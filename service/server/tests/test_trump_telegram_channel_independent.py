"""Independent synthetic source-switch controls; never contact Telegram or AI."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

import telegram_news_reader as reader
import trump_truth_posts as posts


AT = datetime(2026, 10, 25, 17, tzinfo=timezone.utc)
CHANNEL = 'real_donaldjtrump'
CHANNEL_ID = 1462338131
OLD_CHANNEL = 'realdonaldtrump_truth'
OLD_CHANNEL_ID = 2310477090
SOURCE = 'We support peace and will not raise tariffs by 5%.'


@pytest.fixture(autouse=True)
def selected_channel(monkeypatch):
    for key, value in {
        'TELEGRAM_TRUMP_SOURCE': 'telegram_channel_v1',
        'TELEGRAM_TRUMP_TRUTH_ENABLED': 'false',
        'TELEGRAM_TRUMP_CHANNEL_ENABLED': 'true',
        'TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED': 'true',
        'TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED': 'true',
        'TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED': 'false',
        'TELEGRAM_TRUMP_TRUTH_NOT_BEFORE': (AT-timedelta(minutes=5)).isoformat(),
        'TELEGRAM_NEWS_READER_ENABLED': 'true',
        'TELEGRAM_NEWS_SOURCE_CHANNELS': 'financialjuice',
        'TELEGRAM_MARKET_NEWS_THREAD_ID': '991',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('TELEGRAM_NEWS_NOT_BEFORE', raising=False)
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request',
                        lambda *a, **k: pytest.fail('Unexpected HTTP call'))


def message(text=SOURCE, number=19, channel_id=CHANNEL_ID, **kw):
    fields = dict(id=number, date=AT, message=text, action=None,
                  peer_id=NS(channel_id=channel_id), entities=[],
                  photo=None, document=None, fwd_from=None, forward=None,
                  reply_to=None, reply_to_msg_id=None)
    fields.update(kw)
    return NS(**fields)


def old_message():
    body = posts.HEADER+'\n'+SOURCE+'\n'+posts.LABEL
    start = len(body[:body.rindex(posts.LABEL)].encode('utf-16-le'))//2
    return message(body, channel_id=OLD_CHANNEL_ID, entities=[
        NS(offset=start, length=len(posts.LABEL),
           url='https://truthsocial.com/@realDonaldTrump/117500000000000777')])


def test_selected_new_source_replaces_old_reader_allowlist():
    assert reader.channel_names() == ['financialjuice', CHANNEL]


def test_new_message_is_dedicated_channel_item_not_generic_market_news():
    item = reader.message_item(message(), CHANNEL, AT)
    assert item is not None
    assert item['source_kind'] == 'trump_telegram_channel_v1'
    assert item['truth_post_id'] == 'tg:1462338131:19'
    assert item['truth_url'] == 'https://t.me/real_DonaldJTrump/19'
    assert item['source_verification'] == 'channel_only'
    assert item['original_published_at'] is None


def test_wrong_channel_id_cannot_fall_through_to_generic_reader():
    assert reader.message_item(message(channel_id=CHANNEL_ID+1), CHANNEL, AT) is None


def test_old_relay_cannot_extract_active_items_after_source_switch():
    assert posts.extract(old_message(), AT)[0] is None


def extracted(msg=None, at=AT):
    value, reason = posts.extract(msg or message(), at)
    assert reason is None and value is not None
    return value


@pytest.mark.parametrize('setting', ['unknown', 'disabled', 'hebrew_off', 'both_sources'])
def test_bad_selector_or_flag_never_leaks_either_pinned_identity_to_generic(monkeypatch, setting):
    if setting == 'unknown': monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE', 'telegram_channel_typo')
    if setting == 'disabled': monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'false')
    if setting == 'hebrew_off': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
    if setting == 'both_sources': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_NEWS_SOURCE_CHANNELS', f'financialjuice,{CHANNEL},{OLD_CHANNEL}')
    assert reader.channel_names() == ['financialjuice']
    for username, channel_id in [(CHANNEL, CHANNEL_ID), (OLD_CHANNEL, OLD_CHANNEL_ID),
                                  ('financialjuice', CHANNEL_ID), ('financialjuice', OLD_CHANNEL_ID)]:
        assert reader.message_item(message(channel_id=channel_id), username, AT) is None


@pytest.mark.parametrize('bad', ['fwd_from', 'forward', 'reply_to', 'reply_to_msg_id', 'action'])
def test_forward_reply_or_service_message_never_qualifies(bad):
    assert posts.extract(message(**{bad: NS()}), AT)[0] is None


@pytest.mark.parametrize('text', [
    'RT: someone else', 'ReTruth @other', 'A quote: @other',
    'R\u200bT: hidden marker', 'ＲＴ： another account',
    'Original text https://truthsocial.com/@another/117500000000000777',
    ('ordinary words '*120)+' RT: trailing after the old excerpt limit',
])
def test_full_raw_shared_markers_are_rejected_before_cleaning(text):
    assert posts.extract(message(text), AT)[0] is None


def test_hidden_entity_truth_link_cannot_be_cleaned_into_an_original():
    entity = NS(offset=0, length=2, url='https://truthsocial.com/@other/117500000000000777')
    assert posts.extract(message(entities=[entity]), AT)[0] is None


@pytest.mark.parametrize('bad', [True, 0, -1, 2147483648, '19'])
def test_typed_message_identity_is_bounded(bad):
    assert posts.extract(message(number=bad), AT)[0] is None


@pytest.mark.parametrize('bad', [AT+timedelta(seconds=1), AT-timedelta(minutes=6), AT.replace(tzinfo=None)])
def test_future_pre_activation_or_naive_source_time_rejected(bad):
    assert posts.extract(message(date=bad), AT)[0] is None


def test_long_supported_source_retained_whole_and_over_limit_fails_closed():
    body = ('peace '*290).strip()
    assert 1600 < len(body) < 2400
    assert extracted(message(body))['text_excerpt'] == body
    assert posts.extract(message('X'*2401), AT)[0] is None
    assert posts.extract(message('😀'*1201), AT)[0] is None


def test_url_expansion_cannot_silently_clip_retained_last_clause():
    body = 'A'*2360+' https://x.co FINAL_CLAUSE'
    assert len(body.encode('utf-16-le'))//2 <= 2400
    item, reason = posts.extract(message(body), AT)
    assert item is None or item['text_excerpt'].endswith('FINAL_CLAUSE')


@pytest.mark.parametrize(('key', 'value'), [
    ('truth_post_id', 'tg:1462338131:20'),
    ('truth_url', 'https://t.me/real_DonaldJTrump/20'),
    ('truth_url', 'https://t.me/real_DonaldJTrump/19?other=1'),
    ('truth_url', 'https://truthsocial.com/@realDonaldTrump/117500000000000777'),
    ('relay_channel_id', '1462338131'), ('relay_message_id', True),
    ('source_verification', 'primary_verified'), ('original_published_at', AT.isoformat()),
    ('publication_policy', 'original_relay_v1'), ('is_repost', True),
])
def test_retained_identity_or_provenance_tamper_rejected(key, value):
    item = extracted(); item[key] = value
    assert not posts.valid_item(item, AT)


def test_historical_new_item_does_not_gain_live_authority_from_disabled_flags(monkeypatch):
    item = extracted()
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE', 'unknown')
    monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
    assert not posts.valid_item(item, AT)
    assert posts.valid_item(item, AT+timedelta(days=2), active=False)


def test_bootstrap_cursor_fences_new_channel_without_replaying_old_cursor():
    fake = NS(get_entity=AsyncMock(return_value=NS(id=CHANNEL_ID, username=CHANNEL, broadcast=True)),
              get_messages=AsyncMock(return_value=[message(number=19)]))
    old = {'checkpoint_json': json.dumps({'channels': {OLD_CHANNEL: {'last_id': 9999}}})}
    first = asyncio.run(reader.collect(fake, old, AT, [CHANNEL]))
    assert first['items'] == []
    assert fake.get_messages.call_args.kwargs == {'limit': 1}
    checkpoint = first['checkpoint']['channels'][CHANNEL]
    assert checkpoint['last_id'] == 19
    fake.get_messages.return_value = [message(number=20)]
    second = asyncio.run(reader.collect(fake, {'checkpoint_json': json.dumps(first['checkpoint'])}, AT, [CHANNEL]))
    assert fake.get_messages.call_args.kwargs == {'limit': 50, 'min_id': 19, 'reverse': True}
    assert len(second['items']) == 1
    assert second['items'][0]['truth_post_id'] == 'tg:1462338131:20'


@pytest.fixture
def db(tmp_path, monkeypatch):
    import database, scanner_engine, stock_scanner
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path/'new-channel.sqlite'))
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'false')
    database.init_database()
    monkeypatch.setattr(scanner_engine, 'now_z', lambda: AT.isoformat())
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    return database


def rows(db):
    with db.get_db_connection() as c:
        return [dict(value) for value in c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id')]


def approved(system, payload, schema):
    return ({'text_he': 'אנו תומכים בשלום ולא נעלה את המכסים ב־5%.'}
            if 'text_he' in schema['properties'] else
            {'faithful': True, 'fluent_hebrew': True, 'complete': True, 'unsupported_claims': False})


def test_ingest_is_message_idempotent_and_forces_hebrew_despite_old_bilingual_flag(db):
    first = extracted()
    assert posts.ingest([first], AT)['inserted'] == 1
    assert posts.ingest([first], AT)['duplicates'] == 1
    assert posts.ingest([extracted(message(number=20))], AT)['inserted'] == 1
    saved = rows(db)
    assert len(saved) == 2 and saved[0]['dedupe_key'] != saved[1]['dedupe_key']
    assert all(json.loads(row['message'])['presentation'] == 'hebrew_v1' for row in saved)
    assert all(row['status'] == 'trump_hebrew_pending' for row in saved)


def test_pipeline_special_partition_never_creates_scanner_or_canonical_news(db, monkeypatch):
    import news_pipeline
    from news_events import runtime
    monkeypatch.setattr(runtime, 'ingest_items', lambda *a, **k: pytest.fail('Generic canonical leak'))
    assert news_pipeline.ingest_items([extracted()], AT)['inserted'] == 1
    with db.get_db_connection() as c:
        for table in ('scanner_news', 'scanner_signals', 'scanner_orders', 'scanner_trades', 'scanner_fills'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n'] == 0


def test_capacity_unavailability_does_not_spend_generation_attempt(db, monkeypatch):
    import ai_routing, trump_truth_translation as h
    posts.ingest([extracted()], AT)
    monkeypatch.setattr(ai_routing, 'enabled', lambda: True)
    monkeypatch.setattr(ai_routing, 'ready', lambda: False)
    monkeypatch.setattr(h, 'local_json', lambda *a: pytest.fail('Busy model must not run'))
    assert h.prepare(at=AT) == {'prepared': 0, 'deferred': 1}
    saved = rows(db)[0]
    assert saved['status'] == h.PENDING
    with db.get_db_connection() as c:
        assert c.execute('SELECT value_json FROM scanner_settings WHERE key=?', (h.cache_key(saved),)).fetchone() is None
    assert posts.delivery_message(saved, AT) is None


def test_two_failed_generations_cancel_without_source_fallback_or_send(db, monkeypatch):
    import scanner_engine, stock_scanner, trump_truth_translation as h
    posts.ingest([extracted()], AT)
    completion = Mock(side_effect=ValueError('private model content must not leak'))
    assert h.prepare(at=AT, completion=completion)['deferred'] == 1
    h.prepare(at=AT+timedelta(seconds=61), completion=completion)
    saved = rows(db)[0]
    assert completion.call_count == 2 and saved['status'] == 'cancelled'
    assert posts.delivery_message(saved, AT+timedelta(seconds=62)) is None
    sender = Mock(); monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    sender.assert_not_called()
    assert 'private model' not in (saved['last_error'] or '')


def test_success_retry_and_restart_reuse_only_complete_hebrew(db, monkeypatch):
    import scanner_engine, stock_scanner, trump_truth_translation as h
    from telegram_presentation import telegram_text, utf16_length
    posts.ingest([extracted()], AT)
    completion = Mock(side_effect=approved)
    prepared = h.prepare(at=AT, completion=completion)
    assert prepared['prepared'] == 1, (prepared, completion.call_count, rows(db)[0]['last_error'])
    saved = rows(db)[0]; envelope = saved['message']
    text = posts.delivery_message(saved, AT)
    assert SOURCE not in text and 'Truth Social' not in text
    assert 'אנו תומכים' in text and 'https://t.me/real_DonaldJTrump/19' not in text
    assert utf16_length(telegram_text(text, limit=16384)) <= 4096
    sender = Mock(side_effect=['connect_timeout', 'sent'])
    monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    monkeypatch.setattr(h, 'local_json', lambda *a: pytest.fail('No inference during send or retry'))
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    with db.get_db_connection() as c:
        c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert completion.call_count == 2 and sender.call_count == 2
    assert rows(db)[0]['message'] == envelope


def test_source_revocation_between_translation_and_editor_is_not_published(db, monkeypatch):
    import trump_truth_translation as h
    posts.ingest([extracted()], AT)
    calls = []
    def callback(system, payload, schema):
        calls.append(payload)
        monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'false')
        return {'text_he': 'אנו תומכים בשלום ולא נעלה את המכסים ב־5%.'}
    assert h.prepare(at=AT, completion=callback)['prepared'] == 0
    assert len(calls) == 1 and rows(db)[0]['status'] == 'cancelled'
    assert posts.delivery_message(rows(db)[0], AT) is None


def test_old_queued_source_is_cancelled_without_model_or_replay_after_switch(db, monkeypatch):
    import trump_truth_translation as h
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE', 'truth_relay_v1')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED', 'false')
    old, reason = posts.extract(old_message(), AT)
    assert old is not None and reason is None
    assert posts.ingest([old], AT)['inserted'] == 1
    immutable = rows(db)[0]['message']
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE', 'telegram_channel_v1')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'true')
    completion = Mock(side_effect=AssertionError('No old-source inference'))
    assert h.prepare(at=AT, completion=completion)['prepared'] == 0
    completion.assert_not_called()
    saved = rows(db)[0]
    assert saved['status'] == 'cancelled' and saved['message'] == immutable
    assert posts.delivery_message(saved, AT) is None
    assert posts.valid_item(old, AT, active=False)


def test_utf16_bidi_expansion_blocks_rather_than_clips_accepted_hebrew(db, monkeypatch):
    import scanner_engine, stock_scanner, trump_truth_translation as h
    posts.ingest([extracted(message('1 '*800))], AT)
    hebrew = ('א1 '*800).strip()
    def callback(system, payload, schema):
        return {'text_he': hebrew} if 'text_he' in schema['properties'] else approved(system, payload, schema)
    assert h.prepare(at=AT, completion=callback)['prepared'] == 1
    assert posts.delivery_message(rows(db)[0], AT) is None
    sender = Mock(); monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    sender.assert_not_called()


def test_actual_sender_keeps_hebrew_without_source_url_and_news_destination(db, monkeypatch):
    import re
    import scanner_engine, stock_scanner, trump_truth_translation as h
    from telegram_presentation import telegram_text, utf16_length
    posts.ingest([extracted()], AT)
    assert h.prepare(at=AT, completion=approved)['prepared'] == 1
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-unit-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100123')
    monkeypatch.setenv('TELEGRAM_TRADING_THREAD_ID', '777')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_URL', 'https://t.me/'+'a'*490)
    session = Mock()
    session.post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 42}}
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    fields = session.post.call_args.kwargs['data']; wire = fields['text']
    visible = re.sub('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', wire)
    assert fields['message_thread_id'] == 991 and 'parse_mode' not in fields
    assert approved('', {}, h.SCHEMA)['text_he'] in visible
    assert SOURCE not in visible and 'Truth Social' not in visible
    assert 'https://t.me/real_DonaldJTrump/19' not in visible and 'מקור:' not in visible
    assert utf16_length(wire) <= 4096 and telegram_text(wire) == wire


def captured_item(monkeypatch, tmp_path, text=SOURCE):
    import trump_truth_media as media
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED', 'true')
    monkeypatch.setattr(media, 'CACHE', tmp_path/'assets')
    monkeypatch.setattr(media, '_now', lambda: AT)
    monkeypatch.setattr(media, '_budget_state', {'minute': None, 'count': 0, 'bytes': 0})
    classes = {name: type(name, (), {}) for name in
               ('MessageMediaPhoto', 'Photo', 'MessageMediaDocument', 'Document', 'DocumentAttributeVideo')}
    monkeypatch.setattr(media, '_types', lambda: NS(**classes))
    photo = classes['Photo'](); photo.id = 7; photo.sizes = [NS(size=4)]
    attached = classes['MessageMediaPhoto'](); attached.photo = photo
    msg = message(text, media=attached, photo=photo)
    session = tmp_path/'reader.session'; session.touch(); session.chmod(0o600)
    async def download(msg, file):
        file.write(b'\xff\xd8\xff\xd9')
    client = NS(download_media=AsyncMock(side_effect=download))
    item = asyncio.run(media.capture(client, msg, extracted(msg), AT, session_path=session))
    assert client.download_media.call_count == 1
    assert item['media']['status'] == 'available' and posts.valid_item(item, AT)
    return media, item


def test_untranslated_nonempty_media_is_cancelled_without_any_remote_stage(db, monkeypatch, tmp_path):
    import trump_truth_translation as h
    media, item = captured_item(monkeypatch, tmp_path)
    assert posts.ingest([item], AT)['inserted'] == 1
    failure = Mock(side_effect=ValueError('No valid translation'))
    h.prepare(at=AT, completion=failure)
    h.prepare(at=AT+timedelta(seconds=61), completion=failure)
    saved = rows(db)[0]
    assert saved['status'] == 'cancelled'
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100123')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-unit-token')
    send = Mock(); monkeypatch.setattr(media, '_send', send)
    assert json.loads(media.dispatch(saved, {'telegram_enabled': True}, AT))['terminal'] is True
    send.assert_not_called()


def test_genuine_empty_media_uses_hebrew_caption_without_model(db, monkeypatch, tmp_path):
    import scanner_engine, trump_truth_translation as h
    media, item = captured_item(monkeypatch, tmp_path, text='')
    assert posts.ingest([item], AT)['inserted'] == 1
    no_model = Mock(side_effect=AssertionError('No invented media caption'))
    assert h.prepare(at=AT, completion=no_model)['prepared'] == 1
    no_model.assert_not_called()
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100123')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-unit-token')
    send = Mock(return_value={'message_id': 51}); monkeypatch.setattr(media, '_send', send)
    claimed = scanner_engine._claim_telegram_outbox()
    assert len(claimed) == 1
    assert media.dispatch(claimed[0], {'telegram_enabled': True}, AT) == 'sent'
    assert send.call_count == 1 and send.call_args.args[0] == 'sendPhoto'
    caption = send.call_args.args[1]['caption']
    assert 'ללא טקסט' in caption and SOURCE not in caption


def test_media_ack_is_not_authority_to_send_text_after_source_revocation(db, monkeypatch, tmp_path):
    import scanner_engine, trump_truth_translation as h
    media, item = captured_item(monkeypatch, tmp_path, text='A synthetic peaceful statement.')
    assert posts.ingest([item], AT)['inserted'] == 1
    def translated(system, payload, schema):
        return {'text_he': 'שלום '*300} if 'text_he' in schema['properties'] else approved(system, payload, schema)
    assert h.prepare(at=AT, completion=translated)['prepared'] == 1
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100123')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-unit-token')
    calls = []
    def send(method, fields, asset=None):
        calls.append((method, fields))
        monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'false')
        return {'message_id': 51}
    monkeypatch.setattr(media, '_send', send)
    claimed = scanner_engine._claim_telegram_outbox()
    assert len(claimed) == 1
    result = media.dispatch(claimed[0], {'telegram_enabled': True}, AT)
    assert json.loads(result)['terminal'] is True
    assert len(calls) == 1 and calls[0][0] == 'sendPhoto'


def test_unknown_media_ack_never_replays_or_falls_back_to_source_text(db, monkeypatch, tmp_path):
    import scanner_engine, trump_truth_translation as h
    media, item = captured_item(monkeypatch, tmp_path)
    posts.ingest([item], AT)
    assert h.prepare(at=AT, completion=approved)['prepared'] == 1
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100123')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-unit-token')
    send = Mock(return_value={'unknown': True}); monkeypatch.setattr(media, '_send', send)
    claimed = scanner_engine._claim_telegram_outbox()
    first = media.dispatch(claimed[0], {'telegram_enabled': True}, AT)
    second = media.dispatch(claimed[0], {'telegram_enabled': True}, AT)
    assert json.loads(first)['terminal'] is True and json.loads(second)['terminal'] is True
    assert send.call_count == 1


def test_active_item_expires_but_historical_validation_does_not(monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (AT-timedelta(days=2)).isoformat())
    item = extracted(message(date=AT-timedelta(hours=23)))
    assert posts.valid_item(item, AT)
    assert not posts.valid_item(item, AT+timedelta(hours=2))
    assert posts.valid_item(item, AT+timedelta(hours=2), active=False)


@pytest.mark.parametrize('fence', ['activation', 'environment'])
def test_changed_fence_cancels_before_translation(db, monkeypatch, fence):
    import trump_truth_translation as h
    posts.ingest([extracted()], AT)
    key = 'TELEGRAM_TRUMP_TRUTH_NOT_BEFORE' if fence == 'activation' else 'TELEGRAM_NEWS_NOT_BEFORE'
    monkeypatch.setenv(key, (AT+timedelta(seconds=1)).isoformat())
    completion = Mock(side_effect=AssertionError('No inference past revoked fence'))
    assert h.prepare(at=AT, completion=completion)['prepared'] == 0
    completion.assert_not_called()
    assert rows(db)[0]['status'] == 'cancelled'


def test_expired_inflight_hebrew_is_terminal_unknown_not_retried(db, monkeypatch):
    import scanner_engine, stock_scanner, trump_truth_translation as h
    posts.ingest([extracted()], AT)
    assert h.prepare(at=AT, completion=approved)['prepared'] == 1
    claimed = scanner_engine._claim_telegram_outbox()
    assert len(claimed) == 1
    with db.get_db_connection() as c:
        c.execute('UPDATE scanner_telegram_outbox SET next_attempt_at=?', ((AT-timedelta(seconds=1)).isoformat(),))
    sender = Mock(); monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    saved = rows(db)[0]
    assert saved['status'] == 'failed' and 'unknown' in saved['last_error']
    sender.assert_not_called()


def test_read_only_archive_keeps_hebrew_history_and_cursor_after_flags_off(db, monkeypatch):
    import trump_truth_public as public, trump_truth_translation as h
    for number in (19, 20):
        posts.ingest([extracted(message(number=number))], AT)
        assert h.prepare(at=AT, completion=approved)['prepared'] == 1
        with db.get_db_connection() as c:
            c.execute("UPDATE scanner_telegram_outbox SET status='sent',sent_at=? WHERE status=?",
                      (AT.isoformat(), h.READY))
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE', 'unknown')
    monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
    first = public.payload(now=AT, limit=1)
    assert len(first['items']) == 1 and first['next_cursor'] == 'tg:1462338131:20'
    second = public.payload(now=AT, limit=1, before=first['next_cursor'])
    assert len(second['items']) == 1
    assert second['items'][0]['truth_post_id'] == 'tg:1462338131:19'
    assert second['items'][0]['text_he'] == approved('', {}, h.SCHEMA)['text_he']
    assert second['items'][0]['source_verification'] == 'channel_only'
    assert second['items'][0]['truth_url'] == 'https://t.me/real_DonaldJTrump/19'
    assert second['coverage']['authorship'] == 'SOURCE_CHANNEL_NOT_PRIMARY_VERIFICATION'
    with db.get_db_connection() as c:
        c.execute('DELETE FROM scanner_settings WHERE key=?', (h.cache_key(rows(db)[0]),))
    assert public.payload(now=AT, before='tg:1462338131:20')['items'] == []


def test_old_source_cannot_masquerade_as_a_telegram_namespace_in_archive(db, monkeypatch):
    import trump_truth_public as public
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE', 'truth_relay_v1')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED', 'false')
    old, reason = posts.extract(old_message(), AT)
    assert old is not None and reason is None
    posts.ingest([old], AT)
    saved = rows(db)[0]; envelope = json.loads(saved['message'])
    envelope['item']['truth_post_id'] = 'tg:1462338131:19'
    envelope['item']['truth_url'] = 'https://t.me/real_DonaldJTrump/19'
    saved.update(message=json.dumps(envelope), dedupe_key=posts.PREFIX+'tg:1462338131:19',
                 status='sent', sent_at=AT.isoformat())
    assert public.historic_envelope(saved, AT) is None
