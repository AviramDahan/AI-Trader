"""Independent final Telegram-wire checks, entirely synthetic and mocked."""
import json
import re
from unittest.mock import Mock

import pytest

import test_trump_truth_translation_independent as prepare_tests
from telegram_presentation import telegram_text, utf16_length, LRI, PDI

no_external_io = prepare_tests.no_external_io
enabled = prepare_tests.enabled
local_db = prepare_tests.local_db
hebrew = prepare_tests.hebrew
NOW = prepare_tests.NOW
URL = prepare_tests.original.URL
RELAY = 'https://t.me/' + prepare_tests.original.CHANNEL + '/100'


def visible(value):
    return re.sub('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', value)


def transport(monkeypatch, *, response_error=None):
    import stock_scanner
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-token-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100-synthetic')
    monkeypatch.setenv('TELEGRAM_TRADING_THREAD_ID', '777')
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    session = Mock()
    if response_error:
        session.post.side_effect = response_error
    else:
        session.post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 42}}
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    return session


def prepare(db, source, translated):
    import trump_truth_translation as translation
    row = prepare_tests.enqueue(db, source)
    model = prepare_tests.good_completion(translated)
    assert translation.prepare(at=NOW, completion=model)['prepared'] == 1
    assert model.call_count == 2
    return row


def test_real_final_send_never_clips_a_validated_hebrew_translation(hebrew, monkeypatch):
    # The original plain-render check passes at2749 UTF16 units. Bidi insertion
    # expands this accepted2399-unit draft beyond4096 in the old final sender.
    translated = ('א1 ' * 800).strip()
    row = prepare(hebrew, '1 ' * 800, translated)
    before_cache = prepare_tests.cache(hebrew, row)
    session = transport(monkeypatch)
    assert hebrew.engine.process_telegram_outbox()['sent'] == 1
    text = session.post.call_args.kwargs['data']['text']
    shown = visible(text)
    assert utf16_length(text) <= 4096
    assert text.count(LRI) == text.count(PDI)
    assert URL in text and RELAY in text
    if translated in shown:
        assert shown.count('א1') == 800
        assert '…' not in shown
    else:
        assert 'התרגום לעברית אינו זמין' in shown
        assert 'א1' not in shown, 'Never send a clipped partial translation as the translated post'
    assert prepare_tests.rows(hebrew)[0]['message'] == row['message']
    assert prepare_tests.cache(hebrew, row) == before_cache


@pytest.mark.parametrize('translated', [
    'שלום לכל הקוראים. זהו קטע סינתטי בלבד.',
    'הבטחה מותנית: אם הקונגרס יסכים, לא נאשר תוספת של 5%.',
    'משפחה 👨‍👩‍👧‍👦 ותמונה 🦅 — ללא טענה נוספת.',
])
def test_normal_whole_content_and_attribution_survive_actual_send(hebrew, monkeypatch, translated):
    source = 'Only if Congress agrees, no increase of 5%.' if '5%' in translated else 'A synthetic personal statement.'
    prepare(hebrew, source, translated)
    session = transport(monkeypatch)
    assert hebrew.engine.process_telegram_outbox()['sent'] == 1
    payload = session.post.call_args.kwargs['data']
    text = payload['text']; shown = visible(text)
    assert translated in shown and shown.count(translated) == 1
    assert 'טראמפ' in shown and 'תרגום' in shown
    assert 'לא אומת' in shown
    assert URL in text and RELAY in text
    assert payload['message_thread_id'] == 991 and 'parse_mode' not in payload
    assert utf16_length(text) <= 4096 and text.count(LRI) == text.count(PDI)
    assert telegram_text(text) == text
    for private_key in ('"item"', '"fence"', '"presentation"', '"binding"', '"attempts"'):
        assert private_key not in shown


@pytest.mark.parametrize('status', ['unavailable', 'media_only'])
def test_truthful_nontranslation_modes_keep_links_without_source_body(hebrew, monkeypatch, status):
    import trump_truth_translation as translation
    if status == 'media_only':
        row = prepare_tests.enqueue(hebrew, '', media=True)
        assert translation.prepare(at=NOW, completion=Mock(side_effect=AssertionError('No caption generation')))['prepared'] == 1
    else:
        row = prepare_tests.enqueue(hebrew, 'Original source-only body must not masquerade as Hebrew.')
        failed = Mock(side_effect=ValueError('Synthetic unavailable model'))
        translation.prepare(at=NOW, completion=failed)
        translation.prepare(at=NOW + prepare_tests.timedelta(seconds=61), completion=failed)
        with hebrew.db.get_db_connection() as c:
            c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    session = transport(monkeypatch)
    assert hebrew.engine.process_telegram_outbox()['sent'] == 1
    text = visible(session.post.call_args.kwargs['data']['text'])
    assert URL in text and RELAY in text and 'לא אומת' in text
    assert 'Original source-only' not in text
    assert ('אינו זמין' if status == 'unavailable' else 'אין תמלול') in text
    assert prepare_tests.rows(hebrew)[0]['message'] == row['message']


def test_final_wire_safety_does_not_change_dedupe_or_unknown_delivery_policy(hebrew, monkeypatch):
    import requests
    prepare(hebrew, '1 ' * 800, ('א1 ' * 800).strip())
    session = transport(monkeypatch, response_error=requests.ReadTimeout('Synthetic ambiguous acknowledgement'))
    assert hebrew.engine.process_telegram_outbox()['failed'] == 1
    assert prepare_tests.rows(hebrew)[0]['status'] == 'failed'
    assert hebrew.engine.process_telegram_outbox()['sent'] == 0
    assert session.post.call_count == 1
    assert hebrew.trump.ingest([prepare_tests.make_item(number=101)], NOW)['duplicates'] == 1


