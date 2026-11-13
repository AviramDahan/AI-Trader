"""Independent media-stage and actual engine controls; no real transport/model."""
import asyncio
import ast
import inspect
import json
import stat
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import test_trump_truth_media as owner
import test_trump_truth_posts_independent as source_controls

no_external_io = source_controls.no_external_io
media = owner.media
db = owner.db


@pytest.fixture(autouse=True)
def synchronous_mock_capture(monkeypatch, no_external_io):
    # These injected downloads complete synchronously. Avoid Windows asyncio's
    # loopback socketpair, without allowing any network through the deny guard.
    # This fixture does NOT claim to test real timer expiry or event-loop IO.
    async def immediate(coroutine, timeout):
        assert timeout == 30
        return await coroutine
    monkeypatch.setattr(asyncio, 'wait_for', immediate)
    monkeypatch.setattr(asyncio, 'run', source_controls.run_stub)


@pytest.mark.parametrize('revoke', ['source', 'hebrew', 'media', 'boundary', 'cache'])
def test_each_external_stage_rechecks_current_publication_authority(db, media, monkeypatch, revoke):
    module, _, _, _ = media
    row = owner.claimed(db, media, long=True)
    def send(method, fields, asset=None):
        if revoke == 'source': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
        if revoke == 'hebrew': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
        if revoke == 'media': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED', 'false')
        if revoke == 'boundary': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', '2026-10-22T15:00:01Z')
        if revoke == 'cache':
            import trump_truth_translation as translation
            with db.get_db_connection() as conn:
                conn.execute('DELETE FROM scanner_settings WHERE key=?', (translation.cache_key(row),))
        return {'message_id': 123}
    sender = Mock(side_effect=send); monkeypatch.setattr(module, '_send', sender)
    result = module.dispatch(row, {'telegram_enabled': True}, owner.AT)
    assert sender.call_count == 1, 'A known media ACK cannot authorize a newly revoked text send'
    assert json.loads(result)['terminal'] is True
    assert module._receipt(row)['media_message_id'] == 123


def ready_row(db, media):
    module, _, _, _ = media
    row = owner.claimed(db, media, long=True)
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=? WHERE id=?', (module.READY, owner.AT.isoformat(), row['id']))
    row['status'] = module.READY
    row['next_attempt_at'] = owner.AT.isoformat()
    return row


def test_actual_shared_engine_claims_media_ready_and_tracks_both_acks_without_ai(db, media, monkeypatch):
    import scanner_engine
    import stock_scanner
    import trump_truth_translation as translation
    module, _, _, _ = media
    row = ready_row(db, media)
    never = Mock(side_effect=AssertionError('No generation or generic text fallback on media dispatch'))
    monkeypatch.setattr(translation, 'local_json', never)
    monkeypatch.setattr(translation, 'translate', never)
    monkeypatch.setattr(stock_scanner, 'send_telegram', never)
    sender = Mock(side_effect=[{'message_id': 123}, {'message_id': 124}])
    monkeypatch.setattr(module, '_send', sender)
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert [call.args[0] for call in sender.call_args_list] == ['sendPhoto', 'sendMessage']
    receipt = module._receipt(row)
    assert receipt['status'] == 'complete' and receipt['text_message_id'] == 124
    with db.get_db_connection() as conn:
        saved = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone())
    assert saved['status'] == 'sent' and saved['message'] == row['message']
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert sender.call_count == 2
    never.assert_not_called()


@pytest.mark.parametrize('stage', ['media', 'text'])
def test_actual_engine_unknown_ack_is_terminal_without_generic_fallback(db, media, monkeypatch, stage):
    import scanner_engine
    import stock_scanner
    module, _, _, _ = media
    row = ready_row(db, media)
    fallback = Mock(side_effect=AssertionError('No text fallback after uncertain media'))
    monkeypatch.setattr(stock_scanner, 'send_telegram', fallback)
    sender = Mock(side_effect=[{'unknown': True}] if stage == 'media' else [{'message_id': 123}, {'unknown': True}])
    monkeypatch.setattr(module, '_send', sender)
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    with db.get_db_connection() as conn:
        saved = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone())
    assert saved['status'] == 'failed'
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert sender.call_count == (1 if stage == 'media' else 2)
    fallback.assert_not_called()


