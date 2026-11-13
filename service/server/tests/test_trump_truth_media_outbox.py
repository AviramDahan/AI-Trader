"""Actual shared claim/dispatch integration, synthetic isolated DB and senders."""
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

AT = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import database, scanner_engine, stock_scanner
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path / 'media-outbox.sqlite'))
    database.init_database()
    monkeypatch.setattr(scanner_engine, 'now_z', lambda: AT.isoformat())
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'false')
    return database


def insert(db, state, event='trump_truth_post', due=None):
    raw = json.dumps({'version': 'synthetic-original-envelope', 'do_not_render': True})
    with db.get_db_connection() as c:
        c.execute('INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at) VALUES(?,?,?,?,?,?,?)',
                  ('synthetic:' + state, event, raw, state, 0,
                   due or AT.isoformat(), AT.isoformat()))
        return dict(c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id DESC LIMIT 1').fetchone())


def current(db, row):
    with db.get_db_connection() as c:
        return dict(c.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone())


@pytest.mark.parametrize('state', ['trump_media_ready', 'trump_media_retry'])
def test_media_ready_is_exclusively_claimed_as_media_sending(db, state):
    import scanner_engine as e
    r = insert(db, state)
    claimed = e._claim_telegram_outbox()
    assert len(claimed) == 1 and claimed[0]['id'] == r['id']
    assert claimed[0]['status'] == 'trump_media_sending'
    assert current(db, r)['status'] == 'trump_media_sending'
    assert claimed[0]['next_attempt_at'] == current(db, r)['next_attempt_at']
    assert claimed[0]['next_attempt_at'] != r['next_attempt_at']
    assert e._claim_telegram_outbox() == []


@pytest.mark.parametrize('state', ['trump_media_pending', 'trump_media_preparing'])
def test_unprepared_media_never_claimed(db, state):
    import scanner_engine as e
    r = insert(db, state)
    assert e._claim_telegram_outbox() == []
    assert current(db, r)['status'] == state


def test_expired_media_send_never_replayed_after_restart(db):
    import scanner_engine as e
    r = insert(db, 'trump_media_sending', due='2000-01-01T00:00:00Z')
    assert e._claim_telegram_outbox() == []
    result = current(db, r)
    assert result['status'] == 'failed'
    assert result['last_error'] == 'trump_truth_delivery_unknown_manual_review'
    assert e._claim_telegram_outbox() == []


@pytest.mark.parametrize(('result', 'state'), [
    ('sent', 'sent'), ('missing_credentials', 'disabled'),
    ('{"terminal":true,"reason":"unknown"}', 'failed'),
    ('{"terminal":false,"retry_after":60}', 'trump_media_retry'),
])
def test_actual_outbox_dispatch_retains_original_json_and_media_state(db, monkeypatch, result, state):
    import scanner_engine as e, stock_scanner, trump_truth_posts as t, trump_truth_media as m
    r = insert(db, 'trump_media_ready')
    dispatch = Mock(return_value=result)
    monkeypatch.setattr(m, 'dispatch', dispatch)
    monkeypatch.setattr(t, 'delivery_message', lambda *a, **k: pytest.fail('media row rendered in generic branch'))
    monkeypatch.setattr(stock_scanner, 'send_telegram', lambda *a, **k: pytest.fail('media envelope sent as plain text'))
    e.process_telegram_outbox()
    assert dispatch.call_count == 1
    assert dispatch.call_args.args[0]['message'] == r['message']
    assert dispatch.call_args.args[0]['status'] == 'trump_media_sending'
    actual = current(db, r)
    assert actual['message'] == r['message'] and actual['status'] == state
    if state != 'trump_media_retry':
        e.process_telegram_outbox()
        assert dispatch.call_count == 1


def test_global_telegram_off_cancels_media_without_remote_call(db, monkeypatch):
    import scanner_engine as e, stock_scanner, trump_truth_media as m
    r = insert(db, 'trump_media_ready')
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': False})
    monkeypatch.setattr(m, 'dispatch', lambda *a: pytest.fail('disabled remote dispatch'))
    e.process_telegram_outbox()
    assert current(db, r)['status'] == 'disabled'


def test_foreign_event_cannot_enter_media_ready_queue(db):
    import scanner_engine as e
    r = insert(db, 'trump_media_ready', event='news')
    assert e._claim_telegram_outbox() == []
    assert current(db, r)['status'] == 'trump_media_ready'
