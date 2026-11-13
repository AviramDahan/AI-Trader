"""Independent synthetic Trump-album regressions; no external IO or AI."""
import asyncio
import copy
import importlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

AT = datetime(2026, 11, 8, 8, tzinfo=timezone.utc)
CHANNEL = 1462338131
GROUP = 99887766


@pytest.fixture
def album_env(tmp_path, monkeypatch):
    import database, scanner_engine, stock_scanner, telegram_news_reader as reader
    import trump_truth_media as media
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path / 'independent-album.sqlite'))
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE', 'telegram_channel_v1')
    monkeypatch.setenv('TELEGRAM_TRUMP_CHANNEL_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (AT-timedelta(hours=1)).isoformat())
    monkeypatch.setenv('TELEGRAM_MARKET_NEWS_THREAD_ID', '991')
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'false')
    monkeypatch.delenv('TELEGRAM_NEWS_NOT_BEFORE', raising=False)
    monkeypatch.setattr(scanner_engine, 'now_z', lambda: AT.isoformat())
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    database.init_database()
    monkeypatch.setattr(media, 'CACHE', tmp_path / 'independent-assets')
    monkeypatch.setattr(media, '_budget_state', {'minute': None, 'count': 0, 'bytes': 0})
    session = tmp_path / 'reader.session'
    session.touch(); session.chmod(0o600)
    monkeypatch.setattr(reader, 'SESSION', session)
    classes = {name: type(name, (), {}) for name in
               ('MessageMediaPhoto', 'Photo', 'MessageMediaDocument', 'Document', 'DocumentAttributeVideo')}
    monkeypatch.setattr(media, '_types', lambda: NS(**classes))
    clock = [AT]
    monkeypatch.setattr(media, '_now', lambda: clock[0])
    def message(number, text='', group=GROUP):
        photo = classes['Photo'](); photo.id = 10000+number; photo.sizes = [NS(size=5)]
        attachment = classes['MessageMediaPhoto'](); attachment.photo = photo
        return NS(id=number, date=AT-timedelta(minutes=2), message=text, action=None,
                  peer_id=NS(channel_id=CHANNEL), entities=[], fwd_from=None,
                  forward=None, reply_to=None, reply_to_msg_id=None,
                  photo=photo, document=None, media=attachment, grouped_id=group)
    messages = [message(n) for n in (100, 101, 102)]
    async def read(entity, **kwargs):
        assert entity.id == CHANNEL
        ids = kwargs.get('ids')
        if ids is not None:
            assert all(type(x) is int and x > 0 for x in ids)
            return [m for m in messages if m.id in ids]
        return list(messages)
    async def download(msg, file):
        file.write(b'\xff\xd8\xff'+bytes([msg.id % 256])+b'\xd9')
    client = NS(get_messages=AsyncMock(side_effect=read), download_media=AsyncMock(side_effect=download))
    entity = NS(id=CHANNEL, username='real_DonaldJTrump', broadcast=True)
    return NS(db=database, media=media, clock=clock, message=message, messages=messages,
              client=client, entity=entity)


def test_group_identity_is_retained_without_changing_source_identity(album_env):
    import trump_telegram_channel as source
    item, reason = source.extract(album_env.messages[1], AT)
    assert reason is None
    assert item['telegram_grouped_id'] == GROUP
    assert item['truth_post_id'] == 'tg:1462338131:101'
    assert source.valid_item(item, AT)


@pytest.mark.parametrize('group', [True, False, '99887766', 0, -1, 2**63])
def test_invalid_group_identity_cannot_silently_become_standalone(album_env, group):
    import trump_telegram_channel as source
    msg = album_env.message(100, group=group)
    item, reason = source.extract(msg, AT)
    assert item is None and reason is not None


