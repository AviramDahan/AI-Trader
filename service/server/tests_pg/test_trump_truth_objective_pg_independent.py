"""Real isolated PostgreSQL claim/archive proof; synthetic assets/AI/Bot ACKs."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import test_trump_truth_media as owner

media = owner.media


@pytest.fixture
def setup(pg, media, monkeypatch):
    import database
    import scanner_engine
    import stock_scanner
    for key, value in {
        'TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED': 'true',
        'TELEGRAM_MARKET_NEWS_THREAD_ID': '991', 'TELEGRAM_BOT_TOKEN': 'synthetic-only',
        'TELEGRAM_CHAT_ID': '-1001', 'NEWS_EVENTS_RUNTIME': 'false',
    }.items(): monkeypatch.setenv(key, value)
    monkeypatch.setattr(scanner_engine, 'now_z', lambda: owner.AT.isoformat())
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    row = owner.claimed(database, media, long=True)
    with database.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=? WHERE id=?', (media[0].READY, owner.AT.isoformat(), row['id']))
    return database, row


def readonly(connect):
    conn = connect()
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    conn.execute("SET LOCAL statement_timeout='5s'")
    conn.execute("SET LOCAL lock_timeout='2s'")
    return conn


def test_real_pg_concurrent_media_claim_is_one_lease_with_durable_sending_state(setup, media):
    import scanner_engine
    database, row = setup
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: scanner_engine._claim_telegram_outbox(), range(3)))
    claimed = [item for group in results for item in group]
    assert len(claimed) == 1 and claimed[0]['id'] == row['id']
    assert claimed[0]['status'] == media[0].SENDING
    with database.get_db_connection() as conn:
        assert conn.execute('SELECT status FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone()['status'] == media[0].SENDING


def test_real_pg_actual_media_send_then_historic_archive_survives_off(setup, media, monkeypatch):
    import scanner_engine
    import stock_scanner
    import trump_truth_public
    import trump_truth_translation
    database, row = setup; module = media[0]
    sender = Mock(side_effect=[{'message_id': 123}, {'message_id': 124}]); monkeypatch.setattr(module, '_send', sender)
    never = Mock(side_effect=AssertionError('No generic send or inference in media/public path'))
    monkeypatch.setattr(stock_scanner, 'send_telegram', never)
    monkeypatch.setattr(trump_truth_translation, 'local_json', never)
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert module._receipt(row)['status'] == 'complete'
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', '2026-10-23T15:00:00Z')
    conn = readonly(database.get_db_connection)
    try:
        result = trump_truth_public.report(conn, now=owner.AT)
        assert len(result['items']) == 1 and result['items'][0]['translation_status'] == 'translated'
        assert result['items'][0]['media']['status'] == 'available'
        digest = json.loads(row['message'])['item']['media']['sha256']
        expected = hashlib.sha256(json.dumps({'binding': module._receipt(row, conn)['binding'],
            'asset_sha256': digest}, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        assert result['items'][0]['media']['asset_token'] == expected and expected != digest
        assert module.public_asset(expected, conn, owner.AT) == (b'\xff\xd8\xff\xd9', 'image/jpeg')
    finally: conn.close()
    never.assert_not_called()
    assert sender.call_count == 2


def test_real_pg_failed_text_ack_is_not_published_or_retried(setup, media, monkeypatch):
    import scanner_engine
    import trump_truth_public
    database, row = setup; module = media[0]
    sender = Mock(side_effect=[{'message_id': 123}, {'unknown': True}]); monkeypatch.setattr(module, '_send', sender)
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert sender.call_count == 2
    conn = readonly(database.get_db_connection)
    try: assert trump_truth_public.report(conn, now=owner.AT)['items'] == []
    finally: conn.close()


def test_real_pg_cache_loss_is_unknown_and_no_financial_mutations(setup, media, monkeypatch):
    import scanner_engine
    import trump_truth_public
    import trump_truth_translation as h
    database, row = setup; module = media[0]
    monkeypatch.setattr(module, '_send', Mock(side_effect=[{'message_id': 123}, {'message_id': 124}]))
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    with database.get_db_connection() as conn:
        conn.execute('DELETE FROM scanner_settings WHERE key=?', (h.cache_key(row),))
    conn = readonly(database.get_db_connection)
    try:
        item = trump_truth_public.report(conn, now=owner.AT)['items'][0]
        assert item['translation_status'] == 'not_retained' and item['text_he'] is None
        assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        for table in ('scanner_orders', 'scanner_trades', 'scanner_signals', 'scanner_fills', 'scanner_news'):
            assert conn.execute('SELECT count(*) n FROM '+table).fetchone()['n'] == 0
    finally: conn.close()
