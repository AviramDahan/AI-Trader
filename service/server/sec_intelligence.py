"""Bounded SEC decision evidence. No news publication or trading side effects.

Collection is a scanner-role background job; decision reads use immutable,
precomputed snapshots. Filings are untrusted data, never executable prompts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from database import get_db_connection
from sec_transport import fetch

POLICY = "sec-intelligence-v1"
PARSER = "sec-structured-v1"
MAX_PENDING = 600
FORMS = {"4", "4/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "8-K", "8-K/A"}
FINANCIAL_TAGS = {
    "Revenues": "revenue", "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "OperatingIncomeLoss": "operating_income", "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "CashAndCashEquivalentsAtCarryingValue": "cash", "LongTermDebtCurrent": "current_debt",
    "LongTermDebtNoncurrent": "long_term_debt", "CommonStockSharesOutstanding": "shares_outstanding",
}
DEI_TAGS = {"EntityCommonStockSharesOutstanding": "shares_outstanding"}


def mode() -> str:
    value = os.getenv("SEC_INTELLIGENCE_MODE", "off").lower()
    return value if value in {"off", "shadow", "paper"} else "off"


def killed() -> bool:
    return os.getenv("SEC_INTELLIGENCE_KILL_SWITCH", "false").lower() == "true"


def _z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timezone_required")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def _hash(*values) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _number(value: str) -> float | None:
    try:
        number = float(value)
        return number if __import__("math").isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _xml(raw: bytes):
    if len(raw) > 2_000_000 or re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I):
        raise ValueError("unsafe_sec_xml")
    return ET.fromstring(raw)


def _owner_ids(root) -> list[dict]:
    owners = []
    for node in root.findall("reportingOwner"):
        cik = _text(node, "reportingOwnerId/rptOwnerCik")
        if cik.isdigit():
            relation = node.find("reportingOwnerRelationship")
            owners.append({"cik": cik.zfill(10), "name": _text(node, "reportingOwnerId/rptOwnerName")[:120],
                           "director": _text(relation, "isDirector") == "1" if relation is not None else False,
                           "officer": _text(relation, "isOfficer") == "1" if relation is not None else False,
                           "ten_percent": _text(relation, "isTenPercentOwner") == "1" if relation is not None else False})
    return owners


def parse_form4(raw: bytes, accession: str, expected_issuer: str) -> dict:
    """Interpret XML codes literally; P/acquired is not proof of open-market trade."""
    root = _xml(raw)
    document_type = _text(root, "documentType").upper()
    if document_type not in {"4", "4/A"}:
        raise ValueError("ownership_form_invalid")
    issuer = _text(root, "issuer/issuerCik")
    if not issuer.isdigit() or issuer.zfill(10) != expected_issuer:
        raise ValueError("issuer_cik_mismatch")
    owners = _owner_ids(root)
    if not owners:
        raise ValueError("reporting_owner_missing")
    footnotes = {node.get("id"): (node.text or "").strip()[:1200]
                 for node in root.findall("footnotes/footnote")}
    transactions = []
    amendment = document_type == "4/A"
    for table, path in (("non_derivative", "nonDerivativeTable/nonDerivativeTransaction"),
                        ("derivative", "derivativeTable/derivativeTransaction")):
        for index, node in enumerate(root.findall(path)):
            code = _text(node, "transactionCoding/transactionCode").upper()
            side = _text(node, "transactionAmounts/transactionAcquiredDisposedCode/value").upper()
            shares = _number(_text(node, "transactionAmounts/transactionShares/value"))
            price = _number(_text(node, "transactionAmounts/transactionPricePerShare/value"))
            refs = [footnotes.get(n.get("id"), "") for n in node.findall(".//footnoteId")]
            notes = " ".join(filter(None, refs))[:1600]
            plan_flag = _text(node, "transactionCoding/aff10b5One").lower()
            if plan_flag in {"1", "true"}:
                plan = True
            elif plan_flag in {"0", "false"}:
                plan = False
            elif (re.search(r"pursuant to.{0,80}10b5[- ]?1", notes, re.I)
                  and not re.search(r"not pursuant to.{0,80}10b5[- ]?1", notes, re.I)):
                plan = True
            else:
                plan = "unknown"
            private = (True if re.search(r"privat(?:e|ely) (?:placement|negotiat|purchase)", notes, re.I)
                       and not re.search(r"not privat(?:e|ely) (?:placement|negotiat|purchase)", notes, re.I)
                       else "unknown")
            security = _text(node, "securityTitle/value")[:160]
            date = _text(node, "transactionDate/value")
            category = ("purchase" if table == "non_derivative" and code == "P" and side == "A"
                        and shares is not None and shares > 0 and price is not None and price > 0
                        and re.search(r"(?:common|ordinary|class [a-z] (?:share|stock))", security, re.I)
                        else "derivative" if table == "derivative" else "other")
            # 4/A requires a verified parent before it can contribute a purchase.
            if amendment and category == "purchase":
                category = "amendment_unlinked"
            tx = {"issuer_cik": issuer.zfill(10), "owners": owners, "table": table,
                  "transaction_code": code, "acquired_disposed": side, "security": security,
                  "transaction_at": date, "shares": shares, "price": price,
                  "value": round(shares * price, 2) if shares is not None and price is not None and price > 0 else None,
                  "post_shares": _number(_text(node, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                  "ownership": _text(node, "ownershipNature/directOrIndirectOwnership/value") or "unknown",
                  "plan_10b5_1": plan, "private": private, "footnotes": notes,
                  "purchase_policy_bucket": ("scheduled_or_private" if plan is True or private is True
                                             else "execution_character_unknown"),
                  "category": category, "event_id": _hash(accession, table, index),
                  "transaction_key": _hash(issuer, tuple(sorted(o["cik"] for o in owners)), date,
                                           security.lower(), code, side, table, index)}
            transactions.append(tx)
    return {"issuer_cik": issuer.zfill(10), "issuer": _text(root, "issuer/issuerName")[:180],
            "form": document_type,
            "period_of_report": _text(root, "periodOfReport"),
            "owners": owners, "transactions": transactions, "amendment": amendment}


def _comparable(current: dict, prior: dict) -> bool:
    """Equal concept, unit and fiscal duration; never quarter vs YTD."""
    if (current.get("unit") != prior.get("unit") or current.get("tag") != prior.get("tag")
            or current.get("namespace") != prior.get("namespace")):
        return False
    try:
        end_delta = (_time(current["end"] + "T00:00:00Z") - _time(prior["end"] + "T00:00:00Z")).days
        if not 358 <= end_delta <= 372:
            return False
        starts = (current.get("start"), prior.get("start"))
        if bool(starts[0]) != bool(starts[1]):
            return False
        if starts[0]:
            length = [(_time(x["end"] + "T00:00:00Z") - _time(x["start"] + "T00:00:00Z")).days
                      for x in (current, prior)]
            return abs(length[0] - length[1]) <= 7 and all(70 <= n <= 110 or 350 <= n <= 380 for n in length)
        return True
    except (ValueError, KeyError, TypeError):
        return False


def companyfacts_comparisons(payload: dict, accession: str, accepted_at: str) -> list[dict]:
    result = []
    issuer_cik = str(payload.get("cik") or "").zfill(10)
    source_url = (f"https://data.sec.gov/api/xbrl/companyfacts/CIK{issuer_cik}.json"
                  if payload.get("cik") and issuer_cik.isdigit() and len(issuer_cik) == 10 else None)
    for namespace, tag, metric in [*(('us-gaap', tag, metric) for tag, metric in FINANCIAL_TAGS.items()),
                                   *(('dei', tag, metric) for tag, metric in DEI_TAGS.items())]:
        concept = ((payload.get("facts") or {}).get(namespace) or {}).get(tag) or {}
        for unit, facts in (concept.get("units") or {}).items():
            if unit not in {"USD", "shares"} or (metric == "shares_outstanding") != (unit == "shares"):
                continue
            current = [dict(f, namespace=namespace, tag=tag, unit=unit) for f in facts
                       if f.get("accn") == accession and f.get("form") in {"10-Q", "10-K", "10-Q/A", "10-K/A"}
                       and _number(f.get("val")) is not None]
            for fact in current[:4]:
                prior = [dict(f, namespace=namespace, tag=tag, unit=unit) for f in facts if f.get("accn") != accession
                         and f.get("filed", "") < accepted_at[:10] and _number(f.get("val")) is not None
                         and _comparable(fact, dict(f, namespace=namespace, tag=tag, unit=unit))]
                prior.sort(key=lambda f: (f.get("filed", ""), f.get("accn", "")), reverse=True)
                row = {"metric": metric, "namespace": namespace, "tag": tag, "unit": unit, "start": fact.get("start"),
                       "end": fact.get("end"), "value": fact["val"], "accession": accession,
                       "source_url": source_url,
                       "previous": None, "change_pct": None, "reason": "no_comparable_prior"}
                if prior:
                    previous = prior[0]
                    row["previous"] = {"value": previous["val"], "accession": previous["accn"],
                                       "start": previous.get("start"), "end": previous.get("end"),
                                       "filed": previous["filed"], "source_url": source_url}
                    if previous["val"] != 0:
                        row["change_pct"] = round((fact["val"] / previous["val"] - 1) * 100, 3)
                        row["reason"] = "comparable_prior"
                    else:
                        row["reason"] = "zero_denominator"
                result.append(row)
    matched = {}
    for row in result:
        if row["metric"] in {"revenue", "operating_income"} and row["reason"] == "comparable_prior":
            matched.setdefault((row.get("start"), row.get("end")), {}).setdefault(row["metric"], row)
    for (start, end), pair in matched.items():
        revenue, operating = pair.get("revenue"), pair.get("operating_income")
        if not revenue or not operating:
            continue
        prior_revenue, prior_operating = revenue["previous"], operating["previous"]
        if (revenue["value"] <= 0 or prior_revenue["value"] <= 0
                or (prior_revenue["accession"], prior_revenue["start"], prior_revenue["end"])
                != (prior_operating["accession"], prior_operating["start"], prior_operating["end"])):
            continue
        current_margin = 100 * operating["value"] / revenue["value"]
        prior_margin = 100 * prior_operating["value"] / prior_revenue["value"]
        result.append({"metric": "operating_margin", "namespace": "derived", "tag": "operating_income/revenue",
                       "unit": "percent", "start": start, "end": end, "accession": accession,
                       "value": round(current_margin, 3), "previous": {
                           "value": round(prior_margin, 3), "accession": prior_revenue["accession"],
                           "start": prior_revenue["start"], "end": prior_revenue["end"]},
                       "change_pp": round(current_margin-prior_margin, 3),
                       "reason": "comparable_prior", "source_url": source_url,
                       "source_facts": [revenue["tag"], operating["tag"]]})
    return result[:40]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.length = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and self.length < 24000:
            part = data[:24000-self.length]
            self.parts.append(part)
            self.length += len(part)


def parse_8k_exhibit(raw: bytes) -> dict:
    if len(raw) > 1_000_000:
        raise ValueError("sec_exhibit_too_large")
    parser = _Text()
    parser.feed(raw.decode("utf-8", "replace"))
    text = " ".join(" ".join(parser.parts).split())[:24000]
    hits = [text[max(0, match.start()-100):match.end()+250] for match in
            list(re.finditer(r"\b(?:guidance|outlook|forecast)\b", text, re.I))[:3]]
    concrete = [hit for hit in hits if re.search(
        r"\b(?:raise[sd]?|increase[sd]?|lower[sd]?|cut[s]?|reduce[sd]?|revis(?:e|ed)|update[sd]?)\b", hit, re.I)
        and re.search(r"\b(?:FY\s?\d{2,4}|fiscal|quarter|20\d{2})\b", hit, re.I)]
    return {"guidance_mentions": hits, "specific_guidance_updates": concrete[:2],
            "comparison": "unknown_without_same_period_prior"}


def _source_url(cik: str, accession: str, document: str) -> str:
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("invalid_accession")
    if not re.fullmatch(r"(?:xsl[A-Za-z0-9]+/)?[A-Za-z0-9_.-]{1,180}", document):
        raise ValueError("invalid_sec_document_name")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"


def _rows(payload: dict, key: str):
    recent = payload.get("filings", {}).get(key, {}) if key == "recent" else payload
    accessions = recent.get("accessionNumber") or []
    for index, accession in enumerate(accessions):
        yield {name: values[index] if index < len(values) else None
               for name, values in recent.items() if isinstance(values, list)} | {"accessionNumber": accession}


def save_universe(universe: dict, mapping: dict, at: datetime) -> tuple[str, dict[str, str]]:
    """Only exact issuer CIK/ticker matches are decision eligible."""
    reverse: dict[str, set[str]] = {}
    for cik, symbols in mapping.items():
        if not re.fullmatch(r"\d{10}", str(cik)):
            continue
        for ticker in symbols:
            if ticker in universe:
                reverse.setdefault(ticker, set()).add(cik)
    verified = {ticker: next(iter(ciks)) for ticker, ciks in reverse.items() if len(ciks) == 1}
    members = {ticker: {"company": value["company"], "indexes": value["indexes"],
                         "issuer_cik": verified.get(ticker),
                         "mapping": "verified" if ticker in verified else "unknown_or_ambiguous"}
               for ticker, value in universe.items()}
    snapshot_id = _hash(at.date().isoformat(), members)
    with get_db_connection() as conn:
        conn.execute("""INSERT INTO si_universe_snapshots(id,observed_at,sources_json,members_json)
            VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING""",
            (snapshot_id, _z(at), _json(["sp500", "nasdaq100"]), _json(members)))
        conn.commit()
    return snapshot_id, verified


class QueueFull(Exception):
    pass


def _queue_filing(row: dict, cik: str, symbols: list[str], snapshot_id: str,
                  seen: datetime, budget: list[int]) -> bool:
    accession = str(row.get("accessionNumber") or "")
    form = str(row.get("form") or "").upper()
    if form not in FORMS or not symbols or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        return False
    accepted = row.get("acceptanceDateTime")
    error = None
    try:
        accepted_at = _z(_time(accepted))
        if _time(accepted_at) > seen + timedelta(minutes=10):
            raise ValueError("future_acceptance_time")
        url = _source_url(cik, accession, str(row.get("primaryDocument") or ""))
    except (TypeError, ValueError):
        accepted_at = None
        url = _source_url(cik, accession, "index.json")
        error = "invalid_or_missing_primary_metadata"
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM si_filing_jobs WHERE accession=?", (accession,)).fetchone():
            return False
        if budget[0] <= 0:
            raise QueueFull("sec_filing_queue_capacity")
        cur = conn.execute("""INSERT INTO si_filing_jobs(accession,issuer_cik,tickers_json,form,
            accepted_at,published_at,first_seen_at,source_url,primary_document,status,universe_snapshot_id,error_code)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(accession) DO NOTHING""",
            (accession, cik, _json(sorted(symbols)), form, accepted_at, accepted_at, _z(seen), url,
             str(row.get("primaryDocument") or "")[:180], "unsupported" if error else "queued",
             snapshot_id, error))
        inserted = bool(cur.rowcount)
        conn.commit()
    budget[0] -= int(inserted and not error)
    return inserted


def _user_agent() -> str:
    value = os.getenv("NEWS_SEC_USER_AGENT", "").strip()
    if not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("NEWS_SEC_USER_AGENT_requires_real_operator_contact")
    return value


def discover_cycle(now: datetime | None = None, *, universe=None, mapping=None) -> dict:
    """Round robin over the entire configured universe, never a watchlist."""
    now = now or datetime.now(timezone.utc)
    from stock_scanner import load_universe
    from news_pipeline import _sec_ticker_map

    universe = universe if universe is not None else load_universe()
    mapping = mapping if mapping is not None else _sec_ticker_map(_user_agent(), now)
    snapshot_id, verified = save_universe(universe, mapping, now)
    ciks = sorted(set(verified.values()))
    if not ciks:
        return {"status": "degraded", "reason": "no_verified_issuer_mapping", "queued": 0}
    with get_db_connection() as conn:
        row = conn.execute("SELECT value_json FROM scanner_settings WHERE key='si_discovery_offset'").fetchone()
    offset = int(json.loads(row["value_json"])["offset"]) % len(ciks) if row else 0
    limit = min(8, len(ciks))
    selected = (ciks[offset:] + ciks[:offset])[:limit]
    with get_db_connection() as conn:
        pending = conn.execute("SELECT count(*) n FROM si_filing_jobs WHERE status IN ('queued','retry')").fetchone()["n"]
    budget = [max(0, MAX_PENDING - pending)]
    queued, errors = 0, []
    for cik in selected:
        with get_db_connection() as conn:
            checkpoint = conn.execute("SELECT * FROM si_checkpoints WHERE issuer_cik=?", (cik,)).fetchone()
        prior = dict(checkpoint) if checkpoint else {}
        if prior.get("retry_after") and _time(prior["retry_after"]) > now:
            continue
        try:
            raw, meta = fetch(f"https://data.sec.gov/submissions/CIK{cik}.json", _user_agent(),
                              max_bytes=4_000_000,
                              etag="" if prior.get("catchup_active") else prior.get("etag") or "")
            if raw is not None:
                payload = json.loads(raw)
                if str(payload.get("cik", "")).zfill(10) != cik:
                    raise ValueError("submissions_issuer_mismatch")
                symbols = sorted(t for t, issuer in verified.items() if issuer == cik)
                recent = list(_rows(payload, "recent"))
                for entry in recent:
                    queued += int(_queue_filing(entry, cik, symbols, snapshot_id, now, budget))
                files = sorted((payload.get("filings") or {}).get("files") or [],
                               key=lambda f: str(f.get("filingTo") or ""), reverse=True)
                marker = prior.get("last_accession")
                catchup = bool(prior.get("catchup_active")) or bool(
                    files and (not marker or marker not in {r["accessionNumber"] for r in recent}))
                catchup_marker = prior.get("catchup_marker") if prior.get("catchup_active") else marker
                # If an outage eclipsed the compact recent block, read one
                # official continuation file per turn; never trust page one.
                older_index = int(prior.get("older_file_index") or 0) if prior.get("catchup_active") else 0
                if files and catchup and older_index < len(files):
                    item = files[older_index]
                    filename = str(item.get("name") or "")
                    if re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", filename):
                        older_raw, _ = fetch("https://data.sec.gov/submissions/" + filename,
                                             _user_agent(), max_bytes=4_000_000)
                        older_rows = list(_rows(json.loads(older_raw), "older"))
                        for entry in older_rows:
                            queued += int(_queue_filing(entry, cik, symbols, snapshot_id, now, budget))
                        if catchup_marker and any(r["accessionNumber"] == catchup_marker for r in older_rows):
                            catchup = False
                        # Initial import is bounded to the feature's 90-day
                        # evidence horizon; older data is unknown, not negative.
                        if (not catchup_marker and older_rows and
                                min(str(r.get("acceptanceDateTime") or "")[:10] for r in older_rows)
                                < (now-timedelta(days=90)).date().isoformat()):
                            catchup = False
                    older_index += 1
                    if older_index >= len(files):
                        catchup = False
                else:
                    catchup = False
                with get_db_connection() as conn:
                    conn.execute("""INSERT INTO si_checkpoints(issuer_cik,last_checked_at,last_accession,etag,older_file_index,
                        catchup_active,catchup_marker,retry_after,error_code)
                        VALUES(?,?,?,?,?,?,?,NULL,NULL) ON CONFLICT(issuer_cik) DO UPDATE SET
                        last_checked_at=excluded.last_checked_at,last_accession=excluded.last_accession,
                        etag=excluded.etag,older_file_index=excluded.older_file_index,
                        catchup_active=excluded.catchup_active,catchup_marker=excluded.catchup_marker,
                        retry_after=NULL,error_code=NULL""",
                        (cik, _z(now), recent[0]["accessionNumber"] if recent else marker, meta.get("etag") or "",
                         older_index if catchup else 0, int(catchup), catchup_marker if catchup else None))
                    conn.commit()
            else:
                with get_db_connection() as conn:
                    conn.execute("UPDATE si_checkpoints SET last_checked_at=?,error_code=NULL WHERE issuer_cik=?",
                                 (_z(now), cik))
                    conn.commit()
        except QueueFull:
            errors.append("sec_filing_queue_capacity")
            break
        except Exception as exc:
            from retry_policy import DeferredProviderError
            delay = max(60, float(getattr(exc, "retry_after_seconds", 300))) if isinstance(exc, DeferredProviderError) else 300
            with get_db_connection() as conn:
                conn.execute("""INSERT INTO si_checkpoints(issuer_cik,retry_after,error_code)
                    VALUES(?,?,?) ON CONFLICT(issuer_cik) DO UPDATE SET
                    retry_after=excluded.retry_after,error_code=excluded.error_code""",
                    (cik, _z(now + timedelta(seconds=delay)), type(exc).__name__))
                conn.commit()
            errors.append(type(exc).__name__)
    with get_db_connection() as conn:
        conn.execute("""INSERT INTO scanner_settings(key,value_json,updated_at)
            VALUES('si_discovery_offset',?,?) ON CONFLICT(key) DO UPDATE SET
            value_json=excluded.value_json,updated_at=excluded.updated_at""",
            (_json({"offset": (offset + limit) % len(ciks)}), _z(now)))
        conn.commit()
    return {"status": "degraded" if errors else "ok", "queued": queued,
            "checked": len(selected), "issuer_count": len(ciks), "errors": errors[:5],
            "universe_snapshot_id": snapshot_id}


def _filing_evidence(job: dict, raw: bytes, at: datetime) -> tuple[dict, list[dict]]:
    form = job["form"]
    accession, cik = job["accession"], job["issuer_cik"]
    if form in {"4", "4/A"}:
        actual_url = job["source_url"]
        try:
            parsed = parse_form4(raw, accession, cik)
            if parsed["form"] != form:
                raise ValueError("ownership_form_invalid")
        except (ET.ParseError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc) not in {
                    "issuer_cik_mismatch", "reporting_owner_missing", "ownership_form_invalid"}:
                raise
            # SEC may name its HTML wrapper as the primary document. Follow
            # only the official, same-accession index to locate its XML.
            index = _source_url(cik, accession, "index.json")
            listing, _ = fetch(index, _user_agent(), max_bytes=500_000)
            items = ((json.loads(listing).get("directory") or {}).get("item") or [])
            names = [str(item.get("name") or "") for item in items]
            xml_names = [name for name in names if re.fullmatch(r"[A-Za-z0-9_.-]{1,180}\.xml", name)
                         and name.lower() != "filingsummary.xml"][:5]
            parsed = None
            for xml_name in xml_names:
                candidate_url = _source_url(cik, accession, xml_name)
                candidate_raw, _ = fetch(candidate_url, _user_agent())
                try:
                    candidate = parse_form4(candidate_raw, accession, cik)
                    if candidate["form"] != form:
                        continue
                except (ET.ParseError, ValueError):
                    continue
                actual_url, raw, parsed = candidate_url, candidate_raw, candidate
                break
            if parsed is None:
                raise ValueError("ownership_xml_missing")
        return {"kind": "ownership", "source_url": actual_url,
                "document_sha256": hashlib.sha256(raw).hexdigest(),
                "issuer_cik": cik, "accession": accession,
                "period_of_report": parsed["period_of_report"],
                "owner_ciks": sorted(o["cik"] for o in parsed["owners"]),
                "securities": sorted({t["security"].lower() for t in parsed["transactions"]}),
                "transaction_count": len(parsed["transactions"]),
                "purchase_count": sum(t["category"] == "purchase" for t in parsed["transactions"]),
                "amendment": parsed["amendment"]}, parsed["transactions"]
    if form in {"10-Q", "10-Q/A", "10-K", "10-K/A"}:
        facts_raw, _ = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                             _user_agent(), max_bytes=10_000_000)
        facts = json.loads(facts_raw)
        if str(facts.get("cik", "")).zfill(10) != cik:
            raise ValueError("xbrl_issuer_mismatch")
        return {"kind": "financial", "accession": accession, "issuer_cik": cik,
                "source_url": job["source_url"],
                "document_sha256": hashlib.sha256(raw).hexdigest(),
                "companyfacts_sha256": hashlib.sha256(facts_raw).hexdigest(),
                "comparisons": companyfacts_comparisons(facts, accession, job["accepted_at"])}, []
    if form in {"8-K", "8-K/A"}:
        excerpt = parse_8k_exhibit(raw)
        listing, _ = fetch(_source_url(cik, accession, "index.json"), _user_agent(), max_bytes=500_000)
        items = ((json.loads(listing).get("directory") or {}).get("item") or [])
        for item in items:
            name = str(item.get("name") or "")
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,180}\.(?:html?|txt)", name) and re.search(r"(?:ex|exhibit)[-_.]?99", name, re.I):
                exhibit, _ = fetch(_source_url(cik, accession, name), _user_agent(), max_bytes=1_000_000)
                other = parse_8k_exhibit(exhibit)
                excerpt["guidance_mentions"] = (excerpt["guidance_mentions"] + other["guidance_mentions"])[:3]
                excerpt["specific_guidance_updates"] = (
                    excerpt["specific_guidance_updates"] + other["specific_guidance_updates"])[:2]
                excerpt["exhibit_url"] = _source_url(cik, accession, name)
                excerpt["exhibit_sha256"] = hashlib.sha256(exhibit).hexdigest()
                break
        return {"kind": "current_report", "accession": accession, "issuer_cik": cik,
                "source_url": job["source_url"], "document_sha256": hashlib.sha256(raw).hexdigest(),
                **excerpt}, []
    raise ValueError("unsupported_form")


def _update_snapshots(cik: str, tickers: list[str], universe_snapshot_id: str,
                      at: datetime, conn) -> None:
    """Insert immutable decision data. Historical rows are never revised."""
    start = _z(at - timedelta(days=90))
    filings = [dict(r) for r in conn.execute("""SELECT accession,form,accepted_at,processed_at,
            source_url,evidence_json FROM si_filing_jobs WHERE issuer_cik=? AND status='processed'
            AND superseded_by IS NULL AND accepted_at>=? AND processed_at<=?
            ORDER BY accepted_at DESC LIMIT 300""", (cik, start, _z(at)))]
    transactions = [dict(r) for r in conn.execute("""SELECT event_id,accession,transaction_key,
            category,body_json FROM si_transactions WHERE issuer_cik=? AND effective_available_at<=?
            ORDER BY effective_available_at DESC,event_id""",
            (cik, _z(at)))]
    by_accession = {r["accession"]: r for r in filings}
    unique_purchases: list[dict] = []
    for row in transactions:
        filing = by_accession.get(row["accession"])
        if not filing or row["category"] != "purchase":
            continue
        tx = json.loads(row["body_json"])
        try:
            if tx["transaction_at"] < (at - timedelta(days=90)).date().isoformat():
                continue
        except (KeyError, TypeError):
            continue
        owners = {o["cik"] for o in tx["owners"]}
        signature = (tx["transaction_at"], tx["security"].lower(), tx["shares"], tx["price"], tx["table"])
        # Joint owners reporting the same economic transaction form one
        # purchase group. Disjoint owners with identical terms remain distinct.
        if any(p["signature"] == signature and p["owners"] & owners for p in unique_purchases):
            continue
        unique_purchases.append({"event_id": row["event_id"], "at": tx["transaction_at"],
            "owners": owners, "signature": signature, "value": tx["value"],
            "accession": row["accession"], "policy_bucket": tx["purchase_policy_bucket"]})
    for ticker in tickers:
        fresh, evidence_ids, items = [], [], []
        insider_adjustment = 0.0
        filing_adjustment = 0.0
        scored_financial_periods = set()
        for filing in filings:
            accepted = _time(filing["accepted_at"])
            age_days = (at - accepted).total_seconds() / 86400
            evidence = json.loads(filing["evidence_json"])
            is_ownership = evidence.get("kind") == "ownership"
            eligible_age = 7 if is_ownership else 5
            if not 0 <= age_days <= eligible_age:
                continue
            if is_ownership:
                purchases = [tx for tx in unique_purchases if tx["accession"] == filing["accession"]]
                if not purchases:
                    continue
                owner_count = len(purchases)
                value = sum(tx["value"] or 0 for tx in purchases)
                # These weights are a bounded research hypothesis, not a
                # calibrated probability or proof of an investing edge.
                # P/acquired is verified, but absent execution detail is not
                # proof of an open-market discretionary purchase. Known
                # scheduled/private buys remain review evidence, not a bonus.
                contribution = min(.06, sum(.01 for tx in purchases
                    if tx["policy_bucket"] == "execution_character_unknown"))
                insider_adjustment += contribution
                evidence_ids.extend(tx["event_id"] for tx in purchases)
                items.append({"kind": "verified_purchase", "accession": filing["accession"],
                              "accepted_at": filing["accepted_at"], "source_url": filing["source_url"],
                              "owners": owner_count, "transactions": len(purchases),
                              "total_value": round(value, 2), "adjustment": contribution,
                              "policy_buckets": {bucket: sum(tx["policy_bucket"] == bucket for tx in purchases)
                                                 for bucket in ("execution_character_unknown", "scheduled_or_private")}})
            elif evidence.get("kind") == "financial":
                comparisons = [f for f in evidence.get("comparisons", [])
                               if f.get("reason") == "comparable_prior" and
                               (f.get("change_pct") is not None or f.get("change_pp") is not None)]
                # Opposing validated facts can cancel. Missing/custom tags
                # contribute zero and retain an explicit coverage reason.
                for fact in comparisons:
                    if fact["metric"] not in {"revenue", "operating_income", "operating_cash_flow"}:
                        continue
                    # Companyfacts can expose equivalent GAAP tags and both
                    # the original and amended filing for one fiscal period.
                    # The newest accepted fact wins; one metric/period gets
                    # at most one ranking contribution.
                    period_key = (fact["metric"], fact.get("start"), fact.get("end"), fact["unit"])
                    if period_key in scored_financial_periods:
                        continue
                    scored_financial_periods.add(period_key)
                    # A signed ratio with a negative denominator reverses its
                    # economic meaning; do not score it as improvement/decline.
                    if fact["previous"]["value"] <= 0:
                        continue
                    delta = .01 if fact["change_pct"] >= 10 else -.01 if fact["change_pct"] <= -10 else 0
                    filing_adjustment += delta
                    if delta:
                        evidence_ids.append(_hash(filing["accession"], fact["namespace"], fact["tag"], fact["end"]))
                material_comparisons = [fact for fact in comparisons
                    if (fact.get("change_pct") is not None and abs(fact["change_pct"]) >= 10)
                    or (fact.get("change_pp") is not None and abs(fact["change_pp"]) >= 2)]
                if material_comparisons:
                    items.append({"kind": "comparable_financials", "accession": filing["accession"],
                                  "accepted_at": filing["accepted_at"], "source_url": filing["source_url"],
                                  "comparisons": material_comparisons[:12]})
            elif evidence.get("kind") == "current_report" and evidence.get("specific_guidance_updates"):
                # Text is evidence for AI review, not a fabricated numeric
                # change or automatic positive score.
                items.append({"kind": "specific_guidance_update", "accession": filing["accession"],
                              "accepted_at": filing["accepted_at"], "source_url": filing["source_url"],
                              "exhibit_url": evidence.get("exhibit_url"),
                              "quoted_excerpt": evidence["specific_guidance_updates"][:2]})
                evidence_ids.append(_hash(filing["accession"], "guidance_update"))
            if items and items[-1]["accession"] == filing["accession"]:
                fresh.append(filing)
        conflict = any(item["kind"] == "verified_purchase" for item in items) and any(
            fact.get("metric") in {"revenue", "operating_income", "operating_cash_flow"}
            and fact.get("previous") and fact["previous"]["value"] > 0
            and fact.get("change_pct") is not None and fact["change_pct"] <= -20
            for item in items if item["kind"] == "comparable_financials"
            for fact in item["comparisons"])
        adjustment = round(max(-.10, min(.10, insider_adjustment + filing_adjustment)), 4)
        if conflict:
            adjustment = min(adjustment, -.02)
        status = "verified" if items else "unknown_no_fresh_structured_evidence"
        data_confidence = (.85 if any(item["kind"] != "specific_guidance_update" for item in items)
                           else .60 if items else 0.0)
        available = max((_time(f["processed_at"]) for f in fresh), default=at)
        expiry = min(_time(f["accepted_at"]) + timedelta(days=7 if f["form"].startswith("4") else 5)
                     for f in fresh) if fresh else at
        snapshot_id = _hash(POLICY, ticker, cik, universe_snapshot_id, _z(at), items)
        payload = {"ticker": ticker, "issuer_cik": cik, "facts": items[:12],
                   "purchase_windows": {str(days): sum(tx["at"] >= (at-timedelta(days=days)).date().isoformat()
                                                 for tx in unique_purchases) for days in (7, 30, 90)},
                   "purchase_window_details": {str(days): {
                       "transaction_groups": len(group),
                       "verified_value_sum": round(sum(tx["value"] for tx in group if tx["value"] is not None), 2),
                       "independent_buyer_groups": len(group)}
                       for days in (7, 30, 90)
                       for group in [[tx for tx in unique_purchases if tx["at"] >=
                                      (at-timedelta(days=days)).date().isoformat()]]},
                   "coverage": status, "source": "SEC EDGAR structured filings",
                   "material_conflict": conflict,
                   "data_confidence": data_confidence, "policy_version": POLICY,
                   "components": {"insider": round(insider_adjustment, 4),
                                  "filing": round(filing_adjustment, 4)}}
        conn.execute("""INSERT INTO si_company_snapshots(id,ticker,issuer_cik,universe_snapshot_id,
                effective_available_at,created_at,expires_at,data_confidence,adjustment,status,
                evidence_json,evidence_ids_json,policy_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING""",
                (snapshot_id, ticker, cik, universe_snapshot_id, _z(available), _z(at), _z(expiry),
                 data_confidence, adjustment, status, _json(payload), _json(evidence_ids), POLICY))


def process_jobs(now: datetime | None = None, limit: int = 2) -> dict:
    now = now or datetime.now(timezone.utc)
    with get_db_connection() as conn:
        jobs = [dict(r) for r in conn.execute("""WITH due AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY issuer_cik ORDER BY first_seen_at,accession) AS issuer_rank
            FROM si_filing_jobs WHERE status IN ('queued','retry')
            AND (next_attempt_at IS NULL OR next_attempt_at<=?))
            SELECT * FROM due ORDER BY issuer_rank,first_seen_at,accession LIMIT ?""",
            (_z(now), min(max(limit, 1), 4)))]
    processed, failures = 0, []
    for job in jobs:
        try:
            raw, _ = fetch(job["source_url"], _user_agent(), max_bytes=2_000_000)
            evidence, transactions = _filing_evidence(job, raw, now)
            processed_at = datetime.now(timezone.utc)
            with get_db_connection() as conn:
                conn.execute("""UPDATE si_filing_jobs SET status='processed',attempts=attempts+1,
                    document_sha256=?,parser_version=?,processed_at=?,error_code=NULL,evidence_json=?
                    WHERE accession=? AND status IN ('queued','retry')""",
                    (evidence["document_sha256"], PARSER, _z(processed_at), _json(evidence), job["accession"]))
                for tx in transactions:
                    conn.execute("""INSERT INTO si_transactions(event_id,accession,issuer_cik,transaction_key,
                        transaction_at,owners_json,category,body_json,effective_available_at)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING""",
                        (tx["event_id"], job["accession"], job["issuer_cik"], tx["transaction_key"],
                         tx["transaction_at"], _json(tx["owners"]), tx["category"], _json(tx), _z(processed_at)))
                if job["form"] == "4/A":
                    # SEC does not provide a universal parent accession in 4/A.
                    # Only one original with the same report period, owner set,
                    # security set and transaction count may be superseded.
                    originals = conn.execute("""SELECT accession,evidence_json FROM si_filing_jobs
                        WHERE issuer_cik=? AND form='4' AND accepted_at<=? AND status='processed'
                        AND superseded_by IS NULL""", (job["issuer_cik"], job["accepted_at"])).fetchall()
                    signature = tuple(evidence.get(key) for key in ("period_of_report", "transaction_count"))
                    matches = []
                    for old in originals:
                        prior = json.loads(old["evidence_json"])
                        if (signature == tuple(prior.get(key) for key in ("period_of_report", "transaction_count"))
                                and evidence.get("owner_ciks") == prior.get("owner_ciks")
                                and evidence.get("securities") == prior.get("securities")
                                and signature[0] and signature[1]):
                            matches.append(old["accession"])
                    if len(matches) == 1:
                        conn.execute("UPDATE si_filing_jobs SET superseded_by=? WHERE accession=?",
                                     (job["accession"], matches[0]))
                        for tx in transactions:
                            if tx["category"] == "amendment_unlinked":
                                tx["category"] = "purchase"
                                conn.execute("UPDATE si_transactions SET category=?,body_json=? WHERE event_id=?",
                                             ("purchase", _json(tx), tx["event_id"]))
                _update_snapshots(job["issuer_cik"], json.loads(job["tickers_json"]),
                                  job["universe_snapshot_id"], processed_at, conn)
                conn.commit()
            processed += 1
        except Exception as exc:
            from retry_policy import DeferredProviderError
            transient = isinstance(exc, (DeferredProviderError, TimeoutError, ConnectionError,
                                         requests.exceptions.Timeout, requests.exceptions.ConnectionError))
            status = "retry" if transient and job["attempts"] < 5 else "unsupported"
            delay = min(3600, 60 * 2 ** min(job["attempts"], 5))
            if isinstance(exc, DeferredProviderError):
                delay = max(delay, exc.retry_after_seconds)
            with get_db_connection() as conn:
                conn.execute("""UPDATE si_filing_jobs SET status=?,attempts=attempts+1,
                    next_attempt_at=?,error_code=? WHERE accession=?""",
                    (status, _z(now + timedelta(seconds=delay)) if status == "retry" else None,
                     type(exc).__name__, job["accession"]))
                conn.commit()
            failures.append(type(exc).__name__)
    return {"processed": processed, "failed": len(failures), "errors": failures[:4]}


def snapshots_for(candidates: list[dict], decided_at: datetime) -> dict[str, dict]:
    """One read-only, time-fenced lookup for the whole technical universe."""
    if not candidates:
        return {}
    tickers = sorted({r["ticker"] for r in candidates})
    placeholders = ",".join("?" for _ in tickers)
    with get_db_connection() as conn:
        if os.getenv("AI_TRADER_CLOUD") == "true":
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            conn.execute("SET LOCAL statement_timeout='8s'")
        latest = conn.execute("SELECT id,members_json FROM si_universe_snapshots WHERE observed_at<=? ORDER BY observed_at DESC LIMIT 1",
                              (_z(decided_at),)).fetchone()
        if not latest:
            return {}
        membership = json.loads(latest["members_json"])
        rows = conn.execute(f"""SELECT id,ticker,issuer_cik,effective_available_at,created_at,
            expires_at,data_confidence,adjustment,status,evidence_json,evidence_ids_json,policy_version
            FROM si_company_snapshots WHERE ticker IN ({placeholders})
            AND effective_available_at<=? AND created_at<=? AND expires_at>=?
            ORDER BY effective_available_at DESC LIMIT ?""",
            (*tickers, _z(decided_at), _z(decided_at), _z(decided_at), len(tickers)*8)).fetchall()
    result = {}
    for raw in rows:
        row = dict(raw)
        ticker = row["ticker"]
        if ticker in result or row["status"] != "verified":
            continue
        if (membership.get(ticker) or {}).get("issuer_cik") != row["issuer_cik"]:
            continue
        row["evidence"] = json.loads(row.pop("evidence_json"))
        row["evidence_ids"] = json.loads(row.pop("evidence_ids_json"))
        result[ticker] = row
    return result


def decorate(candidates: list[dict], at: datetime | None = None, *, snapshots=None) -> list[dict]:
    """No network, AI, news or trading writes on the scan path."""
    at = at or datetime.now(timezone.utc)
    snapshots = snapshots if snapshots is not None else snapshots_for(candidates, at)
    output = []
    for candidate in candidates:
        row = dict(candidate)
        snapshot = snapshots.get(row["ticker"])
        baseline = round(float(row["technical_score"]) / 7, 4)
        adjustment = float(snapshot["adjustment"]) if snapshot and row.get("technical_direction") == "BUY" else 0.0
        row.update(baseline_rank_score=baseline, sec_adjustment=adjustment,
                   insider_adjustment=float(snapshot["evidence"].get("components", {}).get("insider", 0)) if snapshot else 0.0,
                   filing_adjustment=float(snapshot["evidence"].get("components", {}).get("filing", 0)) if snapshot else 0.0,
                   enhanced_rank_score=round(baseline+adjustment, 4),
                   sec_snapshot_id=snapshot["id"] if snapshot else None,
                   sec_evidence_ids=snapshot["evidence_ids"] if snapshot else [],
                   sec_coverage="verified" if snapshot else "unknown_or_unavailable")
        if snapshot:
            row["sec_intelligence"] = dict(snapshot["evidence"],
                                           snapshot_id=snapshot["id"],
                                           effective_available_at=snapshot["effective_available_at"],
                                           expires_at=snapshot["expires_at"],
                                           adjustment=adjustment)
        output.append(row)
    return output


def current_evidence(candidate: dict, decided_at: datetime, max_age_hours: int) -> list[dict]:
    """Fresh official facts are an alternative to Yahoo, never synthetic Yahoo."""
    sec = candidate.get("sec_intelligence") or {}
    if sec.get("coverage") != "verified" or _time(sec["effective_available_at"]) > decided_at:
        return []
    result = []
    for item in sec.get("facts", [])[:5]:
        if item["kind"] not in {"verified_purchase", "comparable_financials", "specific_guidance_update"}:
            continue
        accepted = _time(item["accepted_at"])
        age_hours = (decided_at - accepted).total_seconds() / 3600
        if not 0 <= age_hours <= max_age_hours:
            continue
        result.append({"title": f"{candidate['company']} — SEC {item['kind'].replace('_', ' ')}",
                       "publisher": "U.S. Securities and Exchange Commission", "url": item["source_url"],
                       "published_at": item["accepted_at"], "age_hours": round(age_hours, 2),
                       "relevance": 0.0, "sec_evidence_route": True,
                       "sec_snapshot_id": sec["snapshot_id"], "accession": item["accession"],
                       "source_excerpt": (item.get("quoted_excerpt") or [""])[0][:400]
                                         if item["kind"] == "specific_guidance_update"
                                         else "Verified structured SEC facts; see sec_intelligence snapshot.",
                       "provenance": [{"ingestion_provider": "sec_intelligence",
                                       "original_url": item["source_url"], "published_at": item["accepted_at"]}]})
    return result


def persist_decisions(scan_id: str, rows: list[dict], selected: set[str],
                      at: datetime, current_mode: str, reasons: dict[str, str] | None = None,
                      shortlist_limit: int = 25) -> None:
    if current_mode == "off":
        return
    with get_db_connection() as conn:
        for row in rows:
            reason = (reasons or {}).get(row["ticker"])
            if reason is None and row["ticker"] not in selected:
                reason = "not_selected_for_review"
            conn.execute("""INSERT INTO si_decisions(scan_id,ticker,mode,baseline_rank_score,
                sec_adjustment,insider_adjustment,filing_adjustment,enhanced_rank_score,
                sec_snapshot_id,review_baseline_score,review_enhanced_score,
                evidence_ids_json,rejection_reason,shortlist_limit,decided_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scan_id,ticker,mode) DO NOTHING""",
                (scan_id, row["ticker"], current_mode, row["baseline_rank_score"],
                 row["sec_adjustment"], row.get("insider_adjustment", 0), row.get("filing_adjustment", 0),
                 row["enhanced_rank_score"], row["sec_snapshot_id"],
                 row.get("review_baseline_score"), row.get("review_enhanced_score"),
                 _json(row["sec_evidence_ids"]), reason, shortlist_limit, _z(at)))
        conn.commit()


def coverage_status() -> dict:
    with get_db_connection() as conn:
        snapshot = conn.execute("SELECT observed_at,members_json FROM si_universe_snapshots ORDER BY observed_at DESC LIMIT 1").fetchone()
        pending = conn.execute("SELECT count(*) n FROM si_filing_jobs WHERE status IN ('queued','retry')").fetchone()["n"]
        errors = conn.execute("SELECT count(*) n FROM si_checkpoints WHERE error_code IS NOT NULL").fetchone()["n"]
        unsupported = conn.execute("SELECT count(*) n FROM si_filing_jobs WHERE status='unsupported'").fetchone()["n"]
        retrying = conn.execute("SELECT count(*) n FROM si_filing_jobs WHERE status='retry'").fetchone()["n"]
        last = conn.execute("SELECT MAX(processed_at) at FROM si_filing_jobs WHERE status='processed'").fetchone()["at"]
        influenced = conn.execute("SELECT count(*) n FROM si_decisions WHERE sec_adjustment!=0").fetchone()["n"]
    members = json.loads(snapshot["members_json"]) if snapshot else {}
    return {"mode": mode(), "kill_switch": killed(), "universe_count": len(members),
            "mapped_count": sum(v["mapping"] == "verified" for v in members.values()),
            "universe_observed_at": snapshot["observed_at"] if snapshot else None,
            "pending_filings": pending, "retrying_filings": retrying,
            "unsupported_filings": unsupported, "mapping_or_provider_errors": errors,
            "last_processed_at": last, "influenced_decisions": influenced,
            "request_limit_per_second": 2, "policy_version": POLICY}
