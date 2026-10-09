"""Schema-7 decision evidence on isolated PostgreSQL only (no SEC requests)."""
from datetime import datetime, timedelta, timezone

import database
import sec_intelligence as si
import sec_transport


def test_postgres_rendered_form4_failure_recovers_without_replay(pg, monkeypatch):
    from migrations import migrate
    migrate(target_version=7)
    now = datetime.now(timezone.utc)
    uid, _ = si.save_universe({'AAPL': {'company': 'Apple Inc.', 'indexes': ['sp500']}},
                              {'0000320193': ['AAPL']}, now)
    accession = '0000320193-26-000091'
    row = {'accessionNumber': accession, 'form': '4',
           'acceptanceDateTime': si._z(now-timedelta(days=100)),
           'primaryDocument': 'xslF345X05/ownership.xml'}
    assert si._queue_filing(row, '0000320193', ['AAPL'], uid, now, [10])
    with database.get_db_connection() as conn:
        conn.execute("UPDATE si_filing_jobs SET status='unsupported',error_code='ValueError',attempts=1")
        original = dict(conn.execute('SELECT * FROM si_filing_jobs').fetchone())
        conn.commit()
    xml = b'''<ownershipDocument><documentType>4</documentType><periodOfReport>2026-07-01</periodOfReport>
    <issuer><issuerCik>0000320193</issuerCik></issuer><reportingOwner><reportingOwnerId>
    <rptOwnerCik>0000000042</rptOwnerCik></reportingOwnerId></reportingOwner>
    <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
    <transactionDate><value>2026-07-01</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>10</value></transactionShares>
    <transactionPricePerShare><value>12</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>'''
    fetched = []
    def fake_fetch(url, *_a, **_k):
        fetched.append(url)
        assert '/xslF345X05/' not in url
        return xml, {}
    monkeypatch.setenv('NEWS_SEC_USER_AGENT', 'Isolated Test Operator test@example.com')
    monkeypatch.setenv('SEC_INTELLIGENCE_MODE', 'paper')
    monkeypatch.setenv('STOCK_SCANNER_TELEGRAM_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_SEC_INTELLIGENCE_THREAD_ID', '345')
    monkeypatch.setenv('SEC_INTELLIGENCE_PUBLIC_NOT_BEFORE', si._z(now-timedelta(hours=1)))
    monkeypatch.setattr(si, 'fetch', fake_fetch)
    assert si.process_jobs(now)['processed'] == 1
    assert si.process_jobs(now)['processed'] == 0
    with database.get_db_connection() as conn:
        restored = dict(conn.execute('SELECT * FROM si_filing_jobs').fetchone())
        for field in ('accession', 'accepted_at', 'published_at', 'first_seen_at'):
            assert restored[field] == original[field]
        assert restored['parser_version'] == si.PARSER and restored['attempts'] == 2
        assert conn.execute('SELECT count(*) n FROM si_transactions').fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) n FROM scanner_orders').fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) n FROM scanner_fills').fetchone()['n'] == 0
    assert len(fetched) == 1


