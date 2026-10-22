"""Real test_* PG transactions; synthetic bilingual source/model/Bot ACKs only."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import test_trump_truth_bilingual_independent as independent
import test_trump_truth_media as media_owner

media = media_owner.media


@pytest.fixture
def setup(pg, media, monkeypatch):
    import database
    import scanner_engine
    import stock_scanner
    import trump_truth_bilingual as bilingual
    for key, value in {
        'TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED': 'true',
        'TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED': 'true',
        'TELEGRAM_MARKET_NEWS_THREAD_ID': '991',
        'TELEGRAM_BOT_TOKEN': 'synthetic-only', 'TELEGRAM_CHAT_ID': '-1001',
        'NEWS_EVENTS_RUNTIME': 'false',
    }.items(): monkeypatch.setenv(key, value)
    monkeypatch.setattr(scanner_engine, 'now_z', lambda: media_owner.AT.isoformat())
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(bilingual, '_now', lambda: media_owner.AT)
    row, original, approved = independent.ready(database, media, bilingual, asset=False)
    return database, bilingual, row, original, approved


def archive(database):
    import trump_truth_public
    with database.get_db_connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        conn.execute("SET LOCAL statement_timeout='5s'")
        conn.execute("SET LOCAL lock_timeout='2s'")
        assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        return trump_truth_public.report(conn, now=media_owner.AT)


def test_real_pg_bilingual_claim_is_exclusive_and_has_actual_durable_deadline(setup):
    import scanner_engine
    database, bilingual, row, _, _ = setup
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: scanner_engine._claim_telegram_outbox(), range(3)))
    claimed = [item for group in results for item in group]
    assert len(claimed) == 1 and claimed[0]['id'] == row['id']
    assert claimed[0]['status'] == bilingual.SENDING
    with database.get_db_connection() as conn:
        actual = conn.execute('SELECT status,next_attempt_at FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone()
        assert actual['status'] == bilingual.SENDING and actual['next_attempt_at'] == claimed[0]['next_attempt_at']


def test_real_pg_two_complete_languages_persist_and_archive_survives_live_switch_off(setup, media, monkeypatch):
    import scanner_engine
    database, bilingual, row, original, approved = setup
    sender = Mock(side_effect=[{'message_id': 100}, {'message_id': 101}]); monkeypatch.setattr(media[0], '_send', sender)
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    value = bilingual.receipt(row)
    assert value['status'] == 'complete' and set(value['acks']) == {'hebrew', 'english'}
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', '2026-10-23T15:00:00Z')
    result = archive(database)
    assert len(result['items']) == 1
    assert result['items'][0]['source_excerpt'] == original and result['items'][0]['text_he'] == approved
    assert sender.call_count == 2
    with database.get_db_connection() as conn:
        for table in ('scanner_orders', 'scanner_trades', 'scanner_signals', 'scanner_fills', 'scanner_news'):
            assert conn.execute('SELECT count(*) n FROM '+table).fetchone()['n'] == 0


def test_real_pg_forged_sent_status_with_only_partial_language_ack_is_not_public(setup, media, monkeypatch):
    import scanner_engine
    database, bilingual, row, _, _ = setup
    sender = Mock(side_effect=[{'message_id': 100}, {'retry': True, 'reason': 'rate_limited'}]); monkeypatch.setattr(media[0], '_send', sender)
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    assert set(bilingual.receipt(row)['acks']) == {'hebrew'}
    with database.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET status=?,sent_at=? WHERE id=?', ('sent', media_owner.AT.isoformat(), row['id']))
    assert archive(database)['items'] == []
    assert sender.call_count == 2


def test_real_pg_changed_valid_unsent_hebrew_is_not_misrepresented_and_cache_loss_is_unknown(setup, media, monkeypatch):
    import scanner_engine
    import trump_truth_translation as translation
    database, bilingual, row, original, _ = setup
    monkeypatch.setattr(media[0], '_send', Mock(side_effect=[{'message_id': 100}, {'message_id': 101}]))
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    with database.get_db_connection() as conn:
        stored = conn.execute('SELECT value_json FROM scanner_settings WHERE key=?', (translation.cache_key(row),)).fetchone()
        value = copy.deepcopy(json.loads(stored['value_json']))
        value['text_he'] = 'ב'*2300 + ' לא להסכים ללא התנאי האחרון.'
        conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?', (json.dumps(value), translation.cache_key(row)))
    assert archive(database)['items'] == []
    with database.get_db_connection() as conn:
        conn.execute('DELETE FROM scanner_settings WHERE key=?', (translation.cache_key(row),))
    item = archive(database)['items'][0]
    assert item['translation_status'] == 'not_retained' and item['text_he'] is None and item['source_excerpt'] == original
