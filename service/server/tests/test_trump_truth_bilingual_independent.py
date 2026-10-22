"""Independent bilingual goal controls; only synthetic retained relay content."""
import pytest
import importlib
import re
import copy
import json
import ast
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import test_trump_truth_media as media_owner
import test_trump_truth_media_objective_independent as media_controls

media = media_owner.media
db = media_owner.db
synchronous_mock_capture = media_controls.synchronous_mock_capture

import test_trump_truth_posts_independent as source
import trump_truth_posts as posts
import trump_truth_translation as translation

no_external_io = source.no_external_io
enabled = source.enabled
SOURCE = 'I will not approve a 5% increase unless Congress agrees.'
HEBREW = 'לא אאשר עלייה של 5% אלא אם הקונגרס יסכים.'


def item(body=SOURCE):
    value = source.item(source.post(body))
    assert value is not None
    return value


def presentation(value, cache):
    # The approved design adds an independently default-OFF presenter instead
    # of changing legacy posts.render for old flag-OFF rows. The initial RED
    # captured the pre-feature goal gap; final controls exercise the new API.
    bilingual = importlib.import_module('trump_truth_bilingual')
    return '\n\n'.join(visible_wire(part['text']) for part in bilingual.plan(value, cache, has_asset=False))


def test_complete_hebrew_and_retained_english_are_both_in_default_telegram_presentation(enabled):
    value = item()
    text = presentation(value, {'status': 'translated', 'text_he': HEBREW})
    assert HEBREW in text
    assert SOURCE in text, 'New bilingual goal requires the actual source excerpt, not only Hebrew'
    assert text.count(SOURCE) == text.count(HEBREW) == 1
    assert value['truth_url'] in text and 'לא אומת' in text
    assert 'full original text' not in text.lower()


def test_unavailable_translation_still_shows_actual_english_not_only_a_link(enabled):
    value = item()
    text = presentation(value, {'status': 'unavailable', 'text_he': ''})
    assert SOURCE in text, 'An unavailable translation must not erase the retained English'
    assert HEBREW not in text
    assert 'אינו זמין' in text and value['truth_url'] in text


@pytest.mark.parametrize('body', [
    'RT https://truthsocial.com/@OtherAccount/117500000000000999',
    '🦅 RT: https://example.invalid/quoted',
    'This post contains the following media: image',
])
def test_link_only_or_media_boilerplate_is_never_fabricated_as_original_english(enabled, body):
    value = item(body)
    assert translation.source_text(value) == ''
    status = 'media_only' if value['has_media'] else 'link_only'
    text = posts.render(value, {'status': status, 'text_he': ''})
    assert 'This post contains the following media:' not in text
    assert '[קישור בגוף הפוסט' not in text
    assert 'https://example.invalid' not in text
    assert value['truth_url'] in text


def visible_wire(text):
    # Strip only deterministic presentation controls for whole-content equality;
    # never punctuation, content, numbers or source-provided qualifiers.
    return re.sub('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', text)


@pytest.mark.parametrize('has_asset', [False, True])
def test_short_plan_contains_both_complete_languages_without_extra_generation(enabled, has_asset):
    bilingual = importlib.import_module('trump_truth_bilingual')
    value = item()
    if has_asset: value['media'] = {'kind': 'photo'}  # Pure plan only; not an acquisition/descriptor proof.
    stages = bilingual.plan(value, {'status': 'translated', 'text_he': HEBREW}, has_asset=has_asset)
    assert isinstance(stages, list) and len(stages) == 1
    stage = stages[0]
    text = visible_wire(stage['text'])
    assert SOURCE in text and HEBREW in text
    assert text.count(SOURCE) == text.count(HEBREW) == 1
    assert value['truth_url'] in text
    assert len(stage['text'].encode('utf-16-le'))//2 <= (1024 if has_asset else 4096)


