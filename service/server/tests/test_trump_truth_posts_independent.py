"""Independent synthetic Truth relay controls; never contact either service."""
import json
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
import requests

import telegram_news_reader as reader


NOW = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
CHANNEL = 'realdonaldtrump_truth'
CHANNEL_ID = 2310477090
POST_ID = '117500000000000123'
URL = 'https://truthsocial.com/@realDonaldTrump/' + POST_ID
LABEL = 'Truth Social Post Link'
HEADER = 'New Post by realDonaldTrump on Truth Social'


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Independent synthetic test attempted external I/O')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)


@pytest.fixture
def enabled(monkeypatch):
    for key, value in {
        'TELEGRAM_TRUMP_TRUTH_ENABLED': 'true',
        'TELEGRAM_TRUMP_TRUTH_NOT_BEFORE': (NOW-timedelta(minutes=5)).isoformat(),
        'TELEGRAM_NEWS_READER_ENABLED': 'true',
        'TELEGRAM_MARKET_NEWS_THREAD_ID': '991',
        'TELEGRAM_NEWS_SOURCE_CHANNELS': 'financialjuice',
    }.items():
        monkeypatch.setenv(key, value)


def post(body='A personal non-economic statement.', *, url=URL, header=HEADER,
         number=100, date=NOW, source_id=CHANNEL_ID):
    text = header + '\n' + body + '\n' + LABEL
    offset = len(text[:text.rindex(LABEL)].encode('utf-16-le')) // 2
    return NS(id=number, date=date, message=text, action=None,
              peer_id=NS(channel_id=source_id),
              entities=[NS(offset=offset, length=len(LABEL), url=url)], media=None)


def item(message):
    return reader.message_item(message, CHANNEL, NOW)


def test_default_off_never_reclassifies_dedicated_relay_as_generic_news(monkeypatch):
    monkeypatch.delenv('TELEGRAM_TRUMP_TRUTH_ENABLED', raising=False)
    assert item(post()) is None


@pytest.mark.parametrize('body', ['A personal greeting.', 'A sports result.',
    'A religious statement.', '🦅😀 A statement with supplementary Unicode.'])
def test_non_economic_topics_and_utf16_footer_are_not_ai_filtered(enabled, body):
    value = item(post(body))
    assert value['truth_url'] == URL
    assert value['truth_post_id'] == POST_ID
    assert value['source_verification'] == 'relay_only'
    assert value['original_published_at'] is None


@pytest.mark.parametrize('url', [
    'http://truthsocial.com/@realDonaldTrump/' + POST_ID,
    'https://truthsocial.com.evil.example/@realDonaldTrump/' + POST_ID,
    'https://truthsocial.com@evil.example/@realDonaldTrump/' + POST_ID,
    'https://evil.example/?next=' + URL,
    'https://truthsocial.com/@MelaniaTrump/' + POST_ID,
    URL + '?next=evil', URL + '#fragment',
    'https://truthsocial.com/@realDonaldTrump/not-a-post',
])
def test_only_unambiguous_original_account_and_link_are_eligible(enabled, url):
    assert item(post(url=url)) is None


@pytest.mark.parametrize('header', [
    'New Post by MelaniaTrump on Truth Social',
    'New Post by realDonaldTrump Jr on Truth Social',
    'A quoted notice: ' + HEADER,
])
def test_author_header_cannot_be_inferred_from_a_trump_link(enabled, header):
    assert item(post(header=header)) is None


@pytest.mark.parametrize('offset_delta,length_delta', [(1, 0), (-1, 0), (0, -1), (0, 1)])
def test_entity_must_cover_complete_footer_not_adjacent_or_partial_text(enabled, offset_delta, length_delta):
    message = post('🦅 supplementary Unicode before the footer')
    message.entities[0].offset += offset_delta
    message.entities[0].length += length_delta
    assert item(message) is None


def test_conflicting_original_post_footer_entities_fail_closed(enabled):
    message = post()
    message.entities.append(NS(offset=message.entities[0].offset, length=len(LABEL),
                               url='https://truthsocial.com/@realDonaldTrump/117500000000000456'))
    assert item(message) is None


def test_body_reference_is_not_substituted_for_missing_original_footer_link(enabled):
    message = post('Quoted post ' + URL)
    message.entities = []
    assert item(message) is None


