"""Candidate-scoped evidence selection, using only synthetic stored observations."""
import json
from pathlib import Path

import pytest

from test_signal_inputs import NOW, canonical_fixture
import database
import signal_news


CANDIDATE = dict(ticker='TEST', company='Synthetic Corporation')


def insert_event(conn, identifier, body=None, updated_at=None, status='analyzed', reason='low_importance'):
    row = canonical_fixture()
    conn.execute('''INSERT INTO ne_events
        (event_id,body_json,evidence_version,status,reason,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?)''', (identifier, body if body is not None else row['body_json'],
        row['evidence_version'], status, reason, row['created_at'], updated_at or row['updated_at']))


def seed_crowded_snapshot(conn):
    insert_event(conn, 'company-story')
    market = json.loads(canonical_fixture()['body_json'])
    market.update(tickers=[], company_identity=[], event_type='market')
    for index in range(1001):
        insert_event(conn, f'market-{index:04d}', json.dumps(market), '2026-10-05T19:00:00+00:00')
    conn.commit()


@pytest.fixture
def isolated_news_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path/'news.db'))
    with database.get_db_connection() as conn:
        conn.executescript((Path(signal_news.__file__).parent/'news_events/schema.sql').read_text())


def test_newer_market_events_do_not_starve_fresh_company_evidence(isolated_news_db):
    with database.get_db_connection() as conn:
        seed_crowded_snapshot(conn)
    rows = signal_news.existing_news([CANDIDATE], 72, NOW)['TEST']
    assert [row['canonical_event_id'] for row in rows] == ['company-story']
    with database.get_db_connection() as conn:
        assert conn.execute('SELECT count(*) FROM ne_events').fetchone()[0] == 1002
        assert conn.execute('SELECT count(*) FROM ne_analysis').fetchone()[0] == 0


def test_exact_ticker_membership_and_malformed_events_are_isolated(isolated_news_db):
    with database.get_db_connection() as conn:
        insert_event(conn, 'company-story')
        for index, tickers in enumerate((['TESTING'], 'TEST', {'symbol':'TEST'}, None)):
            body = json.loads(canonical_fixture()['body_json'])
            body['tickers'] = tickers
            insert_event(conn, f'wrong-shape-{index}', json.dumps(body), '2026-10-05T19:00:00+00:00')
        insert_event(conn, 'malformed', '{not-json', '2026-10-05T19:00:00+00:00')
        conn.commit()
    assert [row['canonical_event_id'] for row in signal_news.existing_news([CANDIDATE], 72, NOW)['TEST']] == ['company-story']


@pytest.mark.parametrize('status,reason', [
    ('quality_failed', 'news_quality_rejected:passes_quality_gate'),
    ('quality_failed', 'invalid_json'),
    ('blocked', 'license_required'), ('blocked', 'source_conflict'),
    ('blocked', 'backlog_blocked'), ('blocked', 'identity_unverified'),
])
def test_retrieval_fix_does_not_bypass_quality_or_protected_blocks(isolated_news_db, status, reason):
    with database.get_db_connection() as conn:
        insert_event(conn, 'blocked-story', status=status, reason=reason)
        conn.commit()
    assert signal_news.existing_news([CANDIDATE], 72, NOW) == {'TEST': []}


def test_cap_applies_per_candidate_not_other_companies(isolated_news_db, monkeypatch, caplog):
    monkeypatch.setattr(signal_news, 'MAX_EVENTS', 2)
    with database.get_db_connection() as conn:
        insert_event(conn, 'company-story')
        other = json.loads(canonical_fixture()['body_json'])
        other['tickers'] = ['OTHER']
        for index in range(3):
            insert_event(conn, f'other-{index}', json.dumps(other), '2026-10-05T19:00:00+00:00')
        conn.commit()
    result = signal_news.existing_news([CANDIDATE, dict(ticker='OTHER', company='Other Corporation')], 72, NOW)
    assert result['TEST'][0]['canonical_event_id'] == 'company-story'
    assert result['OTHER'] == []  # Metadata does not bypass company identity.
    assert 'signal_news_snapshot_clipped:OTHER:2' in caplog.text


def test_empty_candidates_need_no_database_connection(monkeypatch):
    def forbidden():
        pytest.fail('No evidence query should run without candidates')
    monkeypatch.setattr(database, 'get_db_connection', forbidden)
    assert signal_news.existing_news([], 72, NOW) == {}
