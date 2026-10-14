"""Current SEC state and historical decision views; synthetic isolated DB only."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import sec_intelligence as si

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
CIK = "0000320193"
CANDIDATE = {"ticker": "AAPL", "company": "Apple Inc.",
             "technical_score": 5, "technical_direction": "BUY",
             "average_dollar_volume": 100_000_000}


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DATABASE_URL", "")
    monkeypatch.setattr(database, "_SQLITE_DB_PATH", str(tmp_path / "sec-state.db"))
    monkeypatch.setenv("AI_TRADER_CLOUD", "false")
    monkeypatch.setenv("STOCK_SCANNER_TELEGRAM_ENABLED", "false")
    monkeypatch.setenv("SEC_INTELLIGENCE_MODE", "off")
    monkeypatch.setenv("SEC_INTELLIGENCE_KILL_SWITCH", "false")

    def blocked(*_args, **_kwargs):
        raise AssertionError("External HTTP forbidden in SEC snapshot fixtures")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    database.init_database()
    return database.get_db_connection


def universe(at=NOW, members=None):
    members = members or {"AAPL": CIK}
    return si.save_universe(
        {ticker: {"company": ticker, "indexes": ["sp500"]} for ticker in members},
        {cik: [ticker] for ticker, cik in members.items()}, at)[0]


def snapshot(identifier, uid, *, ticker="AAPL", cik=CIK, created=NOW,
             available=None, expires=None, status="verified", adjustment=.01):
    available = available or created
    expires = expires or NOW + timedelta(days=1)
    accession = "0000320193-26-000001"
    facts = [{"kind": "verified_purchase", "accession": accession,
              "accepted_at": si._z(NOW - timedelta(hours=1)),
              "source_url": si._source_url(CIK, accession, "ownership.xml")}]
    evidence = {"coverage": status, "facts": facts,
                "components": {"insider": adjustment, "filing": 0}}
    with database.get_db_connection() as conn:
        conn.execute("""INSERT INTO si_company_snapshots
            (id,ticker,issuer_cik,universe_snapshot_id,effective_available_at,
             created_at,expires_at,data_confidence,adjustment,status,
             evidence_json,evidence_ids_json,policy_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (identifier, ticker, cik, uid, si._z(available), si._z(created),
             si._z(expires), .85, adjustment, status, json.dumps(evidence),
             '["synthetic-evidence"]', si.POLICY))
        conn.commit()


@pytest.mark.parametrize("state", ["unknown", "expired", "issuer_mismatch"])
def test_latest_snapshot_revokes_current_eligibility_without_old_fallback(isolated, state):
    uid = universe(NOW - timedelta(hours=1))
    snapshot("original", uid)
    changed = NOW + timedelta(minutes=1)
    kwargs = {"created": changed}
    if state == "unknown":
        kwargs.update(status="unknown_no_fresh_structured_evidence",
                      adjustment=0, expires=changed)
    elif state == "expired":
        kwargs["expires"] = changed
    else:
        kwargs["cik"] = "0000000042"
    snapshot("latest", uid, **kwargs)
    assert si.snapshots_for([CANDIDATE], NOW)["AAPL"]["id"] == "original"
    after = changed + timedelta(seconds=1)
    assert si.snapshots_for([CANDIDATE], after) == {}
    decorated = si.decorate([CANDIDATE], after)[0]
    assert decorated["sec_adjustment"] == 0
    assert decorated["enhanced_rank_score"] == decorated["baseline_rank_score"]
    assert si.current_evidence(decorated, after, 72) == []


@pytest.mark.parametrize("future_field", ["created", "available"])
def test_future_snapshot_is_not_available_ahead_of_decision(isolated, future_field):
    uid = universe(NOW - timedelta(hours=1))
    snapshot("original", uid)
    future = NOW + timedelta(minutes=1)
    kwargs = {"created": future, "available": NOW}
    if future_field == "available":
        kwargs = {"created": NOW, "available": future}
    snapshot("future-unknown", uid, status="unknown_no_fresh_structured_evidence",
             adjustment=0, expires=future, **kwargs)
    assert si.snapshots_for([CANDIDATE], NOW)["AAPL"]["id"] == "original"
    assert si.snapshots_for([CANDIDATE], future + timedelta(seconds=1)) == {}