def test_actual_engine_retry_keeps_known_media_ack_and_only_retries_text(db, media, monkeypatch):
    import scanner_engine
    module, _, _, _ = media
    row = ready_row(db, media)
    sender = Mock(side_effect=[{'message_id': 123}, {'retry': True, 'reason': 'rate_limited'}, {'message_id': 124}])
    monkeypatch.setattr(module, '_send', sender)
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    with db.get_db_connection() as conn:
        saved = conn.execute('SELECT status FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone()
        assert saved['status'] == module.RETRY
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (row['id'],))
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert [call.args[0] for call in sender.call_args_list] == ['sendPhoto', 'sendMessage', 'sendMessage']
    assert module._receipt(row)['media_message_id'] == 123


def test_actual_engine_expired_uncertain_lease_after_crash_never_resends(db, media, monkeypatch):
    import scanner_engine
    module, _, _, _ = media
    row = ready_row(db, media)
    sender = Mock(side_effect=KeyboardInterrupt('Synthetic crash at external send boundary'))
    monkeypatch.setattr(module, '_send', sender)
    with pytest.raises(KeyboardInterrupt): scanner_engine.process_telegram_outbox()
    assert module._receipt(row)['status'] == 'media_sending'
    with db.get_db_connection() as conn:
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (row['id'],))
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    with db.get_db_connection() as conn:
        saved = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone())
    assert saved['status'] == 'failed' and 'unknown' in saved['last_error']
    assert sender.call_count == 1


def test_long_delivery_cannot_claim_complete_without_known_text_ack(db, media, monkeypatch):
    module, _, _, _ = media
    row = owner.claimed(db, media, long=True)
    sender = Mock(side_effect=[{'message_id': 123}, {'message_id': 124}]); monkeypatch.setattr(module, '_send', sender)
    assert module.dispatch(row, {'telegram_enabled': True}, owner.AT) == 'sent'
    value = module._receipt(row); value['text_message_id'] = None
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?', (module.wire(value), module.receipt_key(row)))
    result = module.dispatch(row, {'telegram_enabled': True}, owner.AT)
    assert result != 'sent' and json.loads(result)['terminal'] is True
    assert sender.call_count == 2, 'Malformed complete receipt is manual review, not a new send'
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET status=?,sent_at=? WHERE id=?', ('sent', owner.AT.isoformat(), row['id']))
        published = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone())
    envelope = json.loads(row['message'])
    assert module.public_media(published, envelope, owner.AT)['status'] != 'available'
    with pytest.raises(ValueError):
        module.read_public_asset(envelope['item']['media']['sha256'], published, envelope, owner.AT)


def test_identical_file_later_unpublished_receipt_cannot_replace_published_asset_index(db, media, monkeypatch):
    module, _, message, _ = media
    sender = Mock(side_effect=[{'message_id': 123}, {'message_id': 124}])
    monkeypatch.setattr(module, '_send', sender)
    first = owner.claimed(db, media)
    assert module.dispatch(first, {'telegram_enabled': True}, owner.AT) == 'sent'
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_telegram_outbox SET status=?,sent_at=? WHERE id=?',
                     ('sent', owner.AT.isoformat(), first['id']))
        published = dict(conn.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (first['id'],)).fetchone())
        first_token = module.public_media(published, json.loads(first['message']), owner.AT, conn=conn)['asset_token']
    message.id += 1
    message.entities[0].url = 'https://truthsocial.com/@realDonaldTrump/117500000000000002'
    second = owner.claimed(db, media)
    assert module.dispatch(second, {'telegram_enabled': True}, owner.AT) == 'sent'
    first_receipt, second_receipt = module._receipt(first), module._receipt(second)
    assert first_receipt['asset_sha256'] == second_receipt['asset_sha256']
    second_token = module._public_token(second_receipt['binding'], second_receipt['asset_sha256'])
    assert first_token != second_token, 'Public token is publication-bound, not just file-content-bound'
    with db.get_db_connection() as conn:
        assert conn.execute('SELECT status FROM scanner_telegram_outbox WHERE id=?', (second['id'],)).fetchone()['status'] == module.SENDING
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        assert module.public_asset(first_token, conn, owner.AT) == (b'\xff\xd8\xff\xd9', 'image/jpeg')
        with pytest.raises(ValueError):
            module.public_asset(second_token, conn, owner.AT)
    assert sender.call_count == 2