def test_wrong_channel_identity_never_falls_back_to_generic_news(enabled):
    assert item(post(source_id=CHANNEL_ID+1)) is None


def test_lookalike_username_cannot_reuse_expected_peer(enabled):
    assert reader.message_item(post(), CHANNEL + '_other', NOW) is None


def test_media_only_post_retains_original_link_without_inventing_original_timestamp(enabled):
    message = post('This post contains the following media:')
    message.media = object()
    value = item(message)
    assert value['has_media'] is True
    assert value['truth_url'] == URL
    assert value['original_published_at'] is None


@pytest.mark.parametrize('date', [NOW+timedelta(microseconds=1), NOW-timedelta(minutes=6)])
def test_future_and_pre_activation_relay_posts_are_not_published(enabled, date):
    assert item(post(date=date)) is None


def test_source_flag_does_not_replace_ordinary_channel_allowlist(enabled):
    assert reader.channel_names() == ['financialjuice', CHANNEL]


def test_generic_ordinary_source_item_contract_remains_unchanged(enabled):
    value = reader.message_item(post('Ordinary relay headline', source_id=999), 'financialjuice', NOW)
    assert value['source_kind'] == 'telegram_post'
    assert value['url'] == 'https://t.me/financialjuice/100'
    assert 'truth_post_id' not in value


def fake_client(messages, *, entity_id=CHANNEL_ID, username=CHANNEL):
    return NS(get_entity=AsyncMock(return_value=NS(id=entity_id, username=username, broadcast=True)),
              get_messages=AsyncMock(return_value=messages))