def test_genuine_single_post_keeps_legacy_identity(album_env):
    import trump_telegram_channel as source
    msg = album_env.message(100, 'A genuine independent post.', group=None)
    item, reason = source.extract(msg, AT)
    assert reason is None and 'telegram_grouped_id' not in item
    assert item['truth_post_id'] == 'tg:1462338131:100'


@pytest.mark.parametrize('damage', ['foreign_peer', 'forwarded_member', 'noncontiguous',
                                     'distinct_captions', 'spread_dates', 'unsupported_media',
                                     'probe_edge'])
def test_unproven_group_never_acquires_or_publishes(album_env, damage):
    import trump_telegram_album as album
    env = album_env
    if damage == 'foreign_peer': env.messages[1].peer_id.channel_id = 999
    elif damage == 'forwarded_member': env.messages[1].fwd_from = NS(from_id=55)
    elif damage == 'noncontiguous': env.messages[1].id = 105
    elif damage == 'distinct_captions':
        env.messages[0].message = 'Distinct caption one.'
        env.messages[1].message = 'Distinct caption two.'
    elif damage == 'spread_dates': env.messages[1].date -= timedelta(seconds=3)
    elif damage == 'unsupported_media': env.messages[1].media = None; env.messages[1].photo = None
    elif damage == 'probe_edge': env.messages.append(env.message(110))
    for offset in (0, 61, 122):
        env.clock[0] = AT+timedelta(seconds=offset)
        item, reason, last = asyncio.run(album.collect_album(env.client, env.entity, env.messages[0], env.clock[0]))
        assert item is None and reason is not None
    env.client.download_media.assert_not_called()
    with env.db.get_db_connection() as conn:
        assert conn.execute('SELECT count(*) FROM scanner_telegram_outbox').fetchone()[0] == 0


def test_first_probe_and_forming_album_do_not_download(album_env):
    import trump_telegram_album as album
    env = album_env
    for msg in env.messages: msg.date = AT-timedelta(seconds=20)
    item, reason, _ = asyncio.run(album.collect_album(env.client, env.entity, env.messages[0], AT))
    assert item is None and reason is not None
    env.client.download_media.assert_not_called()


def test_partial_acquisition_survives_module_restart_without_recapture(album_env):
    import trump_telegram_album as album
    env = album_env
    item = None
    for offset in (0, 61, 122, 183):
        env.clock[0] = AT+timedelta(seconds=offset)
        item, reason, last = asyncio.run(album.collect_album(env.client, env.entity, env.messages[0], env.clock[0]))
        if offset == 61:
            assert item is None, 'three photos cannot bypass existing two-file/minute budget'
            assert env.client.download_media.await_count == 2
            album = importlib.reload(album)
        if item is not None: break
    assert item is not None and reason is None and last == 102
    assert env.client.download_media.await_count == 3, 'already captured first two photos must not be downloaded again'
    assert [call.args[0].id for call in env.client.download_media.await_args_list] == [100, 101, 102]
    import trump_truth_posts as posts
    result = posts.ingest([item], env.clock[0])
    assert result['inserted'] == 1
    with env.db.get_db_connection() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id')]
    active = [r for r in rows if r['status'] == album.PENDING]
    assert len(active) == 1
    assert json.loads(active[0]['message'])['media_version'] == album.VERSION
    assert posts.ingest([item], env.clock[0])['inserted'] == 0



def _complete_group(env):
    import trump_telegram_album as album
    for offset in (0, 61, 122, 183):
        env.clock[0] = AT+timedelta(seconds=offset)
        item, reason, last = asyncio.run(album.collect_album(env.client, env.entity, env.messages[0], env.clock[0]))
        if item is not None:
            return album, item
    pytest.fail('complete supported fixture was not acquired across four existing cycles')


