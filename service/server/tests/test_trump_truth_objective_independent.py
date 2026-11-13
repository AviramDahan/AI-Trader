"""Independent public-display controls; all posts, sends and databases synthetic."""
import copy
import importlib
import json
from unittest.mock import Mock

import pytest

import test_trump_truth_translation_independent as prepared

no_external_io = prepared.no_external_io
enabled = prepared.enabled
local_db = prepared.local_db
hebrew = prepared.hebrew
NOW = prepared.NOW
TEXT_HE = 'לא אאשר עלייה של 5% אלא אם הקונגרס יסכים.'


def sent_post(db, monkeypatch):
    import stock_scanner
    import trump_truth_translation as translation
    row = prepared.enqueue(db)
    assert translation.prepare(at=NOW, completion=prepared.good_completion(TEXT_HE))['prepared'] == 1
    sender = Mock(return_value='sent')
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert db.engine.process_telegram_outbox()['sent'] == 1 and sender.call_count == 1
    row = prepared.rows(db)[0]
    assert row['status'] == 'sent'
    return row


def report(db):
    public = importlib.import_module('trump_truth_public')
    with db.db.get_db_connection() as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        return public.report(conn, now=NOW, limit=20)


def test_public_report_displays_only_checked_hebrew_from_actual_sent_outbox(hebrew, monkeypatch):
    row = sent_post(hebrew, monkeypatch)
    result = report(hebrew)
    assert result['version'] == 1 and len(result['items']) == 1
    item = result['items'][0]
    assert item['text_he'] == TEXT_HE and item['translation_status'] == 'translated'
    assert item['truth_url'] == prepared.original.URL and item['source_verification'] == 'relay_only'
    assert item['original_published_at'] is None and item['delivery_status'] == 'sent'
    assert prepared.rows(hebrew)[0]['message'] == row['message']


def test_sent_archive_survives_live_source_off_and_new_activation_without_global_changes(hebrew, monkeypatch):
    sent_post(hebrew, monkeypatch)
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', '2026-10-23T15:00:00Z')
    monkeypatch.setenv('TELEGRAM_NEWS_NOT_BEFORE', '2026-10-23T15:00:00Z')
    assert len(report(hebrew)['items']) == 1
    assert hebrew.trump.enabled() is False
    assert hebrew.trump.activation() == '2026-10-23T15:00:00+00:00'


@pytest.mark.parametrize('status', ['trump_hebrew_pending', 'trump_hebrew_translating',
    'trump_hebrew_ready', 'trump_hebrew_sending', 'trump_hebrew_retry', 'failed', 'cancelled', 'disabled'])
def test_unsent_or_ambiguous_rows_never_appear_as_published(hebrew, monkeypatch, status):
    row = sent_post(hebrew, monkeypatch)
    with hebrew.db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET status=? WHERE id=?', (status, row['id']))
    assert report(hebrew)['items'] == []


def test_source_language_legacy_envelope_cannot_resurface_in_new_public_archive(hebrew, monkeypatch):
    row = sent_post(hebrew, monkeypatch)
    envelope = json.loads(row['message']); del envelope['presentation']
    with hebrew.db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET message=? WHERE id=?', (json.dumps(envelope), row['id']))
    assert report(hebrew)['items'] == []


@pytest.mark.parametrize('damage', ['missing', 'invalid_json', 'binding', 'working', 'invented_empty_body'])
def test_missing_or_bad_cache_is_truthfully_not_retained_not_a_fake_translation(hebrew, monkeypatch, damage):
    import trump_truth_translation as translation
    row = sent_post(hebrew, monkeypatch)
    with hebrew.db.get_db_connection() as conn:
        if damage == 'missing':
            conn.execute('DELETE FROM scanner_settings WHERE key=?', (translation.cache_key(row),))
        else:
            value = copy.deepcopy(prepared.cache(hebrew, row))
            if damage == 'binding': value['binding'] = '0' * 64
            if damage == 'working': value.update(status='working', text_he='')
            if damage == 'invented_empty_body':
                envelope = json.loads(row['message'])
                envelope['item'].update(text_excerpt='RT [קישור בגוף הפוסט — לצפייה במקור]', is_repost=True)
                value['binding'] = translation.binding(row, envelope)
                conn.execute('UPDATE scanner_telegram_outbox SET message=? WHERE id=?', (json.dumps(envelope), row['id']))
            encoded = '{' if damage == 'invalid_json' else json.dumps(value)
            conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?', (encoded, translation.cache_key(row)))
    if damage == 'invented_empty_body':
        assert report(hebrew)['items'] == []  # Shared rows are hidden, not relabelled originals.
        return
    item = report(hebrew)['items'][0]
    assert item['translation_status'] == 'not_retained' and item['text_he'] is None


@pytest.mark.parametrize('damage', ['future_sent', 'source_identity', 'foreign_url', 'dedupe'])
def test_public_source_and_clocks_fail_closed(hebrew, monkeypatch, damage):
    row = sent_post(hebrew, monkeypatch)
    envelope = json.loads(row['message'])
    with hebrew.db.get_db_connection() as conn:
        if damage == 'future_sent':
            conn.execute('UPDATE scanner_telegram_outbox SET sent_at=? WHERE id=?', ('2026-10-23T10:00:00Z', row['id']))
        elif damage == 'dedupe':
            conn.execute('UPDATE scanner_telegram_outbox SET dedupe_key=? WHERE id=?', ('stock:synthetic', row['id']))
        else:
            if damage == 'source_identity': envelope['item']['relay_channel_id'] += 1
            if damage == 'foreign_url': envelope['item']['truth_url'] = 'https://evil.invalid/post'
            conn.execute('UPDATE scanner_telegram_outbox SET message=? WHERE id=?', (json.dumps(envelope), row['id']))
    assert report(hebrew)['items'] == []


def test_public_projection_is_an_allowlist_not_raw_provenance_or_private_metadata(hebrew, monkeypatch):
    row = sent_post(hebrew, monkeypatch)
    before = report(hebrew)
    assert len(before['items']) == 1
    envelope = json.loads(row['message'])
    envelope['private_debug'] = {'token': 'SYNTHETIC_PRIVATE_SENTINEL', 'path': '/private/example'}
    with hebrew.db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET message=? WHERE id=?', (json.dumps(envelope), row['id']))
    result = report(hebrew)
    encoded = json.dumps([before, result], ensure_ascii=False)
    for forbidden in ('SYNTHETIC_PRIVATE_SENTINEL', 'private_debug', '/private/example',
                      '"fence"', '"activation"', '"binding"', '"attempts"', '"row_id"', '"config"'):
        assert forbidden not in encoded
    for item in result['items']:
        assert item['id'] != row['id'] and not isinstance(item['id'], int)
