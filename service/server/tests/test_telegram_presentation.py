"""Wire-format checks only: no Telegram requests, AI or production data."""
import re
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telegram_presentation import telegram_text, utf16_length, RLM, LRI, PDI


def visible(text):
    return re.sub('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', text)


@pytest.mark.parametrize('text,span', [
    ('סימול: BRK.B', 'BRK.B'),
    ('פעולה: SELL — שורט מדומה', 'SELL'),
    ('חברה: First Solar (FSLR)', 'First Solar (FSLR)'),
    ('תוצאה: -2.35% ברוטו', '-2.35%'),
    ('תוצאה: +1.25% נטו', '+1.25%'),
    ('יחס RR: 2.00R', 'RR: 2.00R'),
    ('פורסם: 28/09/2026 14:07 (שעון ישראל)', '28/09/2026 14:07'),
    ('טווח: 1–5 ימים', '1–5'),
    ('בקרת TP/SL ממשיכה בנפרד', 'TP/SL'),
    ('📰 הבנק Fed הודיע על החלטה', 'Fed'),
    ('מצב: recovery_uncertain — חסום', 'recovery_uncertain'),
    ('קישור: https://t.me/+Example?x=1&y=2', 'https://t.me/+Example?x=1&y=2'),
])
def test_mixed_paragraph_is_rtl_with_intact_ltr_span(text, span):
    rendered = telegram_text(text)
    assert rendered.startswith(RLM)
    assert LRI + span + PDI in rendered
    assert visible(rendered) == text
    assert telegram_text(rendered) == rendered


def test_every_hebrew_line_is_guarded_not_just_first_line_of_paragraph():
    text = 'AI-Trader\n\n📰 חדשות NVDA\nהחברה Apple הודיעה\nhttps://t.me/+Example'
    lines = telegram_text(text).splitlines()
    assert lines[0] == 'AI-Trader' and lines[1] == ''
    assert lines[2].startswith(RLM) and lines[3].startswith(RLM)
    assert lines[4] == 'https://t.me/+Example'
    assert visible('\n'.join(lines)) == text


def test_hebrew_joining_hyphen_not_presented_as_negative_number():
    assert 'ב-' + LRI + '0.25%' + PDI in telegram_text('הריבית עלתה ב-0.25%')
    assert LRI + '-0.25%' + PDI in telegram_text('תוצאה: -0.25%')


def test_untrusted_overrides_removed_existing_isolates_not_nested_emoji_intact():
    text = '\u202eסימול: \u2066NVDA\u2069\u202c\nמשפחה 👨‍👩‍👧‍👦'
    rendered = telegram_text(text)
    assert '\u202e' not in rendered and '\u202c' not in rendered
    assert rendered.count(LRI) == rendered.count(PDI) == 1
    assert '👨‍👩‍👧‍👦' in rendered
    assert visible(rendered) == visible(text)
    assert telegram_text(rendered) == rendered


@pytest.mark.parametrize('limit', [1024, 4096])
def test_limits_count_controls_and_emoji_preserve_tail_and_balance(limit):
    text = ('חדשות 📰 NVDA +2.34%\n' * 500) + '\n📣 הצטרפות:\nhttps://t.me/+Example'
    rendered = telegram_text(text, limit=limit)
    assert utf16_length(rendered) <= limit
    assert rendered.count(LRI) == rendered.count(PDI)
    assert rendered.endswith('https://t.me/+Example')
    assert '…' in rendered
    assert telegram_text(rendered, limit=limit) == rendered


def test_exact_budget_english_and_punctuation_only_unchanged():
    for text in ('A' * 4096, 'AI-Trader Admin\nStatus: ok\nHTTP: 200', '─' * 18):
        assert telegram_text(text) == text


def test_plain_text_not_html_markdown_and_hebrew_combining_marks_preserved():
    text = 'שָׁלוֹם <NVDA> & _AAPL_\nתנאי: RR > 2'
    assert visible(telegram_text(text)) == text


def test_overflow_never_turns_partial_price_or_url_into_different_value():
    for value in ('123456789.99%', 'https://t.me/+ExampleLink'):
        rendered = telegram_text('מחיר: ' + value, limit=15)
        assert value not in rendered
        assert '123' not in rendered and 'https' not in rendered
        assert rendered.endswith('…')
        assert rendered.count(LRI) == rendered.count(PDI)


def test_public_wire_format_after_source_cleanup_preserves_topic_and_community():
    import stock_scanner
    session = Mock()
    text = ('📰 רמסדן מהבנק Bank of England\n\nלפי ערוץ Telegram @financialjuice, '
            'הריבית עלתה ב-0.25%.\n\nפורסם: 28/09/2026 14:07 (שעון ישראל)')
    with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'mock', 'TELEGRAM_CHAT_ID': 'public-test',
            'TELEGRAM_MARKET_NEWS_THREAD_ID': '123', 'TELEGRAM_COMMUNITY_URL': 'https://t.me/+Example'}), \
            patch.object(stock_scanner.requests, 'Session', return_value=session):
        assert stock_scanner.send_telegram(text, {'telegram_enabled': True}, 'market_news') == 'sent'
    payload = session.post.call_args.kwargs['data']
    assert payload['chat_id'] == 'public-test' and payload['message_thread_id'] == 123
    assert payload['text'].startswith(RLM)
    assert 'financialjuice' not in payload['text']
    assert 'https://t.me/+Example' in payload['text']
    assert LRI + '0.25%.' + PDI in payload['text'] or LRI + '-0.25%.' + PDI in payload['text']
    assert 'parse_mode' not in payload


def test_admin_wire_format_preserves_original_timestamp_and_private_destination():
    import ai_operations
    row = dict(message='AI-Trader Admin\nתקלה: invalid_json\nניטור TP/SL נמשך',
               created_at='2026-09-30T12:02:00Z', dedupe_key='fixture', attempts=1)
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = row
    context = Mock()
    context.__enter__ = Mock(return_value=connection)
    context.__exit__ = Mock(return_value=False)
    response = Mock()
    response.json.return_value = {'ok': True, 'result': {'message_id': 1}}
    with patch('database.get_db_connection', return_value=context), \
            patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'mock', 'TELEGRAM_ADMIN_CHAT_ID': 'private-test',
                                      'TELEGRAM_CHAT_ID': 'public-test'}), \
            patch.object(ai_operations.requests, 'post', return_value=response) as post:
        ai_operations.send_one()
    payload = post.call_args.kwargs['json']
    assert payload['chat_id'] == 'private-test'
    assert RLM + 'תקלה: ' + LRI + 'invalid_json' + PDI in payload['text']
    assert payload['text'].splitlines()[-1] == 'Timestamp: 30/09/2026 15:02 (Israel)'
    assert row['message'].startswith('AI-Trader Admin\nתקלה: invalid_json')
