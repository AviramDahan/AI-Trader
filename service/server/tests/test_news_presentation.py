from copy import deepcopy
from unittest.mock import patch
from news_presentation import hide_relay_branding
from telegram_topics import with_news_community_link


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
