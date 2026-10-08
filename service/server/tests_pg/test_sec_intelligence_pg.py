"""Schema-7 decision evidence on isolated PostgreSQL only (no SEC requests)."""
from datetime import datetime, timedelta, timezone

import database
import sec_intelligence as si


def test_schema7_snapshot_decisions_and_idempotent_migration(pg, monkeypatch):
    from migrations import migrate
    migrate(target_version=7)
    now = datetime.now(timezone.utc)
    universe = {"AAPL": {"company": "Apple Inc.", "indexes": ["sp500"]}}
    uid, verified = si.save_universe(universe, {"0000320193": ["AAPL"]}, now)
    assert verified == {"AAPL": "0000320193"}
    row = {"accessionNumber": "0000320193-26-000001", "form": "4",
           "acceptanceDateTime": si._z(now-timedelta(minutes=5)), "primaryDocument": "ownership.xml"}
    assert si._queue_filing(row, "0000320193", ["AAPL"], uid, now, [10])
    assert not si._queue_filing(row, "0000320193", ["AAPL"], uid, now, [10])
    xml = b"""<ownershipDocument><documentType>4</documentType><periodOfReport>2026-10-08</periodOfReport>
    <issuer><issuerCik>0000320193</issuerCik></issuer><reportingOwner><reportingOwnerId>
    <rptOwnerCik>0000000042</rptOwnerCik></reportingOwnerId></reportingOwner>
    <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
    <transactionDate><value>2026-10-08</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>10</value></transactionShares>
    <transactionPricePerShare><value>12</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    monkeypatch.setenv("NEWS_SEC_USER_AGENT", "Isolated Test Operator test@example.com")
    monkeypatch.setattr(si, "fetch", lambda *_a, **_k: (xml, {}))
    assert si.process_jobs(now)["processed"] == 1
    candidates = si.decorate([{"ticker": "AAPL", "technical_score": 5,
        "technical_direction": "BUY"}], datetime.now(timezone.utc))
    assert candidates[0]["sec_adjustment"] > 0
    si.persist_decisions("scan-test", candidates, {"AAPL"}, datetime.now(timezone.utc), "shadow")
    si.persist_decisions("scan-test", candidates, {"AAPL"}, datetime.now(timezone.utc), "shadow")
    with database.get_db_connection() as connection:
        assert connection.execute("SELECT MAX(version) n FROM schema_migrations").fetchone()["n"] == 7
        assert connection.execute("SELECT count(*) n FROM si_decisions").fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM si_transactions").fetchone()["n"] == 1
