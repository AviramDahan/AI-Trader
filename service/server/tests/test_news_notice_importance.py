from decimal import Decimal

import pytest

from news_notice_importance import add_importance, analyst_importance, macro_importance, news_importance


@pytest.mark.parametrize(('title', 'level', 'reason'), [
    ('Federal Reserve holds interest rates at 4.25%', 'גבוהה', 'החלטת ריבית'),
    ('Federal Reserve may cut rates next month', 'לא נקבעה', 'לא הוצג'),
    ('Company cuts full-year revenue guidance', 'גבוהה', 'תחזית'),
    ('Company cuts spending and reaffirms guidance', 'לא נקבעה', 'לא הוצג'),
    ('Company shares jump 5% after rally', 'נמוכה', 'תנועת מחיר'),
    ('FDA approves Example drug', 'גבוהה', 'רגולטורית'),
    ('FDA could approve Example drug', 'לא נקבעה', 'לא הוצג'),
    ('Company reports a data breach', 'בינונית', 'סייבר'),
    ('Example reports Q3 revenue of $2 billion', 'בינונית', 'תוצאות'),
    ('Company announces Q3 earnings date', 'לא נקבעה', 'לא הוצג'),
])
def test_facts_set_importance_without_predicting_price(title, level, reason):
    notice = news_importance(title)
    assert f'חשיבות {level}' in notice and reason in notice


def test_forecast_comparison_uses_exact_reported_values():
    assert 'ללא הפתעה' in macro_importance([(Decimal('3.4'), Decimal('3.4'))])
    assert '0.2 נקודות אחוז מעל הצפי' in macro_importance([(Decimal('3.4'), Decimal('3.2'))])
    assert '0.3 נקודות אחוז מתחת לצפי' in macro_importance([(Decimal('3.4'), Decimal('3.7'))])
    assert 'באחד או יותר מהנתונים' in macro_importance([(Decimal('3.4'), Decimal('3.7')),
                                                 (Decimal('3.4'), Decimal('3.4'))])


def test_analyst_rating_and_target_have_different_reasons():
    assert 'דירוג המניה' in analyst_importance('Broker downgrades Example to Hold')
    assert '16% ביחס ליעד הקודם' in analyst_importance('Broker lowers price target to $84 from $100')
    assert 'חשיבות נמוכה' in analyst_importance('Broker raises price target to $102 from $100')
    assert 'לא נקבעה' in analyst_importance('Example upgrades its cloud platform to Buy More Storage')
    assert '%' not in analyst_importance('Broker lowers price target to €84 from $100')


def test_annotation_keeps_heading_and_budget():
    message = '📰 ידיעה\n\nטקסט'
    annotation = news_importance('FDA approves Example drug')
    assert add_importance(message, annotation).splitlines()[:2] == ['📰 ידיעה', annotation]
    assert add_importance(add_importance(message, annotation), annotation) == add_importance(message, annotation)
    long = '📰 ידיעה\n\n' + 'א' * 3800
    assert add_importance(long, annotation) == long


@pytest.mark.parametrize(('title', 'expected'), [
    ('Spain CPI (Y/Y) Oct: 4.9% (est 4.9%; prev 4.9%)', 'ללא הפתעה'),
    ('FRENCH CPI MOM NSA ACTUAL 3.4% (FORECAST 3.2%, PREVIOUS 3.4%) $MACRO', '0.2 נקודות אחוז מעל הצפי'),
    ('SWISS PPI MOM ACTUAL 0.9% (FORECAST -, PREVIOUS 0.3%) $MACRO', 'ללא צפי בר־השוואה'),
    ('France PPI report could surprise as it did in 2025', 'לא נקבעה'),
])
def test_verified_format_is_required_for_forecast_comparison(title, expected):
    assert expected in news_importance(title)


def test_activity_topics_keep_heading_and_queue_contract(monkeypatch):
    import json
    from datetime import datetime, timezone
    from unittest.mock import Mock
    import sec_activity_topics

    now = datetime(2026, 11, 13, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(sec_activity_topics, 'destination',
                        lambda kind, *_: {'ownership_activity': 41, 'buyback_activity': 42}[kind])
    conn = Mock()
    query = conn.execute.return_value
    query.fetchone.return_value = {'members_json': '{"SYN":{"issuer_cik":"1","company":"Synthetic"}}'}
    query.rowcount = 1
    job = {'form': 'SCHEDULE 13G', 'accession': 'synthetic', 'accepted_at': now.isoformat(),
           'issuer_cik': '1', 'tickers_json': '["SYN"]', 'universe_snapshot_id': 1}
    holdings = {'reported_date': '2026-11-13', 'security': 'Common stock',
                'persons': [{'name': 'Synthetic Fund', 'percent': '6'}], 'additional_person_count': 0}
    assert sec_activity_topics.enqueue(job, {'kind': 'beneficial_ownership', 'holdings': holdings}, [], now, conn)
    key, kind, packed, *_ = conn.execute.call_args.args[1]
    assert kind == 'ownership_activity' and key == 'sec-activity:v1:ownership_activity:synthetic'
    envelope = json.loads(packed)
    assert envelope['version'] == 1 and envelope['thread'] == 41
    heading, priority, *_ = envelope['text'].splitlines()
    assert '13G' in heading and priority.startswith('מידע למעקב')
    assert 'רכישה' not in envelope['text']
    assert sec_activity_topics.enqueue({**job, 'form': '10-Q'},
        {'kind': 'financial', 'buyback_cash': {'usd_paid': '2000000', 'start': '2026-01-01', 'end': '2026-09-30'}},
        [], now, conn)
    _, kind, packed, *_ = conn.execute.call_args.args[1]
    envelope = json.loads(packed)
    assert kind == 'buyback_activity' and envelope['thread'] == 42
    assert 'תשלום בפועל' in envelope['text'].splitlines()[1]


@pytest.mark.parametrize('render', ['_news_alert_message', '_watchlist_alert_message', '_stock_broadcast_alert_message'])
def test_stock_notices_keep_facts_without_repeating_the_headline(render):
    import news_pipeline

    row = dict(ticker='SYN', title='Example raises full-year revenue guidance',
               title_he='החברה העלתה תחזית', summary_he='החברה העלתה תחזית. התחזית החדשה היא 20 מיליון דולר.',
               published_at='2026-11-13T10:15:00Z', impact='positive', headline_only=True,
               interpretation_he='טקסט פרשנות שלא שייך להודעת כותרת')
    notice = getattr(news_pipeline, render)(row)
    assert notice.count(row['title_he']) == 1
    assert 'חשיבות גבוהה' in notice and '20 מיליון דולר' in notice and 'SYN' in notice
    assert 'כותרת בלבד' in notice and row['interpretation_he'] not in notice
    assert len(notice) < 330