@pytest.mark.parametrize('has_asset,expected_parts', [(False, 2), (True, 3)])
def test_long_bilingual_plan_preserves_complete_approved_text_and_source_as_tracked_parts(enabled, has_asset, expected_parts):
    bilingual = importlib.import_module('trump_truth_bilingual')
    original = 'A'*1500 + ' Do not agree without this final condition.'
    approved = 'א'*2300 + ' לא להסכים ללא התנאי האחרון.'
    value = item(original)
    if has_asset: value['media'] = {'kind': 'photo'}
    assert translation.source_text(value) == original
    stages = bilingual.plan(value, {'status': 'translated', 'text_he': approved}, has_asset=has_asset)
    assert isinstance(stages, list) and len(stages) == expected_parts
    texts = [visible_wire(stage['text']) for stage in stages]
    assert sum(original in text for text in texts) == 1
    assert sum(approved in text for text in texts) == 1
    assert len({stage['stage'] for stage in stages}) == len(stages)
    for stage in stages:
        assert len(stage['text'].encode('utf-16-le'))//2 <= (1024 if stage['method'] != 'sendMessage' else 4096)
        assert '…' not in stage['text'], 'No clipping marker may substitute a whole approved language part'


@pytest.fixture
def bilingual(db, media, monkeypatch):
    module = importlib.import_module('trump_truth_bilingual')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED', 'true')
    monkeypatch.setattr(module, '_now', lambda: media_owner.AT)
    return module


def ready(db, media, bilingual, *, asset=False, long=True):
    _, truth, message, _ = media
    original = ('A'*1500 + ' Do not agree without this final condition.') if long else SOURCE
    approved = ('א'*2300 + ' לא להסכים ללא התנאי האחרון.') if long else HEBREW
    message.message = truth.HEADER+'\n'+original+'\n'+truth.LABEL
    message.entities[0].offset = len(message.message[:message.message.rindex(truth.LABEL)].encode('utf-16-le'))//2
    if asset:
        value, _ = media_owner.captured(media)
    else:
        message.media = None; message.photo = None
        value = truth.extract(message, media_owner.AT)[0]
    assert truth.ingest([value], media_owner.AT)['inserted'] == 1
    completion = Mock(side_effect=lambda system, payload, schema: {'text_he': approved} if 'text_he' in schema['properties'] else
        {'faithful': True, 'fluent_hebrew': True, 'complete': True, 'unsupported_claims': False})
    assert translation.prepare(at=media_owner.AT, completion=completion)['prepared'] == 1
    assert completion.call_count == 2
    with db.get_db_connection() as conn:
        row = dict(conn.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id DESC LIMIT 1').fetchone())
    assert row['status'] == bilingual.READY
    return row, original, approved


@pytest.mark.parametrize('asset,parts', [(False, 2), (True, 3)])
def test_real_shared_dispatch_json_roundtrip_retries_only_unacked_complete_language_parts(db, media, bilingual, monkeypatch, asset, parts):
    import scanner_engine
    row, original, approved = ready(db, media, bilingual, asset=asset)
    expected_parts = bilingual._current(row, media_owner.AT)[1]
    replies = [{'message_id': 100+i} for i in range(parts-1)] + [{'retry': True, 'reason': 'rate_limited'}, {'message_id': 200}]
    sender = Mock(side_effect=replies); monkeypatch.setattr(media[0], '_send', sender)
    monkeypatch.setattr(translation, 'local_json', lambda *a: pytest.fail('Inference on retry'))
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    value = bilingual.receipt(row)
    assert len(value['acks']) == parts-1 and value['status'] == 'retry'
    with db.get_db_connection() as conn:
        raw = conn.execute('SELECT value_json FROM scanner_settings WHERE key=?', (bilingual.receipt_key(row),)).fetchone()['value_json']
        assert json.loads(raw) == value, 'Sorted JSON must preserve acknowledged-prefix semantics'
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (row['id'],))
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert sender.call_count == parts+1
    sent_texts = [call.args[1].get('text', call.args[1].get('caption', '')) for call in sender.call_args_list]
    assert sent_texts == [part['text'] for part in expected_parts[:-1]] + [expected_parts[-1]['text']]*2
    assert sum(approved in visible_wire(text) for text in sent_texts) == 1
    assert original in visible_wire(sent_texts[-1])
    assert bilingual.receipt(row)['status'] == 'complete'
    assert scanner_engine.process_telegram_outbox()['sent'] == 0 and sender.call_count == parts+1


