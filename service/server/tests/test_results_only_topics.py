"""Human-approved results-only topic: values, source and period, no new AI."""
import json
import pytest
from test_directional_news_routing import legacy,canonical
from test_earnings_news_routing import dispatch
from test_sec_public_editorial import isolated
from test_public_news_translation_only import isolated_pipeline


@pytest.fixture(autouse=True)
def strict(monkeypatch):
    monkeypatch.setenv('TELEGRAM_COMPANY_REPORTS_RESULTS_ONLY_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_POSITIVE_STOCK_NEWS_THREAD_ID','201')


@pytest.mark.parametrize('title,body',[
    ('Example Q3 Earnings Beat Estimates','Revenue increased but no figure is supplied.'),
    ('Example reports Q3 earnings','Expected EPS $2.10; consensus revenue $100 million.'),
    ('Example reports Q3 revenue','Revenue not supplied, stock price $100.'),
    ('Example reports revenue $100 million','The report period is not supplied.'),
    ('📊 דיווח תוצאות — עדכון מהחברה','לא נמסרו נתונים.'),
])
def test_no_results_topic_from_qualitative_expectations_or_presentation_prefix(title,body):
    from news_report_routing import is_company_report
    assert not is_company_report(title,body)


@pytest.mark.parametrize('title,body',[
    ('Example reports Q3 results','EPS $2.10; revenue $100 million. Expected EPS $2.00.'),
    ('Example Q3 Earnings','Example reported EPS $2.10 and revenue $100 million.'),
    ('החברה דיווחה על תוצאות הרבעון השלישי','הרווח למניה היה 2.10 דולר, לעומת צפי של 2.00 דולר.'),
    ('החברה דיווחה על רווחים ברבעון השלישי','רווח למניה של 3.55 אירו, לעומת צפי של 2.80 אירו, ומכירות של 14.44 מיליארד אירו.'),
    ('Example reports FY2026 financial results','Revenue $100 million.'),
    ('Example reports Q3 revenue','Revenue increased 18% year on year.'),
])
def test_real_values_with_period_qualify_and_consensus_is_optional(title,body):
    from news_report_routing import is_company_report
    assert is_company_report(title,body)


def test_true_earnings_fact_remains_news_eligible_without_report_values():
    from news_report_routing import is_company_report
    from news_public_importance import source_importance
    title='Example Q3 Earnings Beat Estimates'
    assert not is_company_report(title)
    assert source_importance(title)==(True,None)


def test_dedicated_structured_report_type_keeps_its_topic():
    from news_report_routing import delivery_type
    assert delivery_type('company_report','Existing producer envelope')=='company_report'
    from news_report_routing import is_company_report
    assert is_company_report('📊 תוצאות פעילות החברה',
        'התוצאות בפועל\nתזרים מפעילות שוטפת\nבפועל: 267.2 מיליון דולר\nתקופת הדיווח: 2026-07-01 עד 2026-09-30')
    assert is_company_report('📊 תוצאות פעילות החברה',
        'תקופת הדיווח: 2026-07-01 עד 2026-09-30\nהכנסות\nנוכחי: 50,540,000,000 USD')


@pytest.mark.parametrize('title,summary,report',[
    ('תוצאות הרבעון השלישי','הרווח למניה היה 2.10 דולר.',True),
    ('עדכון מהחברה','התוצאות טובות מהצפוי.',False),
])
def test_actual_legacy_queue_needs_source_and_visible_values(isolated_pipeline,title,summary,report):
    import news_pipeline
    c=isolated_pipeline
    news_pipeline.ingest_items([{**c.item(),'title':'Example reports Q3 EPS $2.10',
        'source_excerpt':'Example reported Q3 EPS of $2.10 and quarterly revenue of $100 million.'}],c.clock)
    analyzer=lambda rows:[dict(id=r['id'],title_he=title,summary_he=summary,_public_translation_only=True,duplicate_of=0) for r in rows]
    assert news_pipeline.analyze_news_jobs(analyzer=analyzer,at=c.clock)['alerts']==1
    from news_report_routing import REPORT_PREFIX
    saved=c.rows('SELECT * FROM scanner_telegram_outbox')[0]
    assert saved['message'].startswith(REPORT_PREFIX) is report
    assert c.rows('SELECT relevance FROM scanner_news')[0]['relevance'] is None


@pytest.mark.parametrize('source,message,expected',[
    ('Example Q3 Earnings Beat Estimates','Example Q3 Earnings Beat Estimates',201),
    ('Example reports Q3 EPS $2.10','Example reports Q3 EPS $2.10',456),
    ('Example opens a factory','Example reports Q3 EPS $2.10',201),
    ('Example reports Q3 EPS $2.10','📊 דיווח תוצאות — עדכון מהחברה',201),
])
def test_retained_legacy_send_uses_source_and_visible_values_once(isolated,dispatch,source,message,expected):
    import scanner_engine
    row=legacy(isolated,title=source,version='a'*20)
    with isolated() as c:
        c.execute('UPDATE scanner_telegram_outbox SET message=? WHERE id=?',(message,row['id']));c.commit()
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==expected
    assert scanner_engine.process_telegram_outbox()['sent']==0 and dispatch.post.call_count==1