def test_future_universe_membership_cannot_rewrite_earlier_view(isolated):
    uid = universe(NOW - timedelta(minutes=1))
    snapshot("original", uid)
    future = NOW + timedelta(minutes=1)
    universe(future, {"AAPL": "0000000042"})
    assert si.snapshots_for([CANDIDATE], NOW)["AAPL"]["id"] == "original"
    assert si.snapshots_for([CANDIDATE], future) == {}


def test_snapshot_order_tracks_newest_state_with_deterministic_ties(isolated):
    uid = universe(NOW - timedelta(hours=1))
    snapshot("older-created", uid, available=NOW)
    changed = NOW + timedelta(minutes=1)
    snapshot("newer-state", uid, created=changed, available=NOW - timedelta(minutes=1))
    assert si.snapshots_for([CANDIDATE], changed)["AAPL"]["id"] == "newer-state"
    snapshot("tie-a", uid, created=changed, available=NOW)
    snapshot("tie-z", uid, created=changed, available=NOW)
    assert si.snapshots_for([CANDIDATE], changed)["AAPL"]["id"] == "tie-z"


def test_busy_issuer_cannot_crowd_out_another_tickers_snapshot(isolated):
    uid = universe(NOW - timedelta(days=1), {"A": "0000000001", "B": "0000000002"})
    for index in range(16):
        snapshot(f"A-{index:02d}", uid, ticker="A", cik="0000000001",
                 created=NOW - timedelta(minutes=index))
    snapshot("B-fresh", uid, ticker="B", cik="0000000002",
             created=NOW - timedelta(hours=1))
    candidates = [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "A"}]
    observed = si.snapshots_for(candidates, NOW)
    assert {ticker: row["id"] for ticker, row in observed.items()} == {
        "A": "A-00", "B": "B-fresh"}
    assert {ticker: row["id"] for ticker, row in
            si.snapshots_for(list(reversed(candidates)), NOW).items()} == {
        "A": "A-00", "B": "B-fresh"}
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT count(*) n FROM si_company_snapshots").fetchone()["n"] == 17


def ownership(form="4", code="P", side="A"):
    return (f"<ownershipDocument><documentType>{form}</documentType>"
        "<periodOfReport>2026-10-14</periodOfReport><issuer><issuerCik>0000320193</issuerCik>"
        "</issuer><reportingOwner><reportingOwnerId><rptOwnerCik>0000000042</rptOwnerCik>"
        "</reportingOwnerId></reportingOwner><nonDerivativeTable><nonDerivativeTransaction>"
        "<securityTitle><value>Common Stock</value></securityTitle>"
        "<transactionDate><value>2026-10-14</value></transactionDate><transactionCoding>"
        f"<transactionCode>{code}</transactionCode></transactionCoding><transactionAmounts>"
        "<transactionShares><value>10</value></transactionShares>"
        "<transactionPricePerShare><value>12.5</value></transactionPricePerShare>"
        f"<transactionAcquiredDisposedCode><value>{side}</value></transactionAcquiredDisposedCode>"
        "</transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>").encode()


