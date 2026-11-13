"""Real schema7 transactions, synthetic public posts, no external calls."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

AT = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)


@pytest.fixture
def relay(pg, monkeypatch):
    import trump_truth_posts as t
    import scanner_engine as engine
    from database import get_db_connection
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (AT-timedelta(minutes=5)).isoformat())
    monkeypatch.setenv('TELEGRAM_MARKET_NEWS_THREAD_ID', '991')
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'true')
    with get_db_connection() as c:
        c.execute("UPDATE ne_control SET mode='canonical',not_before=?,epoch=1 WHERE id=1", ((AT-timedelta(hours=1)).isoformat(),))
    monkeypatch.setattr(engine, 'now_z', lambda: AT.isoformat())
    text = t.HEADER+'\nA non-economic personal greeting.\n'+t.LABEL
    url = 'https://truthsocial.com/@realDonaldTrump/117500000000000123'
    msg = NS(id=11, date=AT, message=text, action=None, peer_id=NS(channel_id=t.CHANNEL_ID),
             entities=[NS(offset=len(text[:text.rindex(t.LABEL)].encode('utf-16-le'))//2,
                          length=len(t.LABEL), url=url)])
    item, reason = t.extract(msg, AT)
    assert reason is None
    return t, item, get_db_connection


def test_concurrent_live_and_catchup_have_one_durable_original_post(relay):
    t, item, connect = relay
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: t.ingest([item], AT), range(3)))
    assert sum(r['inserted'] for r in results) == 1
    assert sum(r['duplicates'] for r in results) == 2
    with connect() as c:
        rows = c.execute('SELECT * FROM scanner_telegram_outbox').fetchall()
        assert len(rows) == 1 and rows[0]['status'] == 'trump_pending'
        for table in ('ne_events', 'ne_analysis', 'scanner_news', 'scanner_orders', 'scanner_trades'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n'] == 0
    assert t.delivery_message(dict(rows[0]), AT)


def test_postgres_claim_dispatch_and_new_states_are_restart_safe(relay, monkeypatch):
    import scanner_engine as engine
    import stock_scanner
    t, item, connect = relay
    t.ingest([item], AT)
    sender = Mock(side_effect=['connect_timeout', 'sent'])
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert engine.process_telegram_outbox()['failed'] == 1
    with connect() as c:
        row = dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        assert row['status'] == 'trump_retry'
        assert json.loads(row['message'])['item']['truth_post_id'] == item['truth_post_id']
        c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    assert engine.process_telegram_outbox()['sent'] == 1
    assert engine.process_telegram_outbox()['sent'] == 0
    assert sender.call_count == 2


def test_epoch_and_off_stop_pending_without_touching_other_roles(relay, monkeypatch):
    t, item, connect = relay
    t.ingest([item], AT)
    with connect() as c:
        row = dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        c.execute('UPDATE ne_control SET epoch=epoch+1 WHERE id=1')
    assert t.delivery_message(row, AT) is None
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    assert t.delivery_message(row, AT) is None
    with connect() as c:
        for table in ('scanner_orders', 'scanner_trades', 'scanner_fills', 'scanner_signals'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n'] == 0


def test_old_binary_queue_selector_ignores_all_new_states(relay):
    import scanner_engine as engine
    t, item, connect = relay
    t.ingest([item], AT)
    for status in ('trump_pending', 'trump_retry', 'trump_sending'):
        with connect() as c:
            c.execute('UPDATE scanner_telegram_outbox SET status=?', (status,))
            # Exact previous binary's due selector; no rewind, no deletion.
            assert not c.execute("SELECT id FROM scanner_telegram_outbox WHERE status IN ('pending','retry','community_pending') AND next_attempt_at<=? ORDER BY id LIMIT 20", (AT.isoformat(),)).fetchall()
    with connect() as c:
        c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    assert engine._claim_telegram_outbox() == []
    with connect() as c:
        row = c.execute('SELECT * FROM scanner_telegram_outbox').fetchone()
        assert row['status'] == 'failed' and 'unknown' in row['last_error']
