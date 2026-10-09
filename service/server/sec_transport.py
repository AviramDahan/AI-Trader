"""One fair-access clock for every SEC caller in the scanner deployment.

The reservation is committed before network I/O. No database transaction is
held while a slow SEC response is read. A crashed caller only wastes a slot.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests

_LOCAL_LOCK = threading.Lock()
_LOCAL_NEXT = 0.0
_ALLOWED = (
    re.compile(r"/submissions/CIK\d{10}(?:-submissions-\d{3})?\.json"),
    re.compile(r"/api/xbrl/companyfacts/CIK\d{10}\.json"),
    re.compile(r"/Archives/edgar/data/\d{1,10}/\d{18}/(?:xsl[A-Za-z0-9]+/)?[A-Za-z0-9_.-]{1,180}"),
    re.compile(r"/Archives/edgar/data/\d{1,10}/\d{18}/index\.json"),
    re.compile(r"/files/company_tickers_exchange\.json"),
    re.compile(r"/cgi-bin/browse-edgar"),
)


def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in {"www.sec.gov", "data.sec.gov"}
            or parts.username or parts.password or parts.port or parts.fragment
            or not any(pattern.fullmatch(parts.path) for pattern in _ALLOWED)):
        raise ValueError("sec_url_not_allowlisted")
    if parts.query and not (parts.hostname == "www.sec.gov" and parts.path == "/cgi-bin/browse-edgar"
                            and parts.query == "action=getcurrent&output=atom&count=100"):
        raise ValueError("sec_query_not_allowlisted")
    if ((parts.hostname == "data.sec.gov" and not parts.path.startswith(("/submissions/", "/api/xbrl/")))
            or (parts.hostname == "www.sec.gov" and not parts.path.startswith(
                ("/Archives/", "/files/", "/cgi-bin/")))):
        raise ValueError("sec_host_path_mismatch")
    return url


def reserve() -> None:
    """At most two SEC requests per second across scanner processes/threads."""
    global _LOCAL_NEXT
    gap = max(.5, float(os.getenv("STOCK_SCANNER_SEC_REQUEST_GAP_SECONDS", ".5")))
    if os.getenv("AI_TRADER_CLOUD") == "true":
        from database import get_db_connection

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT pg_advisory_xact_lock(719325,1)")
            now = float(cur.execute("SELECT EXTRACT(EPOCH FROM clock_timestamp()) stamp").fetchone()["stamp"])
            row = cur.execute("SELECT value_json FROM scanner_settings WHERE key='sec_request_slot'").fetchone()
            prior = float(json.loads(row["value_json"])["next_at"]) if row else now
            slot = max(now, prior)
            if slot - now > 15:
                raise RuntimeError("sec_request_queue_busy")
            cur.execute("""INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('sec_request_slot',?,?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",
                (json.dumps({"next_at": slot + gap}), datetime.now(timezone.utc).isoformat()))
            conn.commit()
        delay = slot - now
    else:
        with _LOCAL_LOCK:
            now = time.monotonic()
            slot = max(now, _LOCAL_NEXT)
            _LOCAL_NEXT = slot + gap
            delay = slot - now
    if delay:
        time.sleep(delay)


def fetch(url: str, user_agent: str, *, max_bytes: int = 2_000_000,
          etag: str = "", modified: str = "") -> tuple[bytes | None, dict[str, str]]:
    validate_url(url)
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", user_agent or "") or "\n" in user_agent:
        raise ValueError("sec_operator_contact_required")
    reserve()
    headers = {"User-Agent": user_agent, "Accept": "application/json,application/xml,text/xml,text/html",
               "Accept-Encoding": "identity"}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, headers=headers, timeout=(4, 12), stream=True, allow_redirects=False) as response:
            if response.status_code == 304:
                return None, {"etag": etag, "modified": modified}
            if response.status_code in {403, 429, 500, 502, 503, 504}:
                from retry_policy import DeferredProviderError
                value = response.headers.get("Retry-After", "")
                if value.isdigit():
                    delay = int(value)
                else:
                    try:
                        delay = int((parsedate_to_datetime(value).astimezone(timezone.utc) -
                                     datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError, IndexError):
                        delay = 300
                raise DeferredProviderError(response.status_code, min(max(delay, 30), 3600))
            response.raise_for_status()  # A redirect is never followed to another host.
            if response.status_code != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("sec_response_not_plain_200")
            size = response.headers.get("Content-Length", "")
            if size.isdigit() and int(size) > max_bytes:
                raise ValueError("sec_document_too_large")
            chunks, length = [], 0
            for chunk in response.iter_content(16384):
                length += len(chunk)
                if length > max_bytes:
                    raise ValueError("sec_document_too_large")
                chunks.append(chunk)
            return b"".join(chunks), {"etag": response.headers.get("ETag", ""),
                                      "modified": response.headers.get("Last-Modified", "")}