@pytest.mark.parametrize('failure_stage', [0, 1, 2])
def test_ambiguous_ack_at_any_stage_is_terminal_without_replaying_known_parts(db, media, bilingual, monkeypatch, failure_stage):
    import scanner_engine
    row, _, _ = ready(db, media, bilingual, asset=True)
    sender = Mock(side_effect=[{'message_id': 100+i} for i in range(failure_stage)] + [{'unknown': True}])
    monkeypatch.setattr(media[0], '_send', sender)
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    receipt = bilingual.receipt(row)
    assert receipt['status'] == 'unknown' and len(receipt['acks']) == failure_stage
    assert scanner_engine.process_telegram_outbox()['sent'] == 0 and sender.call_count == failure_stage+1


@pytest.mark.parametrize('revoke', ['source', 'bilingual', 'boundary', 'cache', 'lease'])
def test_every_additional_language_stage_rechecks_current_authority_and_exact_claim(db, media, bilingual, monkeypatch, revoke):
    import scanner_engine
    row, _, _ = ready(db, media, bilingual, asset=True)
    claimed = scanner_engine._claim_telegram_outbox()[0]
    def send(*args, **kwargs):
        if revoke == 'source': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'false')
        if revoke == 'bilingual': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED', 'false')
        if revoke == 'boundary': monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', '2026-10-23T15:00:00Z')
        if revoke in ('cache', 'lease'):
            with db.get_db_connection() as conn:
                if revoke == 'cache': conn.execute('DELETE FROM scanner_settings WHERE key=?', (translation.cache_key(row),))
                else: conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (row['id'],))
        return {'message_id': 100}
    sender = Mock(side_effect=send); monkeypatch.setattr(media[0], '_send', sender)
    result = bilingual.dispatch(claimed, {'telegram_enabled': True}, media_owner.AT)
    assert result != 'sent' and json.loads(result)['terminal'] is True
    assert sender.call_count == 1


def test_crash_after_known_parts_and_before_final_ack_never_resends_on_expired_claim(db, media, bilingual, monkeypatch):
    import scanner_engine
    row, _, _ = ready(db, media, bilingual, asset=True)
    sender = Mock(side_effect=[{'message_id': 100}, {'message_id': 101}, KeyboardInterrupt('Synthetic external-stage crash')])
    monkeypatch.setattr(media[0], '_send', sender)
    with pytest.raises(KeyboardInterrupt): scanner_engine.process_telegram_outbox()
    value = bilingual.receipt(row)
    assert value['status'] == 'sending' and len(value['acks']) == 2
    with db.get_db_connection() as conn:
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (row['id'],))
    assert scanner_engine.process_telegram_outbox()['sent'] == 0 and sender.call_count == 3


@pytest.mark.parametrize('damage', ['nonprefix', 'active', 'missing_part', 'boolean_ack'])
def test_malicious_receipt_cannot_skip_or_misidentify_a_language_stage(db, media, bilingual, monkeypatch, damage):
    import scanner_engine
    row, _, _ = ready(db, media, bilingual, asset=True)
    sender = Mock(side_effect=[{'message_id': 100}, {'retry': True, 'reason': 'rate_limited'}]); monkeypatch.setattr(media[0], '_send', sender)
    assert scanner_engine.process_telegram_outbox()['failed'] == 1
    value = copy.deepcopy(bilingual.receipt(row))
    if damage == 'nonprefix': value['acks'] = {'english': 100}
    if damage == 'active': value['active_stage'] = 'english'
    if damage == 'missing_part': value['status'] = 'complete'; value['active_stage'] = None
    if damage == 'boolean_ack': value['acks']['media'] = True
    with db.get_db_connection() as conn:
        conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?', (media[0].wire(value), bilingual.receipt_key(row)))
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (row['id'],))
    assert scanner_engine.process_telegram_outbox()['failed'] == 1 and sender.call_count == 2