def test_revision_after_partial_capture_revokes_instead_of_mixing_versions(album_env):
    import trump_telegram_album as album
    env = album_env
    for offset in (0, 61):
        env.clock[0] = AT+timedelta(seconds=offset)
        item, _, _ = asyncio.run(album.collect_album(env.client, env.entity, env.messages[0], env.clock[0]))
        assert item is None
    assert env.client.download_media.await_count == 2
    env.messages[2].message = 'Changed source caption.'
    env.clock[0] = AT+timedelta(seconds=122)
    item, reason, _ = asyncio.run(album.collect_album(env.client, env.entity, env.messages[0], env.clock[0]))
    assert item is None and reason is not None
    assert env.client.download_media.await_count == 2
    with env.db.get_db_connection() as conn:
        state = json.loads(conn.execute('SELECT value_json FROM scanner_settings WHERE key=?',
                                       (album.VERSION+':acquire:'+str(GROUP),)).fetchone()['value_json'])
        assert state['phase'] == 'revoked'
        assert conn.execute('SELECT count(*) FROM scanner_telegram_outbox').fetchone()[0] == 0


@pytest.mark.parametrize('existing_status', ['trump_hebrew_pending', 'sent', 'failed', 'trump_media_sending'])
def test_any_existing_member_publication_blocks_whole_album_atomically(album_env, existing_status):
    import trump_truth_posts as posts
    env = album_env
    album, item = _complete_group(env)
    member_key = posts.PREFIX+'tg:1462338131:101'
    with env.db.get_db_connection() as conn:
        conn.execute('INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at) VALUES(?,?,?,?,?,?,?)',
                     (member_key, posts.EVENT, 'previous immutable record', existing_status, 0,
                      AT.isoformat(), AT.isoformat()))
    result = posts.ingest([item], env.clock[0])
    assert result['inserted'] == 0
    with env.db.get_db_connection() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM scanner_telegram_outbox')]
    assert len(rows) == 1 and rows[0]['dedupe_key'] == member_key
    assert rows[0]['status'] == existing_status and rows[0]['message'] == 'previous immutable record'


def test_caption_on_later_member_keeps_caption_and_complete_ordered_album(album_env):
    env = album_env
    env.messages[2].message = 'A caption only on the last member.'
    album, item = _complete_group(env)
    assert item['relay_message_id'] == 102 and item['text_excerpt'] == env.messages[2].message
    import trump_truth_posts as posts
    assert posts.ingest([item], env.clock[0])['inserted'] == 1
    with env.db.get_db_connection() as conn:
        row = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE status=?', (album.PENDING,)).fetchone())
        envelope = json.loads(row['message'])
        members = album.checked_manifest(row, envelope, env.clock[0], conn=conn)
    assert [m['relay_message_id'] for m in members] == [100, 101, 102]
    assert len({m['media']['sha256'] for m in members}) == 3


def test_missing_member_claim_cannot_be_reconstructed_from_manifest(album_env):
    env = album_env
    album, item = _complete_group(env)
    import trump_truth_posts as posts
    assert posts.ingest([item], env.clock[0])['inserted'] == 1
    with env.db.get_db_connection() as conn:
        row = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE status=?', (album.PENDING,)).fetchone())
        envelope = json.loads(row['message'])
        conn.execute('DELETE FROM scanner_telegram_outbox WHERE dedupe_key=?', (posts.PREFIX+'tg:1462338131:101',))
        with pytest.raises(ValueError):
            album.checked_manifest(row, envelope, env.clock[0], conn=conn)



def test_ordinary_channel_old_bootstrap_cursor_behavior_is_preserved(album_env):
    import telegram_news_reader as reader
    old = NS(id=50, date=AT-timedelta(hours=2), message='Old ordinary news.',
             action=None, peer_id=NS(channel_id=222))
    client = NS(get_entity=AsyncMock(return_value=NS(id=222, username='financialjuice', broadcast=True)),
                get_messages=AsyncMock(return_value=[old]))
    result = asyncio.run(reader.collect(client, {'checkpoint_json':'{}'}, AT, ['financialjuice']))
    assert result['items'] == [] and result['errors'] == []
    assert result['checkpoint']['channels']['financialjuice']['last_id'] == 50



