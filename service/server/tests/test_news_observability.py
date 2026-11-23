import sqlite3
from datetime import datetime, timezone

from news_observability import build


AT = datetime(2026, 11, 23, 20, tzinfo=timezone.utc)


def projection_fixture():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE scanner_news(id INT PRIMARY KEY, analysis_status TEXT, analysis_error TEXT);
        CREATE TABLE scanner_news_sources(provider TEXT, news_id INT, collected_at TEXT);
        CREATE TABLE scanner_news_providers(provider TEXT,status TEXT,last_attempt_at TEXT,last_received_count INT,
            last_ingested_count INT,last_duplicate_count INT,last_rejected_assignment_count INT,last_rejected_date_count INT);
        CREATE TABLE scanner_telegram_outbox(dedupe_key TEXT PRIMARY KEY, event_type TEXT, status TEXT,
            created_at TEXT, sent_at TEXT, last_error TEXT);
        CREATE TABLE scanner_news_watchlist(ticker TEXT, enabled INT);
        CREATE TABLE si_universe_snapshots(id TEXT, members_json TEXT, observed_at TEXT);
        CREATE TABLE si_filing_jobs(accession TEXT PRIMARY KEY, issuer_cik TEXT, accepted_at TEXT, form TEXT, status TEXT);
        CREATE TABLE si_checkpoints(issuer_cik TEXT, last_checked_at TEXT);
        INSERT INTO scanner_news VALUES (7,'analyzed',NULL),(8,'analysis_error','private-error-body');
        INSERT INTO scanner_news_providers VALUES ('quiet','ok','2026-11-23T15:00:00Z',2,0,1,1,0);
        INSERT INTO scanner_news_sources VALUES
            ('sec',7,'2026-11-23T14:00:00Z'),('sec',7,'2026-11-23T14:00:01+00:00'),
            ('sec',8,'2026-11-23T15:00:00Z'),('wire',7,'2026-11-23T16:00:00Z'),
            ('wire',8,'2026-11-23T20:00:00Z');
        INSERT INTO scanner_telegram_outbox VALUES
            ('market-news:7:v1','market_news','sent','2026-11-23T13:59:00Z','2026-11-23T16:00:00Z',NULL),
            ('stock-news:7:v1:SYN','stock_news','sent','2026-11-23T15:00:00Z','2026-11-23T17:00:00Z',NULL),
            ('market-news:8:v1','market_news','cancelled','2026-11-23T17:00:00Z',NULL,'company_report_requires_structured_filing'),
            ('sec-intelligence:one','sec_intelligence','sent','2026-11-22T13:00:00Z','2026-11-22T13:05:00Z',NULL);
        INSERT INTO scanner_news_watchlist VALUES ('SYN',1),('SYN.B',1),('UNKNOWN',1),('OFF',0);
        INSERT INTO si_universe_snapshots VALUES ('prior','{
           "SYN":{"mapping":"verified","issuer_cik":"0000000001"},
           "SYN.B":{"mapping":"verified","issuer_cik":"0000000001"},
           "UNKNOWN":{"mapping":"unknown_or_ambiguous","issuer_cik":"0000000002"}}','2026-11-23T12:00:00Z'),
            ('future','{}','2026-11-23T21:00:00Z');
        INSERT INTO si_filing_jobs VALUES
            ('one','0000000001','2026-11-22T13:00:00Z','10-Q','processed'),
            ('two','0000000001','2026-11-22T14:00:00Z','10-Q/A','processed'),
            ('three','0000000001','2026-11-22T15:00:00Z','8-K','processed'),
            ('four','0000000002','2026-11-22T16:00:00Z','10-K','processed');
        INSERT INTO si_checkpoints VALUES ('0000000001','2026-11-23T13:00:00Z');
        PRAGMA query_only=ON;
    """)
    return conn


def test_attribution_separates_receipts_acks_and_exact_sec_filings(monkeypatch):
    monkeypatch.delenv('NEWS_EVENTS_RUNTIME', raising=False)
    with projection_fixture() as conn:
        data = build(conn, AT)
    sec, wire, quiet = data['sources']['rows']
    assert (sec['receipts'], sec['items'], sec['linked_acknowledged']) == (3, 2, 1)
    assert sec['stages'] == {'analyzed': 1, 'error': 1}
    assert sec['reasons'] == {'other': 1}
    assert (wire['receipts'], wire['linked_acknowledged']) == (1, 1)
    assert quiet['receipts'] == 0 and quiet['latest_check']['counts']['rejected_assignment'] == 1
    assert 'private-error-body' not in str(data)
    market = data['delivery']['rows'][0]
    assert market['counts'] == {'queued_in_window': 1, 'acknowledged': 1, 'cancelled': 1}
    assert market['reasons'] == {'company_report_requires_structured_filing': 1}
    syn, second_class, unknown = data['earnings']['rows']
    assert syn['counts'] == second_class['counts'] == {
        'discovered': 2, 'processed': 2, 'acknowledged': 1, 'processed_without_notice': 1,
    }
    assert syn['discovery_checked_at'] == '2026-11-23T13:00:00Z'
    assert unknown['counts'] is None


def test_canonical_version_links_by_durable_route(monkeypatch):
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'true')
    with projection_fixture() as conn:
        conn.executescript("""
            PRAGMA query_only=OFF;
            CREATE TABLE ne_control (id INT, mode TEXT);
            CREATE TABLE ne_sources (provider_id TEXT,event_id TEXT,collected_at TEXT,active INT);
            CREATE TABLE ne_events (event_id TEXT,status TEXT,reason TEXT);
            CREATE TABLE ne_outbox (dedupe_key TEXT,event_id TEXT,topic TEXT);
            INSERT INTO ne_control VALUES (1,'canonical');
            INSERT INTO ne_events VALUES ('e1','analyzed',NULL),('e2','blocked','identity_unverified');
            INSERT INTO ne_sources VALUES ('wire','e1','2026-11-23T15:00:00Z',1),
                ('wire','e2','2026-11-23T15:00:00Z',1),('withdrawn','e1','2026-11-23T15:00:00Z',0);
            INSERT INTO ne_outbox VALUES ('stock-news:7:v1:SYN','e1','important_stock_news');
            PRAGMA query_only=ON;
        """)
        data = build(conn, AT)
    wire, withdrawn = data['sources']['rows']
    assert wire['items'] == 2 and wire['linked_acknowledged'] == 1
    assert wire['reasons'] == {'identity_unverified': 1}
    assert withdrawn['receipts'] == 1 and withdrawn['linked_acknowledged'] == 0
    assert data['delivery']['rows'][0]['route'] == 'important_stock_news'
    assert data['delivery']['rows'][0]['basis'] == 'canonical_route'


def test_capped_cohorts_are_marked_partial(monkeypatch):
    monkeypatch.setattr('news_observability.NEWS_LIMIT', 1)
    monkeypatch.setattr('news_observability.WATCH_LIMIT', 1)
    monkeypatch.delenv('NEWS_EVENTS_RUNTIME', raising=False)
    with projection_fixture() as conn:
        data = build(conn, AT)
    assert all(data[key]['partial'] for key in ('sources', 'delivery', 'earnings'))
