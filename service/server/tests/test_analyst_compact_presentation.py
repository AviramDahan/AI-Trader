"""Presentation-only checks: synthetic notices, no model or external sends."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from news_analyst_presentation import compact_parts
from test_earnings_news_routing import dispatch

TITLE = 'UBS העלה את מחיר היעד של חברת דוגמה מ־220 ל־250 דולר'
SUMMARY = TITLE+'. החברה פועלת בשוק תחרותי. יש לה לקוחות במדינות רבות. '
INTERPRETATION = 'המהלך עשוי להשפיע על המסחר ויש לבחון את הסיכונים.'


def test_repeated_headline_removed_but_complementary_summary_not_guessed_away():
    assert compact_parts(TITLE, SUMMARY, 'SYN') == ['📊 '+TITLE, 'מניות: SYN',
        'החברה פועלת בשוק תחרותי. יש לה לקוחות במדינות רבות.']


def test_complementary_rating_and_decimal_target_survive_without_calculation():
    details = 'מחיר היעד הופחת מ־150.50 ל־125.25 דולר. ההמלצה נשארה קנייה.'
    text = '\n'.join(compact_parts('UBS עדכן את המלצתו לחברת דוגמה', details))
    assert '150.50 ל־125.25' in text and 'ההמלצה נשארה קנייה' in text
    assert '%' not in text and 'אפסייד' not in text


def test_different_targets_are_not_deduplicated_by_numeric_prefix():
    text = '\n'.join(compact_parts('מחיר היעד של UBS הוא $1500', 'מחיר היעד של UBS הוא $150.'))
    assert '$150.' in text


def test_multiple_broker_actions_remain_even_if_longer():
    text = '\n'.join(compact_parts('UBS העלה המלצה לקנייה',
        'בית ההשקעות Citi הוריד מחיר יעד ל־90 דולר. Barclays העלה מחיר יעד ל־110 דולר.'))
    assert 'Citi' in text and 'Barclays' in text and '90' in text and '110' in text


def test_no_hebrew_title_uses_existing_summary_without_new_translation_or_extraction():
    assert compact_parts(None, 'רקע כללי. UBS העלה מחיר יעד ל־120 דולר.')[0] == '📊 רקע כללי. UBS העלה מחיר יעד ל־120 דולר.'


def event_and_result():
    event = {'title':'UBS raises Synthetic price target to $250 from $220',
             'published_at':'2026-11-06T14:00:00+00:00',
             'sources':[{'title':'UBS raises Synthetic price target to $250 from $220',
                         'publisher':'Licensed Publisher', 'raw_metadata':{
                             'license_url':'https://creativecommons.org/licenses/by/3.0/',
                             'license_label':'CC BY 3.0'}}]}
    result = {'title_he':TITLE, 'summary_he':SUMMARY, 'interpretation_he':INTERPRETATION}
    return event, result


def test_canonical_compact_keeps_time_license_and_attribution(monkeypatch):
    from news_events.runtime import message
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','true')
    event, result = event_and_result()
    text = message(event,result,'important_stock_news',['SYN'])
    assert text.count('250') == 1 and '📊' in text
    assert 'משמעות אפשרית' not in text and 'שוק תחרותי' in text
    assert 'Licensed Publisher' in text and 'CC BY 3.0' in text
    assert 'https://creativecommons.org/licenses/by/3.0/' in text and 'פורסם:' in text


@pytest.mark.parametrize('topic,flag',[('important_stock_news','false'),('portfolio_watchlist','true')])
def test_flag_off_and_personal_canonical_messages_keep_existing_detail(monkeypatch,topic,flag):
    from news_events.runtime import message
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED',flag)
    event,result=event_and_result()
    text=message(event,result,topic,['SYN'])
    assert INTERPRETATION in text and 'שוק תחרותי' in text and '📊' not in text


def legacy_row():
    return dict(ticker='SYN',company='Synthetic',title='UBS raises Synthetic price target to $250 from $220',
                title_he=TITLE,summary_he=SUMMARY,interpretation_he=INTERPRETATION,
                impact='positive',materiality='high',headline_only=False,
                published_at='2026-11-06T14:00:00+00:00',publisher='Synthetic Wire',
                url='https://example.com/story',source_facts_json=json.dumps({}))


def test_legacy_stock_bulletin_is_short_and_routes_to_same_analyst_topic(monkeypatch,dispatch):
    import news_pipeline,stock_scanner
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_THREAD_ID','880')
    text=news_pipeline._stock_broadcast_alert_message(legacy_row())
    assert len(text)<250 and TITLE in text and text.count('250')==1
    assert 'פורסם:' in text and 'מניות: SYN' in text
    assert 'מהותיות' not in text and INTERPRETATION not in text
    assert stock_scanner.send_telegram(text,{'telegram_enabled':True},'stock_news')=='sent'
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==880


def test_non_analyst_stock_bulletin_keeps_existing_template(monkeypatch):
    from news_pipeline import _stock_broadcast_alert_message
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','true')
    row={**legacy_row(),'title':'Synthetic opens new factory'}
    text=_stock_broadcast_alert_message(row)
    assert INTERPRETATION in text and 'מהותיות' in text