@pytest.mark.parametrize('mode,owner_uid,accepted', [
    (0o700, 10001, True), (0o750, 10001, True), (0o755, 10001, True),
    (0o775, 10001, False), (0o777, 10001, False), (0o702, 10001, False),
    (0o755, 0, False), (stat.S_IFLNK | 0o755, 10001, False),
    (stat.S_IFREG | 0o600, 10001, False),
])
def test_real_posix_session_parent_guard_allows_owned_readable_directory_but_never_shared_write(media, mode, owner_uid, accepted):
    module = media[0]
    # Execute the actual POSIX function body against immutable metadata doubles,
    # without globally changing os.name (which would change pathlib on Windows).
    ns = {'stat': stat, 'os': SimpleNamespace(name='posix', geteuid=lambda: 10001)}
    exec(compile(ast.parse(inspect.getsource(module._session_parent)), '<actual POSIX session parent>', 'exec'), ns)
    full_mode = mode if stat.S_IFMT(mode) else stat.S_IFDIR | mode
    info = SimpleNamespace(st_mode=full_mode, st_uid=owner_uid)
    path = SimpleNamespace(lstat=lambda: info)
    if accepted:
        assert ns['_session_parent'](path) is info
    else:
        with pytest.raises(ValueError): ns['_session_parent'](path)


@pytest.mark.parametrize('directory,mode,accepted', [
    (False, 0o600, True), (False, 0o644, False),
    (True, 0o700, True), (True, 0o750, False), (True, 0o755, False),
])
def test_session_parent_relaxation_does_not_relax_private_session_file_or_media_cache(media, directory, mode, accepted):
    module = media[0]
    ns = {'stat': stat, 'os': SimpleNamespace(name='posix', geteuid=lambda: 10001)}
    exec(compile(ast.parse(inspect.getsource(module._secure)), '<actual strict private guard>', 'exec'), ns)
    info = SimpleNamespace(st_mode=(stat.S_IFDIR if directory else stat.S_IFREG) | mode, st_uid=10001)
    path = SimpleNamespace(lstat=lambda: info)
    if accepted:
        assert ns['_secure'](path, directory) is info
    else:
        with pytest.raises(ValueError): ns['_secure'](path, directory)


def test_unsafe_session_parent_returns_unavailable_before_any_download(media, monkeypatch):
    from unittest.mock import AsyncMock
    module, posts, message, _ = media
    checks = Mock(side_effect=ValueError('media_session_untrusted'))
    monkeypatch.setattr(module, '_session_parent', checks)
    client = SimpleNamespace(download_media=AsyncMock())
    item = asyncio.run(module.capture(client, message, posts.extract(message, owner.AT)[0], owner.AT))
    assert item['media']['status'] == 'unavailable'
    checks.assert_called_once()
    client.download_media.assert_not_called()


def test_expired_batch_claim_must_not_begin_any_external_media_stage(db, media, monkeypatch):
    import scanner_engine
    module = media[0]
    ready = ready_row(db, media)
    claimed = scanner_engine._claim_telegram_outbox()
    assert len(claimed) == 1 and claimed[0]['id'] == ready['id']
    with db.get_db_connection() as conn:
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (ready['id'],))
    sender = Mock(return_value={'message_id': 123})
    monkeypatch.setattr(module, '_send', sender)
    result = module.dispatch(claimed[0], {'telegram_enabled': True}, owner.AT)
    assert result != 'sent' and json.loads(result)['terminal'] is True
    sender.assert_not_called()


@pytest.mark.parametrize('stage', ['before_first', 'after_media_ack'])
def test_replaced_claim_deadline_never_authorizes_another_external_stage(db, media, monkeypatch, stage):
    import scanner_engine
    module = media[0]
    ready = ready_row(db, media)
    row = scanner_engine._claim_telegram_outbox()[0]
    changed = (owner.AT + timedelta(minutes=10)).isoformat()
    def replace_deadline():
        with db.get_db_connection() as conn:
            conn.execute('UPDATE scanner_telegram_outbox SET next_attempt_at=? WHERE id=?', (changed, ready['id']))
    def send(*a, **kw):
        replace_deadline()
        return {'message_id': 123}
    if stage == 'before_first': replace_deadline()
    sender = Mock(side_effect=send); monkeypatch.setattr(module, '_send', sender)
    result = module.dispatch(row, {'telegram_enabled': True}, owner.AT)
    assert result != 'sent' and json.loads(result)['terminal'] is True
    assert sender.call_count == (0 if stage == 'before_first' else 1)