@pytest.mark.parametrize('state', ['trump_bilingual_pending', 'trump_bilingual_preparing',
    'trump_bilingual_ready', 'trump_bilingual_retry', 'trump_bilingual_sending'])
def test_committed_actual_previous_selector_ignores_all_new_bilingual_states(db, media, bilingual, state):
    import scanner_engine
    row, _, _ = ready(db, media, bilingual)
    with db.get_db_connection() as conn:
        conn.execute("UPDATE scanner_telegram_outbox SET status=?,next_attempt_at='2000-01-01T00:00:00Z' WHERE id=?", (state, row['id']))
    path = Path(__file__).with_name('fixtures') / 'trump_truth_previous2d_outbox.py'
    fixture = {}; exec(compile(path.read_bytes(), str(path), 'exec'), fixture)
    assert fixture['BASE_SHA'] == '2d72146ca70afb27329492fc856987282fc1f32e'
    assert hashlib.sha256(fixture['SOURCE'].encode()).hexdigest() == fixture['FUNCTION_SHA256'] == 'c7b046484e6681070c8959f6ebb0d67eadad87becda78e3e312deda415e5fe42'
    ns = dict(Any=Any, datetime=datetime, timedelta=timedelta, now_z=lambda: media_owner.AT.isoformat(),
        parse_time=scanner_engine.parse_time, get_db_connection=db.get_db_connection,
        begin_write_transaction=db.begin_write_transaction, using_postgres=lambda: False)
    exec(compile(ast.Module(body=[ast.parse(fixture['SOURCE']).body[0]], type_ignores=[]), '<actual old2d selector>', 'exec'), ns)
    assert ns['_claim_telegram_outbox']() == []
    with db.get_db_connection() as conn:
        actual = conn.execute('SELECT status,message FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone()
    assert actual['status'] == state and actual['message'] == row['message']


def test_old_valid_complete_media_receipt_cannot_skip_new_language_parts(db, media, bilingual, monkeypatch):
    import scanner_engine
    row, _, _ = ready(db, media, bilingual, asset=False)
    module = media[0]
    old = {'version': module.VERSION, 'binding': module._receipt_binding(row), 'destination': 'd'*64,
        'asset_sha256': 'a'*64, 'text_sha256': 'b'*64, 'text_required': False,
        'media_message_id': 100, 'text_message_id': None, 'status': 'complete'}
    assert module._checked_receipt(row, old) == old
    with db.get_db_connection() as conn:
        conn.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
            (module.receipt_key(row), module.wire(old), media_owner.AT.isoformat()))
    sender = Mock(side_effect=[{'message_id': 101}, {'message_id': 102}]); monkeypatch.setattr(module, '_send', sender)
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert sender.call_count == 2 and bilingual.receipt(row)['version'] == bilingual.RECEIPT_VERSION


@pytest.mark.parametrize('missing', ['TELEGRAM_TRUMP_TRUTH_ENABLED', 'TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED'])
def test_requested_bilingual_without_base_authority_cannot_silently_downgrade(db, media, bilingual, monkeypatch, missing):
    value = media[1].extract(media[2], media_owner.AT)[0]
    assert value is not None
    monkeypatch.setenv(missing, 'false')
    assert bilingual.enabled() is False
    assert posts.ingest([value], media_owner.AT)['inserted'] == 0
