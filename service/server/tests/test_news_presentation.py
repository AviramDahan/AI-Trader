from copy import deepcopy
from unittest.mock import patch
from news_presentation import hide_relay_branding
from telegram_topics import with_news_community_link
import pytest


@pytest.mark.parametrize('control',['\u200f','\u200e','\u061c','\u2067','\u2069','\u200b','\ufeff',''])
@pytest.mark.parametrize('prefix',['לפי כותרת שפרסם ערוץ','לפי ערוץ','על פי דיווח שפורסם בערוץ'])
def test_invisible_direction_controls_cannot_leak_relay(control,prefix):
    facts='רמסדן אמר כי גדל הסיכון לאינפלציה גבוהה יותר שתימשך זמן רב יותר.'
    body=f'{prefix} Telegram {control}@financialjuice, {facts}'
    cleaned=hide_relay_branding(body)
    assert 'financialjuice' not in cleaned and 'Telegram' not in cleaned
    assert facts in cleaned
    assert cleaned=='לפי דיווח, '+facts
    assert cleaned==hide_relay_branding(cleaned)


def test_exact_reported_headline_wrapper_is_readable():
    body='לפי כותרת שפרסם ערוץ Telegram \u200f@financialjuice, רמסדן אמר כי גדל הסיכון.'
    assert hide_relay_branding(body)=='לפי דיווח, רמסדן אמר כי גדל הסיכון.'


@pytest.mark.parametrize('event',['market_news','position_news','watchlist_news','stock_news'])
def test_bidi_cleanup_at_send_time_preserves_community_and_dates(event):
    body='לפי כותרת שפרסם ערוץ Telegram \u200f@financialjuice, ייתכן שינוי.\nפורסם: 28/09/2026 14:07'
    with patch.dict('os.environ',{'TELEGRAM_COMMUNITY_URL':'https://t.me/+example'}):
        result=with_news_community_link(body,event)
        assert 'financialjuice' not in result and 'Telegram' not in result
        assert 'ייתכן שינוי.' in result and '14:07' in result
        assert result.count('https://t.me/+example')==1


def test_reported_ramsden_message_and_queued_sender_cleanup():
    facts='רמסדן אמר כי ימשיך להתמקד בלחצים חיצוניים על האינפלציה.'
    message=facts+' הדברים דווחו בערוץ Telegram @financialjuice.\n\nTelegram @financialjuice\n\nפורסם: 28/09/2026 13:04'
    with patch.dict('os.environ',{'TELEGRAM_COMMUNITY_URL':'https://t.me/+example'}):
        out=with_news_community_link(message,'market_news')
        assert 'financialjuice' not in out and 'Telegram' not in out
        assert facts in out and 'פורסם:' in out and 'https://t.me/+example' in out
        assert out==with_news_community_link(out,'market_news')
        assert with_news_community_link(message,'entry')==message


def test_attribution_and_uncertainty_not_erased():
    assert hide_relay_branding('לפי ערוץ Telegram @financialjuice, ייתכן שהריבית תרד.')=='לפי דיווח, ייתכן שהריבית תרד.'
    assert hide_relay_branding('רמסדן אמר שלא הוחלט על הורדת ריבית.')=='רמסדן אמר שלא הוחלט על הורדת ריבית.'
    assert hide_relay_branding('ערוץ Telegram @financialjuice ציטט את רמסדן: ייתכן שינוי.')=='דיווח ציטט את רמסדן: ייתכן שינוי.'


def test_canonical_message_hides_publisher_without_mutating_provenance():
    from news_events.runtime import message
    event={'published_at':'2026-09-28T10:04:00Z','sources':[{'publisher':'Telegram @financialjuice','raw_metadata':{}}]}
    original=deepcopy(event)
    result={'title_he':'רמסדן: לחצים על האינפלציה','summary_he':'רמסדן אמר כי הלחצים נמשכים. הדברים דווחו בערוץ Telegram @financialjuice.','interpretation_he':'קיימת אי־ודאות.'}
    for topic in ('market_news','portfolio_watchlist','important_stock_news'):
        out=message(event,result,topic,[])
        assert 'financialjuice' not in out and 'Telegram' not in out
        assert 'רמסדן אמר כי הלחצים נמשכים.' in out
    assert event==original
