"""One fair-access clock for every SEC caller in the scanner deployment.

The reservation is committed before network I/O. No database transaction is
held while a slow SEC response is read. A crashed caller only wastes a slot.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool

_LOCAL_LOCK = threading.Lock()
_LOCAL_NEXT = 0.0
# Cumulative HTTP response time after verified TLS connection establishment.
# DNS and connection/TLS establishment retain Requests' existing limits; this
# is not a hard whole-fetch deadline for an uninterruptible system resolver.
RESPONSE_TIMEOUT_SECONDS = 12
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


class _ResponseDeadline:
    """Own one connected socket and a joined, response-only abort timer."""
    def __init__(self):
        self.transport = None
        self.timer = None
        self.deadline = None
        self.expired = threading.Event()

    def bind(self, transport):
        self.transport = transport
        self.deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS
        self.timer = threading.Timer(RESPONSE_TIMEOUT_SECONDS, self.abort)
        self.timer.daemon = True
        try:
            self.timer.start()
        except BaseException:
            self.timer = None
            transport.close()
            raise
        self.check()  # Expiry may race with returning from connect().

    def abort(self):
        self.expired.set()
        if self.transport is not None:
            try:
                self.transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def check(self):
        if self.expired.is_set() or (self.deadline is not None and time.monotonic() >= self.deadline):
            self.abort()
            raise requests.exceptions.Timeout('sec_response_deadline')

    def close(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer.join()
        if self.transport is not None:
            self.transport.close()


class _ResponseAdapter(HTTPAdapter):
    """Keep Requests TLS behavior; customize only this SEC session's pool."""
    def __init__(self, deadline):
        self.deadline = deadline
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        deadline = self.deadline
        class Connection(HTTPSConnection):
            def connect(self):
                super().connect()
                deadline.bind(self.sock)
        class Pool(HTTPSConnectionPool):
            ConnectionCls = Connection
        # The default mapping is shared by urllib3; never mutate it in place.
        self.poolmanager.pool_classes_by_scheme = {
            **self.poolmanager.pool_classes_by_scheme, 'https': Pool}


def fetch(url: str, user_agent: str, *, max_bytes: int = 2_000_000,
          etag: str = "", modified: str = "") -> tuple[bytes | None, dict[str, str]]:
    """Bound established-response reads; DNS/TLS are not a whole-call cap."""
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
    deadline = _ResponseDeadline()
    try:
        return _read_response(url, headers, max_bytes, etag, modified, deadline)
    except requests.exceptions.RequestException:
        deadline.check()
        raise
    finally:
        deadline.close()


def _read_response(url, headers, max_bytes, etag, modified, deadline):
    with requests.Session() as session:
        session.trust_env = False
        session.mount('https://', _ResponseAdapter(deadline))
        with session.get(url, headers=headers, timeout=(4, 12), stream=True, allow_redirects=False) as response:
            deadline.check()
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
                deadline.check()
                length += len(chunk)
                if length > max_bytes:
                    raise ValueError("sec_document_too_large")
                chunks.append(chunk)
            deadline.check()
            return b"".join(chunks), {"etag": response.headers.get("ETag", ""),
                                      "modified": response.headers.get("Last-Modified", "")}