@pytest.mark.parametrize('outcome', ['ack', 'partial_ack', 'crash', 'global_off'])
def test_actual_prepare_claim_outbox_and_transport_with_synthetic_ack_only(album_env, monkeypatch, outcome):
    import requests, scanner_engine as engine, stock_scanner
    import trump_truth_posts as posts, trump_truth_translation as he, trump_telegram_album_delivery as delivery
    env = album_env
    album, item = _complete_group(env)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setattr(engine, 'now_z', lambda: env.clock[0].isoformat())
    monkeypatch.setattr(delivery, '_now', lambda: env.clock[0])
    monkeypatch.setattr(stock_scanner, 'send_telegram', lambda *a, **k: pytest.fail('generic text fallback forbidden'))
    if outcome == 'global_off':
        monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': False})
    assert posts.ingest([item], env.clock[0])['inserted'] == 1
    def no_ai(*args, **kwargs): pytest.fail('captionless album must not call AI or AI health')
    import ai_routing
    monkeypatch.setattr(ai_routing, 'ready', no_ai)
    assert he.prepare(at=env.clock[0], completion=no_ai)['prepared'] == 1
    with env.db.get_db_connection() as conn:
        row = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE status=?', (album.READY,)).fetchone())
        original = row['message']
    calls = []
    class Session:
        trust_env = True
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            assert self.trust_env is False and kwargs['allow_redirects'] is False
            assert kwargs['timeout'] == 30 and url.endswith('/sendMediaGroup')
            spec = json.loads(kwargs['data']['media'])
            assert len(spec) == 3 and len(kwargs['files']) == 3
            assert sum('caption' in part for part in spec) == 1
            assert all(part['type'] == 'photo' for part in spec)
            if outcome == 'crash': raise KeyboardInterrupt('synthetic post-acceptance process death')
            ids = [501, 502] if outcome == 'partial_ack' else [501, 502, 503]
            ack = [dict(message_id=n, chat={'id': -1001}, message_thread_id=991,
                        media_group_id='synthetic-group', photo=[{}]) for n in ids]
            return NS(status_code=200, json=lambda: {'ok':True, 'result':ack})
        def close(self): pass
    monkeypatch.setattr(requests, 'Session', Session)
    if outcome == 'crash':
        with pytest.raises(KeyboardInterrupt): engine.process_telegram_outbox()
        env.clock[0] += timedelta(seconds=301)
        assert engine.process_telegram_outbox()['sent'] == 0
    else:
        result = engine.process_telegram_outbox()
        assert result['sent'] == (1 if outcome == 'ack' else 0)
    with env.db.get_db_connection() as conn:
        after = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone())
        assert after['message'] == original
        aliases = [dict(r) for r in conn.execute('SELECT * FROM scanner_telegram_outbox WHERE status=?', (album.CLAIMED,))]
        assert len(aliases) == 3
        assert conn.execute('SELECT count(*) FROM scanner_trades').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM scanner_orders').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM scanner_signals').fetchone()[0] == 0
    expected = {'ack': 'sent', 'partial_ack': 'failed', 'crash': 'failed', 'global_off': 'disabled'}[outcome]
    assert after['status'] == expected
    assert len(calls) == (0 if outcome == 'global_off' else 1)
    assert engine.process_telegram_outbox()['sent'] == 0
    assert len(calls) == (0 if outcome == 'global_off' else 1)
    if outcome == 'ack':
        receipt = delivery.receipt(row)
        assert receipt['status'] == 'complete' and receipt['message_ids'] == [501, 502, 503]
        import trump_truth_public
        assert trump_truth_public.historic_envelope(after, env.clock[0]) is None, 'single-asset archive must not misrepresent new album'
    elif outcome == 'partial_ack':
        assert delivery.receipt(row)['status'] == 'unknown'


