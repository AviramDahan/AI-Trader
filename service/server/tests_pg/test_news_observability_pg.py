from datetime import datetime, timezone

from database import get_db_connection
from news_observability import build


def test_private_news_observation_on_a_migrated_read_only_database(pg, monkeypatch):
    monkeypatch.delenv('NEWS_EVENTS_RUNTIME', raising=False)
    now = datetime(2026, 11, 23, 20, tzinfo=timezone.utc)
    stamp = '2026-11-23T19:00:00Z'
    with get_db_connection() as conn:
        conn.execute("""INSERT INTO scanner_news_watchlist(ticker,company,enabled,created_at,updated_at)
            VALUES ('SYN','Synthetic Issuer',1,?,?)""", (stamp, stamp))
        conn.execute("""INSERT INTO si_universe_snapshots(id,observed_at,sources_json,members_json)
            VALUES ('synthetic',?,'[]',?)""",
            (stamp, '{"SYN":{"mapping":"verified","issuer_cik":"0000000010"}}'))
        conn.execute("""INSERT INTO si_filing_jobs(accession,issuer_cik,tickers_json,form,accepted_at,
            first_seen_at,source_url,primary_document,status,universe_snapshot_id)
            VALUES ('synthetic-report','0000000010','["SYN"]','10-Q',?,?,
                'https://example.invalid','synthetic.htm','processed','synthetic')""", (stamp, stamp))
        conn.execute("""INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,
            next_attempt_at,created_at,sent_at)
            VALUES ('sec-intelligence:synthetic-report','sec_intelligence','private-message','sent',?,?,?)""",
            (stamp, stamp, stamp))
        conn.commit()
    with get_db_connection() as conn:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        data = build(conn, now)
    assert data['earnings']['rows'] == [
        {'ticker': 'SYN', 'discovery_checked_at': None,
         'counts': {'discovered': 1, 'processed': 1, 'acknowledged': 1}},
    ]
    assert data['delivery']['rows'][0]['counts'] == {'queued_in_window': 1, 'acknowledged': 1}
    assert 'private-message' not in str(data)
