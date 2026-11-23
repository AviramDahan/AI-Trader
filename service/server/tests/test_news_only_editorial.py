from news_only_editorial import analyst_subject_symbol, qualified_copy
from news_pipeline import _watchlist_alert_message
from test_company_report_sections import render
from test_sec_public_editorial import comparison


def test_analyst_uses_issuer_and_omits_ambiguous_symbols():
    assert analyst_subject_symbol('Disney beats estimates while Bank of America (BAC) raises price target') == 'DIS'
    assert analyst_subject_symbol('Bank of America (BAC) raises Target (TGT) to $120') == 'TGT'
    assert analyst_subject_symbol('Bank of America (BAC) raises price target') == ''


def test_preliminary_claim_remains_qualified_without_assertive_paraphrase():
    assert qualified_copy('Preliminary report: SEC opens inquiry', 'נפתחה בדיקה', 'הרשות פתחה בחקירה') == (
        'דיווח ראשוני: נפתחה בדיקה', '')
    assert qualified_copy('Company reports revenue of $10M', 'הכנסות', 'נתון נוסף') == ('הכנסות', 'נתון נוסף')


def test_watchlist_uses_one_line_when_no_article(monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    row = dict(ticker='NVDA', title='Company files annual report', title_he='החברה הגישה דוח שנתי',
               summary_he='החברה פרסמה דוח שנתי', headline_only=True)
    assert _watchlist_alert_message(row) == 'NVDA · החברה הגישה דוח שנתי'


def test_unavailable_consensus_section_is_omitted(monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    body = render([comparison(value=120_000_000, previous=100_000_000)])
    assert 'ציפיות האנליסטים' not in body and 'לא זמין' not in body
    assert '120 מיליון דולר' in body and 'בתקופה המקבילה: 100 מיליון דולר' in body
