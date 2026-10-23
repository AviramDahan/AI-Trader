from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_events.runtime import message
from telegram_topics import with_news_community_link


def event(sources=None):
    return {'published_at': '2026-10-23T07:00:00Z', 'sources': sources or [
        {'url': 'https://www.sec.gov/Archives/edgar/data/123/filing.htm',
         'publisher': 'SEC', 'source_type': 'official/regulatory',
         'rights': 'approved', 'raw_metadata': {}}]}


def draft():
    return {'title_he': 'דיווח חדש', 'summary_he': 'החברה פרסמה נתונים לרבעון השלישי.',
            'interpretation_he': 'נתוני המקור אינם המלצת השקעה.'}


def test_authoritative_source_survives_canonical_render_and_actual_send_format():
    source = event()
    original = deepcopy(source)
    with patch.dict('os.environ', {'TELEGRAM_COMMUNITY_URL': 'https://t.me/+example'}):
        output = with_news_community_link(message(source, draft(), 'market_news', []), 'market_news')
    assert 'מקור: https://www.sec.gov/Archives/edgar/data/123/filing.htm' in output
    assert output.count('https://t.me/+example') == 1
    assert source == original


def test_approved_source_selection_prefers_official_not_relay_or_ai_link():
    sources = [
        {'url': 'https://t.me/news/1', 'rights': 'approved', 'source_type': 'social/relay'},
        {'url': 'https://example.com/story', 'rights': 'review_required', 'source_type': 'aggregator'},
        *event()['sources'],
    ]
    result = draft()
    result['summary_he'] += '\nמקור: https://evil.example.com/fake'
    output = message(event(sources), result, 'important_stock_news', ['SYN'])
    assert 'מקור: https://www.sec.gov/' in output
    assert 't.me/news' not in output and 'evil.example' not in output


def test_long_astral_body_preserves_source_community_and_utf16_budget():
    result = draft()
    result['summary_he'] = '📰 תוכן ' * 1200
    with patch.dict('os.environ', {'TELEGRAM_COMMUNITY_URL': 'https://t.me/+example'}):
        output = with_news_community_link(message(event(), result, 'market_news', []), 'market_news')
    assert 'https://www.sec.gov/Archives/edgar/data/123/filing.htm' in output
    assert output.endswith('https://t.me/+example')
    assert len(output.encode('utf-16-le')) // 2 <= 4096


def test_labeled_source_retained_but_inline_and_telegram_relay_still_hidden():
    body = 'כותרת https://untrusted.example.com/inline\nמקור: https://www.sec.gov/filing\nמקור: https://t.me/relay/1'
    output = with_news_community_link(body, 'sec_intelligence')
    assert 'מקור: https://www.sec.gov/filing' in output
    assert 'untrusted.example' not in output and 't.me/relay' not in output


def test_long_mixed_body_keeps_required_license_credit_date_and_links():
    from telegram_presentation import telegram_text, utf16_length
    source = event()
    source['sources'][0].update(publisher='Synthetic Credit', raw_metadata={
        'license_label': 'CC BY 3.0',
        'license_url': 'https://creativecommons.org/licenses/by/3.0/'})
    result = draft()
    result['summary_he'] = 'עברית A ' * 800
    with patch.dict('os.environ', {'TELEGRAM_COMMUNITY_URL': 'https://t.me/+' + 'a' * 490}):
        output = telegram_text(with_news_community_link(message(source, result, 'market_news', []), 'market_news'))
    assert utf16_length(output) <= 4096
    for required in ('Synthetic Credit', 'CC BY 3.0', 'creativecommons.org/licenses/by/3.0/',
                     'פורסם:', 'https://www.sec.gov/', 'https://t.me/+'):
        assert required in output
