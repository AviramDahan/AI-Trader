"""Synthetic relay posts only; no Telegram, Truth Social or model calls."""
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

import telegram_news_reader as reader

NOW = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)
POST_ID = '117500000000000001'
URL = 'https://truthsocial.com/@realDonaldTrump/' + POST_ID
CHANNEL = 'realdonaldtrump_truth'
CHANNEL_ID = 2310477090
HEADER = 'New Post by realDonaldTrump on Truth Social'


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (NOW-timedelta(minutes=5)).isoformat())
    monkeypatch.setenv('TELEGRAM_NEWS_READER_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_MARKET_NEWS_THREAD_ID', '991')
    monkeypatch.setenv('TELEGRAM_NEWS_SOURCE_CHANNELS', 'financialjuice')


def post(body='A nonfinancial personal post.', author='realDonaldTrump', url=URL, **kw):
    text = f'New Post by {author} on Truth Social\n{body}\nTruth Social Post Link'
    label = 'Truth Social Post Link'
    offset = len(text[:text.rindex(label)].encode('utf-16-le'))//2
    return NS(id=10, date=kw.get('date', NOW), message=text, action=None,
              peer_id=NS(channel_id=kw.get('channel_id', CHANNEL_ID)),
              entities=[NS(offset=offset, length=len(label), url=url)],
              media=kw.get('media'))


def test_source_is_added_only_by_its_separate_flag(enabled, monkeypatch):
    assert reader.channel_names() == ['financialjuice', CHANNEL]
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    assert reader.channel_names() == ['financialjuice']


def test_nonfinancial_post_and_media_have_a_dedicated_not_ai_item(enabled):
    item = reader.message_item(post(), CHANNEL, NOW)
    assert item['source_kind'] == 'trump_truth_relay_v1'
    assert item['truth_post_id'] == POST_ID
    assert item['truth_url'] == URL
    assert item['original_published_at'] is None
    assert item['source_verification'] == 'relay_only'
    image = reader.message_item(post(body='This post contains the following media:', media=object()), CHANNEL, NOW)
    assert image['has_media'] is True


@pytest.mark.parametrize('msg', [post(author='MelaniaTrump'), post(url='https://truthsocial.com/@MelaniaTrump/'+POST_ID),
    post(url='https://truthsocial.com.evil.test/@realDonaldTrump/'+POST_ID),
    post(url='https://truthsocial.com/@realDonaldTrump/'+POST_ID+'?x=1'),
    post(channel_id=999), post(date=NOW+timedelta(seconds=1)),
    post(date=NOW-timedelta(hours=1))])
def test_bad_author_identity_url_time_never_enters_normal_news(enabled, msg):
    assert reader.message_item(msg, CHANNEL, NOW) is None


def test_repost_footer_cannot_make_a_self_reshare_an_original(enabled):
    msg = post(body='🦅 RT: https://truthsocial.com/users/realDonaldTrump/statuses/117400000000000001')
    item = reader.message_item(msg, CHANNEL, NOW)
    assert item is None


def test_disabled_source_cannot_fall_back_to_generic_economic_news(monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    assert reader.message_item(post(), CHANNEL, NOW) is None


@pytest.fixture
def db(enabled, tmp_path, monkeypatch):
    import database
    import scanner_engine
    import stock_scanner
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path/'truth-test.sqlite'))
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'false')
    monkeypatch.delenv('TELEGRAM_NEWS_NOT_BEFORE', raising=False)
    database.init_database()
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(scanner_engine, 'now_z', lambda: NOW.isoformat())
    return database


def saved(db):
    with db.get_db_connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id')]


def test_live_catchup_duplicate_and_restart_share_one_original_id(db):
    from trump_truth_posts import ingest, delivery_message
    first = reader.message_item(post(), CHANNEL, NOW)
    second_message = post(); second_message.id = 11
    second = reader.message_item(second_message, CHANNEL, NOW)
    assert ingest([first], NOW)['inserted'] == 1
    assert ingest([second, first], NOW)['duplicates'] == 2
    assert len(saved(db)) == 1
    text = delivery_message(saved(db)[0], NOW)
    assert URL in text and 'לא אומת' in text
    assert 'https://t.me/'+CHANNEL+'/10' in text


def test_stream_does_not_require_canonical_universe_ai_or_projection(db, monkeypatch):
    import news_pipeline
    from news_events import runtime
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'true')
    def forbidden(*a, **kw):
        pytest.fail('Dedicated relay notification reached canonical AI/trading pipeline')
    monkeypatch.setattr(runtime, 'pipeline', forbidden)
    with db.get_db_connection() as c:
        c.execute('CREATE TABLE ne_control(id INTEGER PRIMARY KEY,mode TEXT,not_before TEXT,epoch INTEGER)')
        c.execute("INSERT INTO ne_control(id,mode,not_before,epoch) VALUES(1,'canonical',?,1)",
                  ((NOW-timedelta(hours=1)).isoformat(),))
        c.commit()
    assert news_pipeline.ingest_items([reader.message_item(post(), CHANNEL, NOW)], NOW)['inserted'] == 1
    with db.get_db_connection() as c:
        assert c.execute('SELECT COUNT(*) n FROM scanner_news').fetchone()['n'] == 0
        assert c.execute("SELECT COUNT(*) n FROM sqlite_master WHERE name='ne_analysis'").fetchone()['n'] == 0