def test_postgres_processing_cursor_rotates_after_failure_and_restart(pg, monkeypatch):
    from migrations import migrate
    migrate(target_version=7)
    now = datetime.now(timezone.utc)
    mapping = {'0000002488': ['AMD'], '0000002969': ['APD'], '0000320193': ['AAPL']}
    uid, _ = si.save_universe({ticker: {'company': ticker, 'indexes': ['sp500']}
                              for symbols in mapping.values() for ticker in symbols}, mapping, now)
    for cik, symbols in mapping.items():
        for suffix in (1, 2):
            row = {'accessionNumber': f'{cik}-26-{suffix:06}', 'form': '4',
                   'acceptanceDateTime': si._z(now-timedelta(days=100)), 'primaryDocument': 'ownership.xml'}
            si._queue_filing(row, cik, symbols, uid, now, [10])
    seen = []
    def fake_fetch(url, *_a, **_k):
        cik = url.split('/data/')[1].split('/')[0].zfill(10)
        seen.append(cik)
        if cik == '0000002488':
            return b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///private">]><x/>', {}
        return (f'<ownershipDocument><documentType>4</documentType><issuer><issuerCik>{cik}</issuerCik>'
                '</issuer><reportingOwner><reportingOwnerId><rptOwnerCik>42</rptOwnerCik>'
                '</reportingOwnerId></reportingOwner></ownershipDocument>').encode(), {}
    monkeypatch.setenv('NEWS_SEC_USER_AGENT', 'Isolated Test Operator test@example.com')
    monkeypatch.setattr(si, 'fetch', fake_fetch)
    assert si.process_jobs(now, limit=1)['failed'] == 1
    assert si.process_jobs(now, limit=1)['processed'] == 1
    assert si.process_jobs(now, limit=1)['processed'] == 1
    with database.get_db_connection() as conn:
        cursor = conn.execute("SELECT value_json FROM scanner_settings WHERE key='si_processing_cursor'").fetchone()
        assert '0000320193' in cursor['value_json']
    # Every call opens a new DB connection; no in-process rotation memory.
    assert si.process_jobs(now, limit=1)['failed'] == 1
    assert si.process_jobs(now, limit=1)['processed'] == 1
    assert si.process_jobs(now, limit=1)['processed'] == 1
    assert seen[:3] == list(mapping) and seen[:3] == seen[3:]
    assert si.process_jobs(now, limit=1)['processed'] == 0


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


def test_shared_postgres_sec_clock_reserves_nonoverlapping_slots(pg, monkeypatch):
    import json
    import cloud_runtime
    monkeypatch.setenv("AI_TRADER_CLOUD", "true")
    monkeypatch.setattr(cloud_runtime, "guard_lease", lambda: None)
    monkeypatch.setattr(sec_transport.time, "sleep", lambda _seconds: None)
    sec_transport.reserve()
    with database.get_db_connection() as connection:
        first = json.loads(connection.execute(
            "SELECT value_json FROM scanner_settings WHERE key='sec_request_slot'").fetchone()["value_json"])["next_at"]
    sec_transport.reserve()
    with database.get_db_connection() as connection:
        second = json.loads(connection.execute(
            "SELECT value_json FROM scanner_settings WHERE key='sec_request_slot'").fetchone()["value_json"])["next_at"]
    assert second-first >= .5


def test_postgres_sec_publication_is_atomic_and_once_per_accession(pg, monkeypatch):
    from migrations import migrate
    migrate(target_version=7)
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("SEC_INTELLIGENCE_MODE", "paper")
    monkeypatch.setenv("STOCK_SCANNER_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_SEC_INTELLIGENCE_THREAD_ID", "345")
    monkeypatch.setenv("SEC_INTELLIGENCE_PUBLIC_NOT_BEFORE", si._z(now-timedelta(hours=1)))
    monkeypatch.setenv("NEWS_SEC_USER_AGENT", "Isolated Test Operator test@example.com")
    uid, _ = si.save_universe({"AAPL": {"company": "Apple Inc.", "indexes": ["sp500"]}},
                              {"0000320193": ["AAPL"]}, now)
    accession = "0000320193-26-000099"
    row = {"accessionNumber": accession, "form": "10-Q",
           "acceptanceDateTime": si._z(now-timedelta(minutes=5)), "primaryDocument": "report.htm"}
    assert si._queue_filing(row, "0000320193", ["AAPL"], uid, now, [10])
    fact = {"metric": "revenue", "namespace": "us-gaap", "tag": "Revenues", "unit": "USD",
            "start": "2026-07-01", "end": "2026-09-30", "value": 120,
            "previous": {"value": 100}, "change_pct": 20, "reason": "comparable_prior"}
    monkeypatch.setattr(si, "fetch", lambda *_a, **_k: (b"synthetic", {}))
    monkeypatch.setattr(si, "_filing_evidence", lambda *_a, **_k: (
        {"kind": "financial", "document_sha256": "synthetic", "comparisons": [fact]}, []))
    assert si.process_jobs(now)["processed"] == 1
    assert si.process_jobs(now)["processed"] == 0
    with database.get_db_connection() as connection:
        rows = connection.execute("SELECT dedupe_key,status FROM scanner_telegram_outbox WHERE event_type=?",
                                  ("sec_intelligence",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == f"sec-intelligence:{accession}"
    assert rows[0]["status"] == "pending"