def test_matched_disposal_amendment_withdraws_current_purchase_preserving_history(isolated, monkeypatch):
    clock = [NOW]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(si, "datetime", FrozenDateTime)
    monkeypatch.setenv("NEWS_SEC_USER_AGENT", "Synthetic Operator synthetic@example.com")
    monkeypatch.setenv("STOCK_SCANNER_TELEGRAM_ENABLED", "false")
    uid = universe(NOW - timedelta(hours=2))
    original, amended = "0000320193-26-000001", "0000320193-26-000002"
    accepted = NOW - timedelta(hours=1)

    def queue(accession, form, published):
        assert si._queue_filing({"accessionNumber": accession, "form": form,
            "acceptanceDateTime": si._z(published), "primaryDocument": "ownership.xml"},
            CIK, ["AAPL"], uid, clock[0], [10])

    queue(original, "4", accepted)
    monkeypatch.setattr(si, "fetch", lambda *_a, **_k: (ownership(), {}))
    assert si.process_jobs(clock[0])["processed"] == 1
    decided = NOW + timedelta(seconds=1)
    before = si.decorate([CANDIDATE], decided)[0]
    assert before["sec_adjustment"] == .01
    assert si.current_evidence(before, decided, 72)[0]["published_at"] == si._z(accepted)
    si.persist_decisions("historical-scan", [before], {"AAPL"}, decided, "paper")
    with database.get_db_connection() as conn:
        old_snapshot = dict(conn.execute("SELECT * FROM si_company_snapshots").fetchone())
        old_decision = dict(conn.execute("SELECT * FROM si_decisions").fetchone())

    clock[0] = NOW + timedelta(minutes=1)
    queue(amended, "4/A", accepted + timedelta(minutes=1))
    monkeypatch.setattr(si, "fetch", lambda *_a, **_k: (ownership("4/A", "S", "D"), {}))
    assert si.process_jobs(clock[0])["processed"] == 1
    after = clock[0] + timedelta(seconds=1)
    latest = si.decorate([CANDIDATE], after)[0]
    assert latest["sec_adjustment"] == 0
    assert latest["sec_coverage"] == "unknown_or_unavailable"
    assert latest["enhanced_rank_score"] == latest["baseline_rank_score"]
    assert si.current_evidence(latest, after, 72) == []
    assert si.decorate([CANDIDATE], decided)[0]["sec_snapshot_id"] == before["sec_snapshot_id"]
    with database.get_db_connection() as conn:
        current = dict(conn.execute("SELECT * FROM si_company_snapshots ORDER BY created_at DESC LIMIT 1").fetchone())
        assert current["status"] == "unknown_no_fresh_structured_evidence"
        assert current["expires_at"] == current["created_at"]
        assert conn.execute("SELECT superseded_by FROM si_filing_jobs WHERE accession=?",
                            (original,)).fetchone()["superseded_by"] == amended
        assert dict(conn.execute("SELECT * FROM si_company_snapshots WHERE id=?",
                                 (old_snapshot["id"],)).fetchone()) == old_snapshot
        assert dict(conn.execute("SELECT * FROM si_decisions").fetchone()) == old_decision
        assert conn.execute("SELECT count(*) n FROM scanner_telegram_outbox").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) n FROM scanner_orders").fetchone()["n"] == 0


def test_normal_snapshot_keeps_original_publication_and_expires_without_rejuvenation(isolated):
    uid = universe(NOW - timedelta(hours=2))
    snapshot("normal", uid)
    candidate = si.decorate([CANDIDATE], NOW)[0]
    route = si.current_evidence(candidate, NOW, 72)
    assert candidate["sec_adjustment"] == .01
    assert route[0]["published_at"] == si._z(NOW - timedelta(hours=1))
    assert si.current_evidence(candidate, NOW + timedelta(hours=73), 72) == []
    assert si.snapshots_for([CANDIDATE], NOW + timedelta(days=2)) == {}


@pytest.mark.parametrize("mode,killed,eligible", [
    ("off", False, False), ("shadow", False, False),
    ("paper", True, False), ("paper", False, True)])
def test_current_sec_news_route_remains_paper_only(isolated, monkeypatch, mode, killed, eligible):
    import stock_scanner
    import signal_news
    uid = universe(NOW - timedelta(hours=2))
    snapshot("normal", uid)
    candidate = si.decorate([CANDIDATE], NOW)[0]
    monkeypatch.setattr(stock_scanner.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(stock_scanner, "_read_news_cache", lambda: {})
    monkeypatch.setattr(stock_scanner, "_write_news_cache", lambda _cache: None)
    monkeypatch.setattr(stock_scanner, "fetch_recent_news", lambda *_a, **_k: [])
    monkeypatch.setattr(signal_news, "existing_news", lambda *_a, **_k: {})
    cfg = {"shortlist_limit": 1, "news_max_age_hours": 72, "news_cache_ttl": 60,
           "sec_intelligence_mode": mode, "sec_intelligence_killed": killed}
    rows, rejected = stock_scanner.enrich_and_rank_candidates([candidate], {}, cfg)
    assert bool(rows) == eligible
    if eligible:
        assert rows[0]["news"][0]["sec_evidence_route"] is True
    else:
        assert rejected == [{"ticker": "AAPL", "reason": "insufficient_current_news"}]