def test_old_empty_media_placeholder_cannot_fall_back_to_text(album_env, monkeypatch):
    import scanner_engine as engine, stock_scanner
    import trump_truth_posts as posts, trump_truth_translation as he, trump_telegram_channel as source
    env = album_env
    msg = env.message(200, group=None)
    item, _ = source.extract(msg, AT)
    item['media'].update(status='unavailable', reason='budget_exhausted')
    with env.db.get_db_connection() as conn:
        envelope = dict(item=item, fence=posts.fence(conn.cursor(), item), presentation='hebrew_v1')
        conn.execute('INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at) VALUES(?,?,?,?,?,?,?)',
                     (posts.PREFIX+item['truth_post_id'], posts.EVENT, json.dumps(envelope),
                      'trump_hebrew_pending', 0, AT.isoformat(), AT.isoformat()))
    def no_side_effect(*args, **kwargs): pytest.fail('empty placeholder cannot invoke AI or Telegram')
    monkeypatch.setattr(stock_scanner, 'send_telegram', no_side_effect)
    assert he.prepare(at=AT, completion=no_side_effect)['prepared'] == 1
    assert engine.process_telegram_outbox()['sent'] == 0
    with env.db.get_db_connection() as conn:
        row = dict(conn.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
    assert row['status'] == 'cancelled'



def test_actual_reader_holds_album_cursor_across_budget_cycles_and_preserves_other_channels(album_env):
    import telegram_news_reader as reader, trump_truth_posts as posts
    env = album_env
    ordinary_entity = NS(id=222, username='financialjuice', broadcast=True)
    ordinary = NS(id=80, date=AT-timedelta(minutes=1), message='A distinct economic event.',
                  action=None, peer_id=NS(channel_id=222))
    async def entity(name): return env.entity if name == 'real_donaldjtrump' else ordinary_entity
    async def messages(entity, **kwargs):
        if entity.id == 222: return [ordinary]
        if 'ids' in kwargs: return env.messages
        return [env.messages[0]]  # This normal page ends inside the source album.
    env.client.get_entity = AsyncMock(side_effect=entity)
    env.client.get_messages = AsyncMock(side_effect=messages)
    checkpoint = {'channels': {'real_donaldjtrump': {'last_id':99, 'trump_activation':posts.activation()}}}
    for offset, expected_cursor in [(0,99),(61,99),(122,102)]:
        env.clock[0] = AT+timedelta(seconds=offset)
        result = asyncio.run(reader.collect(env.client, {'checkpoint_json':json.dumps(checkpoint)},
                                            env.clock[0], ['real_donaldjtrump','financialjuice']))
        assert result['checkpoint']['channels']['real_donaldjtrump']['last_id'] == expected_cursor
        assert any(item.get('provider') == 'telegram_channels' and item.get('source_kind') == 'telegram_post'
                   for item in result['items']), 'one incomplete Trump group cannot block other channels'
        grouped = [item for item in result['items'] if item.get('telegram_grouped_id') == GROUP]
        assert len(grouped) == (1 if offset == 122 else 0)
        checkpoint = result['checkpoint']
    assert env.client.download_media.await_count == 3


def test_reader_skips_existing_member_aliases_even_after_local_cache_loss(album_env):
    import telegram_news_reader as reader, trump_truth_posts as posts
    env = album_env
    album, item = _complete_group(env)
    assert posts.ingest([item], env.clock[0])['inserted'] == 1
    with env.db.get_db_connection() as conn:
        conn.execute('DELETE FROM scanner_settings WHERE key=?', (album.VERSION+':acquire:'+str(GROUP),))
    for file in env.media.CACHE.iterdir(): file.unlink()
    env.client.get_entity = AsyncMock(return_value=env.entity)
    env.client.get_messages = AsyncMock(return_value=env.messages)
    before = env.client.download_media.await_count
    state = {'checkpoint_json':json.dumps({'channels': {'real_donaldjtrump':
             {'last_id':99, 'trump_activation':posts.activation()}}})}
    result = asyncio.run(reader.collect(env.client, state, env.clock[0], ['real_donaldjtrump']))
    assert result['errors'] == [] and result['items'] == []
    assert result['checkpoint']['channels']['real_donaldjtrump']['last_id'] == 102
    assert env.client.download_media.await_count == before
    assert env.client.get_messages.await_count == 1, 'dedupe aliases precede group re-probing'


def test_live_style_grouped_member_without_manifest_never_queues_standalone(album_env):
    import telegram_news_reader as reader, trump_truth_posts as posts
    env = album_env
    item = reader.stream_item(env.messages[0], {CHANNEL:'real_donaldjtrump'}, AT)
    assert item['telegram_grouped_id'] == GROUP and 'album_ref' not in item
    assert posts.ingest([item], AT)['inserted'] == 0
    with env.db.get_db_connection() as conn:
        assert conn.execute('SELECT count(*) FROM scanner_telegram_outbox').fetchone()[0] == 0
    env.client.download_media.assert_not_called()



def test_concurrent_dispatch_same_lease_cas_allows_only_one_remote_call(album_env, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    import scanner_engine as engine, trump_truth_posts as posts
    import trump_truth_translation as he, trump_telegram_album_delivery as delivery
    env = album_env
    album, item = _complete_group(env)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setattr(engine, 'now_z', lambda: env.clock[0].isoformat())
    monkeypatch.setattr(delivery, '_now', lambda: env.clock[0])
    assert posts.ingest([item], env.clock[0])['inserted'] == 1
    assert he.prepare(at=env.clock[0], completion=lambda *a: pytest.fail('no AI'))['prepared'] == 1
    row = engine._claim_telegram_outbox()[0]
    original_receipt = delivery.receipt
    both_read_empty = Barrier(2)
    def race_read(*args, **kwargs):
        value = original_receipt(*args, **kwargs)
        assert value is None
        both_read_empty.wait(timeout=5)
        return value
    monkeypatch.setattr(delivery, 'receipt', race_read)
    calls = []
    lock = Lock()
    def one_ack(*args):
        with lock: calls.append(args)
        return {'message_ids':[501,502,503], 'media_group_id':'synthetic-group'}
    monkeypatch.setattr(delivery, '_send_album', one_ack)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(delivery.dispatch, row, {'telegram_enabled':True}, env.clock[0]) for _ in range(2)]
        results = [job.result(timeout=10) for job in jobs]
    assert results.count('sent') == 1
    assert len(calls) == 1
    assert original_receipt(row)['status'] == 'complete'



def test_observed_group_edit_revokes_even_before_reconnect_catchup_readiness(album_env, monkeypatch):
    import ast, inspect
    from unittest.mock import Mock
    import telegram_news_reader as reader, trump_telegram_album as album
    # Execute the actual nested callback body offline; no client/session loop.
    tree = ast.parse(inspect.getsource(reader.telegram_news_stream_loop))
    callback = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == 'on_message')
    unit = ast.fix_missing_locations(ast.Module(body=[callback], type_ignores=[]))
    class EditedEvent:
        def __init__(self, message): self.message = message
    namespace = {'asyncio':asyncio, 'datetime':datetime, 'timezone':timezone,
                 'trump_ready':False, 'allowed':{CHANNEL:'real_donaldjtrump'},
                 'events':NS(MessageEdited=NS(Event=EditedEvent))}
    exec(compile(unit, '<actual-reader-callback>', 'exec'), namespace)
    revoke = Mock()
    monkeypatch.setattr(album, 'invalidate_group', revoke)
    asyncio.run(namespace['on_message'](EditedEvent(album_env.messages[0])))
    revoke.assert_called_once()
    assert revoke.call_args.args[0] is album_env.messages[0]