def run_stub(coroutine):
    """Mocks complete synchronously; no Windows event-loop socketpair required."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()
    raise AssertionError('Synthetic async transport unexpectedly required real I/O')


def checkpoint(last_id=100):
    import trump_truth_posts as trump
    return {'checkpoint_json': json.dumps({'channels': {CHANNEL: {
        'last_id': last_id, 'trump_activation': trump.activation()}}})}


def test_initial_activation_fences_latest_id_without_historical_burst(enabled):
    client = fake_client([post(number=200)])
    value = run_stub(reader.collect(client, {}, NOW, [CHANNEL]))
    assert value['items'] == []
    assert value['checkpoint']['channels'][CHANNEL]['last_id'] == 200
    assert client.get_messages.call_args.kwargs == {'limit': 1}
    assert 'no_history' in value['checkpoint']['channels'][CHANNEL]['coverage']


def test_reactivation_uses_new_fence_not_old_checkpoint_history(enabled, monkeypatch):
    state = checkpoint()
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (NOW-timedelta(minutes=1)).isoformat())
    client = fake_client([post(number=201)])
    result = run_stub(reader.collect(client, state, NOW, [CHANNEL]))
    assert result['items'] == []
    assert result['checkpoint']['channels'][CHANNEL]['last_id'] == 201
    assert client.get_messages.call_args.kwargs == {'limit': 1}


def test_durable_cursor_pages_oldest_unread_fifty_without_six_hour_news_cutoff(enabled, monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (NOW-timedelta(days=1)).isoformat())
    client = fake_client([post(number=101, date=NOW-timedelta(hours=7))])
    result = run_stub(reader.collect(client, checkpoint(), NOW, [CHANNEL]))
    assert len(result['items']) == 1
    assert result['checkpoint']['channels'][CHANNEL]['last_id'] == 101
    assert client.get_messages.call_args.kwargs == {'limit': 50, 'min_id': 100, 'reverse': True}


@pytest.mark.parametrize('entity_id,username', [(CHANNEL_ID+1, CHANNEL), (CHANNEL_ID, CHANNEL+'_other')])
def test_source_identity_mismatch_never_reads_messages_or_advances_cursor(enabled, entity_id, username):
    client = fake_client([post(number=101)], entity_id=entity_id, username=username)
    result = run_stub(reader.collect(client, checkpoint(), NOW, [CHANNEL]))
    client.get_messages.assert_not_called()
    assert result['items'] == []
    assert result['errors']
    assert result['checkpoint']['channels'][CHANNEL]['last_id'] == 100


def test_other_author_advances_cursor_but_is_not_sent_or_generic_news(enabled):
    client = fake_client([post(number=101, header='New Post by MelaniaTrump on Truth Social')])
    result = run_stub(reader.collect(client, checkpoint(), NOW, [CHANNEL]))
    assert result['items'] == []
    assert result['checkpoint']['channels'][CHANNEL]['last_id'] == 101
    assert result['checkpoint']['channels'][CHANNEL]['rejected'] == {'other_author_or_header': 1}


@pytest.fixture
def local_db(tmp_path, monkeypatch, enabled):
    import database
    import scanner_engine as engine
    import trump_truth_posts as trump
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path/'independent-trump.db'))
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'false')
    monkeypatch.setenv('TELEGRAM_NEWS_NOT_BEFORE', '')
    monkeypatch.setenv('STOCK_SCANNER_TELEGRAM_ENABLED', 'true')
    class FrozenMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)
    class FrozenDateTime(datetime, metaclass=FrozenMeta):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(trump, 'datetime', FrozenDateTime)
    monkeypatch.setattr(engine, 'now_z', lambda: NOW.isoformat())
    database.init_database()
    return NS(db=database, engine=engine, trump=trump)


def outbox(fixture):
    with fixture.db.get_db_connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id')]


def test_actual_ingest_relay_duplicates_are_one_original_post_and_no_trading_or_news_job(local_db):
    import news_pipeline
    names = ('scanner_news', 'scanner_news_jobs', 'scanner_orders', 'scanner_trades',
             'scanner_signals', 'scanner_fills', 'scanner_accounts')
    def counts():
        with local_db.db.get_db_connection() as db:
            return {name: db.execute('SELECT count(*) n FROM '+name).fetchone()['n'] for name in names}
    before = counts()
    first = news_pipeline.ingest_items([item(post(number=100))], NOW)
    duplicate = news_pipeline.ingest_items([item(post(number=101))], NOW)
    assert first['inserted'] == 1 and duplicate['duplicates'] == 1
    assert len(outbox(local_db)) == 1
    assert outbox(local_db)[0]['dedupe_key'] == local_db.trump.PREFIX+POST_ID
    assert counts() == before


@pytest.mark.parametrize('state', ['trump_pending', 'trump_retry', 'trump_sending'])
def test_previous_binary_due_selector_cannot_claim_dedicated_provenance(local_db, state):
    local_db.trump.ingest([item(post())], NOW)
    assert outbox(local_db)[0]['status'] == 'trump_pending'
    with local_db.db.get_db_connection() as db:
        db.execute('UPDATE scanner_telegram_outbox SET status=?', (state,))
        # Exact due-status set from reviewed base9c scanner_engine._claim_telegram_outbox.
        # That binary cannot interpret the envelope/event or its OFF gate and
        # would otherwise send JSON through the trading-topic fallback.
        assert db.execute("SELECT count(*) n FROM scanner_telegram_outbox "
                          "WHERE status IN ('pending','retry','community_pending') "
                          "AND event_type='trump_truth_post'").fetchone()['n'] == 0
        assert db.execute("SELECT count(*) n FROM scanner_telegram_outbox "
                          "WHERE status='sending' AND event_type='trump_truth_post'").fetchone()['n'] == 0


def test_ingest_transaction_rolls_back_earlier_enqueue_if_later_enqueue_fails(local_db, monkeypatch):
    original = local_db.engine.enqueue_telegram
    called = []
    def fail_second(*args, **kwargs):
        called.append(1)
        if len(called) == 2:
            raise RuntimeError('synthetic interrupted batch')
        return original(*args, **kwargs)
    monkeypatch.setattr(local_db.engine, 'enqueue_telegram', fail_second)
    with pytest.raises(RuntimeError, match='interrupted batch'):
        local_db.trump.ingest([item(post()), item(post(url=URL[:-3]+'456'))], NOW)
    assert outbox(local_db) == []


def test_actual_outbox_safe_retry_retains_envelope_and_then_sends_once(local_db, monkeypatch):
    import stock_scanner
    local_db.trump.ingest([item(post())], NOW)
    original = outbox(local_db)[0]['message']
    sender = Mock(side_effect=['connect_timeout', 'sent'])
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert local_db.engine.process_telegram_outbox()['failed'] == 1
    assert outbox(local_db)[0]['status'] == 'trump_retry'
    assert outbox(local_db)[0]['message'] == original
    with local_db.db.get_db_connection() as db:
        db.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    assert local_db.engine.process_telegram_outbox()['sent'] == 1
    assert outbox(local_db)[0]['status'] == 'sent'
    assert outbox(local_db)[0]['message'] == original
    assert local_db.engine.process_telegram_outbox()['sent'] == 0
    assert sender.call_count == 2
    delivered = sender.call_args.args[0]
    assert URL in delivered and 'https://t.me/'+CHANNEL+'/100' in delivered
    assert 'לא אומת' in delivered


def test_unknown_delivery_and_expired_sending_lease_are_never_retried(local_db, monkeypatch):
    import stock_scanner
    local_db.trump.ingest([item(post())], NOW)
    sender = Mock(return_value=json.dumps({'terminal': True, 'reason': 'delivery_unknown_manual_review'}))
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert local_db.engine.process_telegram_outbox()['failed'] == 1
    assert outbox(local_db)[0]['status'] == 'failed'
    assert local_db.engine.process_telegram_outbox()['sent'] == 0
    assert sender.call_count == 1
    with local_db.db.get_db_connection() as db:
        db.execute("UPDATE scanner_telegram_outbox SET status='trump_sending', next_attempt_at='2000-01-01T00:00:00Z'")
    assert local_db.engine._claim_telegram_outbox() == []
    assert outbox(local_db)[0]['status'] == 'failed'
    assert outbox(local_db)[0]['last_error'] == 'trump_truth_delivery_unknown_manual_review'


@pytest.mark.parametrize('fence', ['off', 'new_activation', 'cutover'])
def test_pending_delivery_is_rechecked_before_any_send(local_db, monkeypatch, fence):
    import stock_scanner
    local_db.trump.ingest([item(post())], NOW)
    if fence == 'off':
        monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    elif fence == 'new_activation':
        monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (NOW-timedelta(minutes=1)).isoformat())
    else:
        monkeypatch.setenv('TELEGRAM_NEWS_NOT_BEFORE', NOW.isoformat())
    sender = Mock()
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    local_db.engine.process_telegram_outbox()
    sender.assert_not_called()
    assert outbox(local_db)[0]['status'] == 'cancelled'


def test_explicit_news_destination_and_source_links_survive_presentation(enabled, monkeypatch):
    import telegram_topics as topics
    monkeypatch.setenv('TELEGRAM_TRADING_THREAD_ID', '777')
    assert topics.destination_fields('-100synthetic', 'trump_truth_post')['message_thread_id'] == 991
    message = 'Original\n'+URL+'\nhttps://t.me/'+CHANNEL+'/100'
    assert topics.with_news_community_link(message, 'trump_truth_post') == message
    assert URL not in topics.with_news_community_link(message, 'market_news')
    monkeypatch.delenv('TELEGRAM_MARKET_NEWS_THREAD_ID')
    monkeypatch.delenv('TELEGRAM_NEWS_THREAD_ID', raising=False)
    assert topics.thread_id_for_event('trump_truth_post') is None


@pytest.mark.parametrize('exception', [requests.ReadTimeout, requests.ConnectionError,
                                     requests.exceptions.ChunkedEncodingError])
def test_actual_sender_ambiguous_response_failures_do_not_resend(local_db, monkeypatch, exception):
    import stock_scanner
    local_db.trump.ingest([item(post())], NOW)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    session = Mock()
    session.post.side_effect = exception('synthetic response-read failure')
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    local_db.engine.process_telegram_outbox()
    assert outbox(local_db)[0]['status'] == 'failed'
    local_db.engine.process_telegram_outbox()
    assert session.post.call_count == 1


def test_malformed_dedicated_boundary_does_not_disable_existing_source(enabled, monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', 'not-an-aware-instant')
    names = reader.channel_names()
    assert 'financialjuice' in names
    client = fake_client([])
    result = run_stub(reader.collect(client, {}, NOW, [CHANNEL]))
    assert result['status'] == 'degraded' and result['errors']
    assert result['items'] == []
    assert CHANNEL not in result['checkpoint']['channels'] or 'last_success_at' not in result['checkpoint']['channels'][CHANNEL]


def test_disabled_raw_ingest_does_not_open_database(enabled, monkeypatch):
    import database
    import trump_truth_posts as trump
    value = item(post())
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    connection = Mock(side_effect=AssertionError('OFF path must not open database'))
    monkeypatch.setattr(database, 'get_db_connection', connection)
    assert trump.ingest([value], NOW)['inserted'] == 0
    connection.assert_not_called()


@pytest.mark.parametrize('field,value', [
    ('truth_post_id', '117500000000000456'), ('relay_channel', 'other_channel'),
    ('relay_channel_id', CHANNEL_ID+1), ('relay_message_id', True),
    ('original_published_at', NOW.isoformat()), ('source_verification', 'verified'),
    ('observed_at', (NOW+timedelta(seconds=1)).isoformat()),
    ('text_excerpt', 'Fabricated https://evil.example/ link'),
])
def test_stored_envelope_fields_are_revalidated_before_render(local_db, field, value):
    local_db.trump.ingest([item(post())], NOW)
    row = outbox(local_db)[0]
    envelope = json.loads(row['message'])
    envelope['item'][field] = value
    row['message'] = json.dumps(envelope)
    assert local_db.trump.delivery_message(row, NOW) is None


def test_mode_epoch_change_revokes_preexisting_pending_envelope(local_db, monkeypatch):
    from news_events import control
    monkeypatch.setattr(control, 'state', lambda *_: {'mode': 'canonical', 'epoch': 3, 'not_before': ''})
    local_db.trump.ingest([item(post())], NOW)
    row = outbox(local_db)[0]
    assert local_db.trump.delivery_message(row, NOW) is not None
    monkeypatch.setattr(control, 'state', lambda *_: {'mode': 'canonical', 'epoch': 4, 'not_before': ''})
    assert local_db.trump.delivery_message(row, NOW) is None


def test_actual_sender_missing_news_topic_cannot_use_trading_fallback(enabled, monkeypatch):
    import stock_scanner
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setenv('TELEGRAM_TRADING_THREAD_ID', '777')
    monkeypatch.delenv('TELEGRAM_MARKET_NEWS_THREAD_ID')
    monkeypatch.delenv('TELEGRAM_NEWS_THREAD_ID', raising=False)
    session = Mock()
    monkeypatch.setattr(stock_scanner.requests, 'Session', session)
    result = json.loads(stock_scanner.send_telegram('Synthetic', {'telegram_enabled': True}, 'trump_truth_post'))
    assert result['terminal'] is True
    session.assert_not_called()


def test_real_photo_and_webpage_preview_are_not_confused(enabled):
    message = post('')
    message.photo = object()
    assert item(message)['has_media'] is True
    message.photo = None
    message.media = NS(webpage=object())
    assert item(message)['has_media'] is False


def test_five_existing_sources_are_preserved_with_one_pinned_source(enabled, monkeypatch):
    ordinary = ['alpha_one', 'bravo_two', 'charlie_three', 'delta_four', 'echo_five']
    monkeypatch.setenv('TELEGRAM_NEWS_SOURCE_CHANNELS', ','.join(ordinary))
    assert reader.channel_names() == ordinary+[CHANNEL]


@pytest.mark.parametrize('receipt,expected', [
    ({'ok': True, 'result': {'message_id': 42}}, 'sent'),
    ({'ok': True, 'result': {'message_id': True}}, 'failed'),
    ({'ok': False, 'description': 'synthetic unverified response'}, 'failed'),
])
def test_actual_success_acknowledgement_is_strict_and_keeps_full_source_links(local_db, monkeypatch, receipt, expected):
    import stock_scanner
    local_db.trump.ingest([item(post('🦅'*1200))], NOW)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    session = Mock()
    session.post.return_value.json.return_value = receipt
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    local_db.engine.process_telegram_outbox()
    assert outbox(local_db)[0]['status'] == expected
    data = session.post.call_args.kwargs['data']
    assert data['message_thread_id'] == 991
    assert URL in data['text'] and 'https://t.me/'+CHANNEL+'/100' in data['text']
    assert len(data['text'].encode('utf-16-le'))//2 <= 4096


def test_explicit_telegram_rate_limit_preserves_retry_after_and_dedicated_queue(local_db, monkeypatch):
    import stock_scanner
    local_db.trump.ingest([item(post())], NOW)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    response = Mock(status_code=429, headers={})
    response.json.return_value = {'parameters': {'retry_after': 700}}
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    session = Mock()
    session.post.return_value = response
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    local_db.engine.process_telegram_outbox()
    row = outbox(local_db)[0]
    assert row['status'] == 'trump_retry'
    assert json.loads(row['last_error'])['retry_after'] == 700