@pytest.mark.parametrize('change', ['off', 'activation', 'cutover', 'topic'])
def test_dispatch_rechecks_current_configuration_before_send(db, monkeypatch, change):
    from trump_truth_posts import ingest, delivery_message
    ingest([reader.message_item(post(), CHANNEL, NOW)], NOW)
    if change == 'off': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    if change == 'activation': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', NOW.isoformat())
    if change == 'cutover': monkeypatch.setenv('TELEGRAM_NEWS_NOT_BEFORE', (NOW+timedelta(seconds=1)).isoformat())
    if change == 'topic':
        monkeypatch.delenv('TELEGRAM_MARKET_NEWS_THREAD_ID', raising=False)
        monkeypatch.delenv('TELEGRAM_NEWS_THREAD_ID', raising=False)
    assert delivery_message(saved(db)[0], NOW) is None


def test_actual_outbox_dispatch_keeps_envelope_and_links_and_never_calls_ai(db, monkeypatch):
    from unittest.mock import Mock
    import scanner_engine as engine
    import stock_scanner
    from trump_truth_posts import ingest, delivery_message
    ingest([reader.message_item(post(), CHANNEL, NOW)], NOW)
    before = saved(db)[0]['message']
    send = Mock(return_value='sent')
    monkeypatch.setattr(stock_scanner, 'send_telegram', send)
    monkeypatch.setattr(engine, '_service', Mock())
    assert engine.process_telegram_outbox() == {'sent': 1, 'failed': 0}
    assert engine.process_telegram_outbox() == {'sent': 0, 'failed': 0}
    assert send.call_count == 1
    assert send.call_args.args[2] == 'trump_truth_post'
    assert URL in send.call_args.args[0]
    assert saved(db)[0]['message'] == before
    assert saved(db)[0]['status'] == 'sent'


def test_restart_never_retries_an_uncertain_sending_lease(db):
    import scanner_engine as engine
    from trump_truth_posts import ingest
    ingest([reader.message_item(post(), CHANNEL, NOW)], NOW)
    with db.get_db_connection() as c:
        c.execute("UPDATE scanner_telegram_outbox SET status='trump_sending',next_attempt_at=?", ((NOW-timedelta(minutes=6)).isoformat(),))
        c.commit()
    assert engine._claim_telegram_outbox() == []
    row = saved(db)[0]
    assert row['status'] == 'failed'
    assert row['last_error'] == 'trump_truth_delivery_unknown_manual_review'


def test_sending_disabled_notification_cancels_not_sends(db, monkeypatch):
    from unittest.mock import Mock
    import scanner_engine as engine
    import stock_scanner
    from trump_truth_posts import ingest
    ingest([reader.message_item(post(), CHANNEL, NOW)], NOW)
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    sender = Mock(); monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert engine.process_telegram_outbox()['sent'] == 0
    sender.assert_not_called()
    assert saved(db)[0]['status'] == 'cancelled'


def test_first_cursor_fence_no_history_then_oldest_unread_restart(db):
    import asyncio
    from unittest.mock import AsyncMock
    fake = NS(get_entity=AsyncMock(return_value=NS(id=CHANNEL_ID, username=CHANNEL, broadcast=True)),
              get_messages=AsyncMock(return_value=[post()]))
    result = asyncio.run(reader.collect(fake, {}, NOW, [CHANNEL]))
    assert result['items'] == []
    assert fake.get_messages.call_args.kwargs == {'limit': 1}
    assert result['checkpoint']['channels'][CHANNEL]['last_id'] == 10
    later = post(); later.id = 11
    fake.get_messages.return_value = [later]
    next_result = asyncio.run(reader.collect(fake, {'checkpoint_json': json.dumps(result['checkpoint'])}, NOW, [CHANNEL]))
    assert fake.get_messages.call_args.kwargs == {'limit': 50, 'min_id': 10, 'reverse': True}
    assert len(next_result['items']) == 1
    assert next_result['checkpoint']['channels'][CHANNEL]['last_id'] == 11


def test_actual_sender_routes_news_and_preserves_primary_and_relay_links(db, monkeypatch):
    from unittest.mock import Mock
    import stock_scanner
    from trump_truth_posts import render
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'unit-test-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setenv('TELEGRAM_TRADING_THREAD_ID', '123')
    session = Mock()
    session.post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 123}}
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    assert stock_scanner.send_telegram(render(reader.message_item(post(), CHANNEL, NOW)),
        {'telegram_enabled': True}, 'trump_truth_post') == 'sent'
    data = session.post.call_args.kwargs['data']
    assert data['message_thread_id'] == 991
    assert URL in data['text'] and 'https://t.me/'+CHANNEL+'/10' in data['text']