def test_audit_mismatch_cannot_promote_old_report_prefix(isolated):
    from news_report_routing import report_for_outbox
    row=legacy(isolated,title='Example reports Q3 EPS $2.10',version='a'*20)
    row['message']='Example reports Q3 EPS $2.10'
    with isolated() as c:
        c.execute("INSERT INTO news_publication_audit(news_id,content_version,evidence_key,reasons_json,updated_at) VALUES(1,?,'fixture','[]','2026-11-05T12:00:00Z')",('b'*64,));c.commit()
    assert report_for_outbox(row) is False


@pytest.mark.parametrize('change',[{'event_type':'market_news'},{'dedupe_key':'stock-news:1:'+('a'*20)+':OTHER'}])
def test_mismatched_family_or_audience_cannot_acquire_report_identity(isolated,change):
    from news_report_routing import report_for_outbox
    row=legacy(isolated,title='Example reports Q3 EPS $2.10',version='a'*20)
    row['message']='Example reports Q3 EPS $2.10';row.update(change)
    assert report_for_outbox(row) is False


def test_expectations_section_and_stock_price_are_not_actual_results():
    from news_report_routing import is_company_report
    assert not is_company_report('Example Q3 financial results','Analyst expectations\nEPS $2.10\nRevenue $100 million')
    assert not is_company_report('Example Q3 financial results','Revenue not supplied, stock price $100.')
    assert not is_company_report('Example Q3 financial results','Forecast FY2027 revenue $100 million.')


def test_source_and_shown_canonical_period_values_are_both_required():
    from news_report_routing import report_for_presentation
    event={'title':'Example reports Q3 EPS $2.10','source_excerpt':'','sources':[]}
    assert report_for_presentation(event,{'title_he':'תוצאות הרבעון השלישי','summary_he':'הרווח למניה היה 2.10 דולר.'})
    assert not report_for_presentation(event,{'title_he':'עדכון מהחברה','summary_he':'התוצאות טובות.'})
    assert not report_for_presentation({'title':'Example opens a factory','sources':[]},
        {'title_he':'תוצאות הרבעון השלישי','summary_he':'הרווח למניה היה 2.10 דולר.'})


def test_canonical_keys_bind_report_even_with_other_routing_flags_off(monkeypatch):
    from news_events.runtime import general_publication_keys
    from news_events import general_news
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_COMPANY_REPORTS_THREAD_ID','456')
    monkeypatch.setenv('TELEGRAM_CHAT_ID','fixture')
    seen=[];monkeypatch.setattr(general_news,'publication_keys',lambda e,v,d:seen.append(d) or ['fixture'])
    event={'title':'Example reports Q3 EPS $2.10','source_excerpt':'','sources':[]}
    result={'title_he':'תוצאות הרבעון השלישי','summary_he':'הרווח למניה היה 2.10 דולר.'}
    general_publication_keys(event,'a'*64,'market_news',result)
    assert seen==[['fixture',456]]


@pytest.mark.parametrize('body',[
    'Revenue $100 million forecast.',
    'Revenue of $100 million was expected.',
    'Prior-year revenue $100 million.',
    'Revenue $100 million in the prior year.',
    'הכנסות בשנה שעברה: 100 מיליון דולר.',
    'רווח למניה צפוי של 2.10 דולר.',
    'EPS 2.10 forecast.',
])
def test_only_forecast_or_prior_context_cannot_supply_current_results(body):
    from news_report_routing import is_company_report
    assert not is_company_report('Example Q3 financial results',body)


@pytest.mark.parametrize('body',[
    'Revenue was $100 million; expected revenue was $110 million.',
    'EPS $2.10 versus expected EPS $2.00.',
    'Revenue $100 million, prior-year $90 million.',
    'Revenue $100 million versus $90 million in the prior year.',
    'Revenue increased 18% from the prior year.',
])
def test_actual_value_keeps_separate_consensus_and_prior_comparison(body):
    from news_report_routing import is_company_report
    assert is_company_report('Example Q3 financial results',body)


@pytest.mark.parametrize('body',[
    'Revenue $100 million last quarter.',
    'Revenue $100 million a year ago.',
    'Last-quarter revenue $100 million.',
    'A year ago revenue $100 million.',
    'Revenue increased 18% last quarter.',
    'Revenue increased 18% in the prior year.',
])
def test_explicit_previous_quarter_or_year_ago_is_not_current(body):
    from news_report_routing import is_company_report
    assert not is_company_report('Example Q3 financial results',body)


def test_current_value_survives_previous_quarter_comparison():
    from news_report_routing import is_company_report
    assert is_company_report('Example Q3 financial results','Revenue $100 million versus $90 million last quarter.')


@pytest.mark.parametrize('body',['Analysts expect revenue of $100 million.','Analysts expect EPS $2.10.'])
def test_present_analyst_expectation_is_not_a_reported_result(body):
    from news_report_routing import is_company_report
    assert not is_company_report('Example Q3 financial results',body)


def test_actual_eps_beating_analyst_expectations_stays_actual():
    from news_report_routing import is_company_report
    assert is_company_report('Example Q3 financial results','EPS $2.10 beats analyst expectations.')