def test_hebrew_wire_preserves_repost_and_media_limitations(hebrew, monkeypatch):
    import trump_truth_translation as translation
    value = prepare_tests.make_item('RT A synthetic personal statement.', media=True)
    assert value['is_repost'] is True and value['has_media'] is True
    hebrew.trump.ingest([value], NOW)
    assert translation.prepare(at=NOW, completion=prepare_tests.good_completion('שיתוף מחדש של אמירה אישית סינתטית.'))['prepared'] == 1
    session = transport(monkeypatch)
    assert hebrew.engine.process_telegram_outbox()['sent'] == 1
    text = visible(session.post.call_args.kwargs['data']['text'])
    assert 'שיתוף מחדש' in text and 'המדיה לא הורדה' in text
    assert URL in text and RELAY in text


def test_original_mode_final_wire_is_still_source_language_not_fake_hebrew(local_db, monkeypatch):
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'false')
    body = 'A source-language synthetic non-economic statement.'
    prepare_tests.enqueue(local_db, body)
    session = transport(monkeypatch)
    assert local_db.engine.process_telegram_outbox()['sent'] == 1
    text = visible(session.post.call_args.kwargs['data']['text'])
    assert body in text and URL in text and RELAY in text
    assert 'תרגום AI' not in text


@pytest.mark.parametrize('body', [
    'RT https://example.invalid/post',
    'RT: https://example.invalid/post',
    'ReTruth https://example.invalid/post',
    'RT:\n\thttps://example.invalid/post\n',
    '🦅 RT https://example.invalid/post',
    'RT https://example.invalid/first\nhttps://example.invalid/second',
])
def test_link_only_repost_has_no_model_request_or_invented_media_caption(hebrew, monkeypatch, body):
    import trump_truth_translation as translation
    value = prepare_tests.make_item(body)
    assert value['is_repost'] is True and value['has_media'] is False
    assert hebrew.trump.ingest([value], NOW)['inserted'] == 1
    model = Mock(side_effect=AssertionError('A URL is not the quoted post body'))
    assert translation.prepare(at=NOW, completion=model)['prepared'] == 1
    model.assert_not_called()
    row = prepare_tests.rows(hebrew)[0]
    assert prepare_tests.cache(hebrew, row)['status'] == 'link_only'
    session = transport(monkeypatch)
    assert hebrew.engine.process_telegram_outbox()['sent'] == 1
    shown = visible(session.post.call_args.kwargs['data']['text'])
    assert 'שיתוף מחדש ללא גוף הפוסט' in shown
    assert 'תרגום AI' not in shown and 'אין תמלול' not in shown
    assert 'example.invalid' not in shown
    assert URL in shown and RELAY in shown and 'לא אומת' in shown
    assert hebrew.engine.process_telegram_outbox()['sent'] == 0
    assert session.post.call_count == 1


@pytest.mark.parametrize('body', [
    'RT A synthetic statement. https://example.invalid/post',
    'ReTruth I disagree with this statement. https://example.invalid/post',
])
def test_repost_with_real_prose_is_not_misclassified_as_link_only(hebrew, monkeypatch, body):
    import trump_truth_translation as translation
    value = prepare_tests.make_item(body)
    assert hebrew.trump.ingest([value], NOW)['inserted'] == 1
    model = prepare_tests.good_completion('שיתוף מחדש של אמירה סינתטית, ללא טענה נוספת.')
    assert translation.prepare(at=NOW, completion=model)['prepared'] == 1
    assert model.call_count == 2
    assert 'source_excerpt' in model.call_args_list[0].args[1]
    assert prepare_tests.cache(hebrew, prepare_tests.rows(hebrew)[0])['status'] == 'translated'
    session = transport(monkeypatch)
    assert hebrew.engine.process_telegram_outbox()['sent'] == 1
    shown = visible(session.post.call_args.kwargs['data']['text'])
    assert 'תרגום AI' in shown and 'שיתוף מחדש ללא גוף הפוסט' not in shown
    assert URL in shown and RELAY in shown


def test_link_only_classification_cannot_supply_missing_original_footer(enabled):
    value = prepare_tests.original.post('RT https://example.invalid/post')
    value.entities = []
    assert prepare_tests.original.item(value) is None


def test_link_only_source_cannot_render_a_source_bound_but_invented_cached_translation(hebrew):
    import trump_truth_translation as translation
    row = prepare_tests.enqueue(hebrew, 'RT https://example.invalid/post')
    envelope = json.loads(row['message'])
    assert translation.source_text(envelope['item']) == ''
    assert translation.prepare(at=NOW, completion=Mock(side_effect=AssertionError('No source body')))['prepared'] == 1
    assert prepare_tests.cache(hebrew, row)['status'] == 'link_only'
    value = dict(version=translation.VERSION, binding=translation.binding(row, envelope),
                 attempts=1, status='translated', text_he='זו אמירה שלא הופיעה בגוף הדיווח.')
    prepare_tests.save_cache(hebrew, row, value)
    assert prepare_tests.cache(hebrew, row) == value
    assert hebrew.trump.delivery_message(row, NOW) is None
