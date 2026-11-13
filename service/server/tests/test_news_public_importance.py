"""Public-only editorial gates: synthetic source facts, no model/network."""
import json
import pytest
from test_directional_news_routing import legacy
from test_sec_public_editorial import isolated
from test_earnings_news_routing import dispatch
from test_public_news_translation_only import isolated_pipeline


@pytest.mark.parametrize('title', [
    'Could Example stock climb 61%? Or is the bank wrong?',
    '3 stocks to buy before the next rally',
    'Example Q3 earnings preview: what to expect',
    'Example Q3 earnings call transcript',
    'Example unveils a new beta app for shoppers',
    'Example names 100 new partners',
    'Federal Reserve announces schedule for interest rate discussion',
    'Example SEC filing is an annual meeting notice',
    'SEC supports constructive dialogue with companies',
    'Example Financial Results Conference to Be Held on Friday',
    'Example announces dividend of $1.20. Is This Stock a Buy?',
    'Lawmakers discuss impeachment campaign',
    'Why Example stock could double next year',
])
def test_promotional_opinion_and_routine_sources_are_held(title):
    from news_public_importance import source_importance
    assert source_importance(title)[0] is False


@pytest.mark.parametrize('title', [
    'Broker Adjusts Example PT to $105 From $100',
    'Broker downgrades Example to Sell from Hold',
    'Example reports Q3 revenue of $2 billion, EPS $1.20',
    'Example cuts full-year revenue guidance',
    'Example Q3 results beat estimates with raised outlook',
    'Example raised full-year revenue guidance',
    'Example withdrew profit forecast',
    'Example wins $200 million supply contract',
    'FDA approves Example treatment after Phase 3 trial',
    'Example Phase 3 study meets primary endpoint',
    'Example recalls devices after reported safety incidents',
    'S&P 500 falls 4% after rate decision',
    'US initial jobless claims rise to 240,000',
    'Federal Reserve holds interest rates steady',
    'Government proposes new tariffs on semiconductor imports',
    'Example announces acquisition of Other for $2 billion',
    'Example cutting 2,000 jobs as restructuring begins',
])
def test_concrete_facts_survive_without_requiring_full_article(title):
    from news_public_importance import source_importance
    assert source_importance(title)[0] is True


def test_generated_summary_cannot_supply_missing_source_importance(monkeypatch):
    from news_public_importance import row_publication_check
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    assert row_publication_check({'title':'3 stocks to buy','summary_he':'החברה פרסמה דוחות כספיים',
        'source_facts_json':'{}'})[0] is False


def test_risk_factor_boilerplate_does_not_lend_importance():
    from news_public_importance import source_importance
    assert source_importance('Example unveils a new beta app',
        'Risk factors include bankruptcy, layoffs and clinical trial results')[0] is False
    assert source_importance('Example unveils a new beta app',
        'Forward-looking statements could differ from actual financial results.')[0] is False
    assert source_importance('Example publishes an update',
        'The company reported Q2 revenue of 100 million dollars.')[0] is True


def test_disabled_flag_preserves_existing_behavior(monkeypatch):
    from news_public_importance import row_publication_check
    monkeypatch.delenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED',raising=False)
    assert row_publication_check({'title':'3 stocks to buy'}) == (True,None)


def test_real_source_version_contract_reaches_directional_topic(isolated,monkeypatch):
    from news_pipeline import _event_version
    from news_direction_routing import direction_for_outbox
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','true')
    version=_event_version({'title':'Synthetic acquisition approved','source_excerpt':'',
        'published_at':'2026-11-05T12:00:00Z'})
    assert len(version)==20
    assert direction_for_outbox(legacy(isolated,version=version))=='positive'


@pytest.mark.parametrize('version',['a'*19,'a'*21,'a'*40,'a'*63,'z'*20,'../unsafe'])
def test_unknown_version_formats_are_never_rerouted(isolated,monkeypatch,version):
    from news_direction_routing import direction_for_outbox
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','true')
    assert direction_for_outbox(legacy(isolated,version=version)) is None


@pytest.mark.parametrize('relevance,materiality',[(.79,'high'),(.9,'low'),(None,'high')])
def test_retained_pending_public_stock_rechecks_stricter_threshold(isolated,monkeypatch,relevance,materiality):
    from news_public_importance import outbox_publication_check
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    row=legacy(isolated,title='Example reports Q3 revenue of $2 billion',version='a'*20,
               relevance=relevance,materiality=materiality)
    assert outbox_publication_check(row)==(False,'public_quality_below_public_threshold')


def test_retained_pending_stock_honors_current_higher_configured_floor(isolated,monkeypatch):
    from news_public_importance import outbox_publication_check
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    monkeypatch.setenv('STOCK_SCANNER_TELEGRAM_BROAD_NEWS_MIN_RELEVANCE','.95')
    row=legacy(isolated,title='Example reports Q3 revenue of $2 billion',version='a'*20,relevance=.85)
    assert outbox_publication_check(row)==(False,'public_quality_below_public_threshold')


@pytest.mark.parametrize('suffix',['OTHER','TEST,TEST','TEST,OTHER',''])
def test_malformed_or_unverified_public_audience_is_held(isolated,monkeypatch,suffix):
    from news_public_importance import outbox_publication_check
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    row=legacy(isolated,title='Example cuts revenue guidance',version='a'*20)
    row['dedupe_key']=':'.join(row['dedupe_key'].split(':')[:3])+':'+suffix
    assert outbox_publication_check(row)==(False,'public_quality_source_version_unverified')


@pytest.mark.parametrize('kind',['position_news','watchlist_news','company_report','sec_intelligence',
    'trump_truth_post','entry','exit','new_signal'])
def test_other_channels_are_not_restricted(kind,monkeypatch):
    from news_public_importance import outbox_publication_check
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    assert outbox_publication_check({'event_type':kind,'message':'3 stocks to buy'})==(True,None)


def test_send_time_gate_uses_exact_retained_source_and_preserves_keys(isolated,monkeypatch):
    from news_public_importance import outbox_publication_check
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    row=legacy(isolated,title='3 stocks to buy',version='a'*20)
    assert outbox_publication_check(row)==(False,'public_quality_opinion_or_promotion')
    with isolated() as c:
        c.execute("UPDATE scanner_news SET title='Example reports Q3 revenue of $2 billion',content_hash=?",('b'*20,))
        c.commit()
    assert outbox_publication_check(row)==(False,'public_quality_source_version_unverified')


def test_personal_route_survives_public_quality_rejection(monkeypatch):
    from news_events.engine import route,Policy
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    event={'title':'3 stocks to buy','source_excerpt':'','tickers':['TEST','OTHER']}
    result=dict(related=True,relevance=.95,materiality='high',sentiment='positive')
    routes,reason=route(event,result,{'TEST'},set(),{'TEST','OTHER'},Policy())
    assert routes==[('portfolio_watchlist',['TEST'])] and reason is None


def test_translation_only_route_is_not_an_importance_bypass(monkeypatch):
    from news_events.engine import route,Policy
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    event={'title':'Could stocks double next year?','source_excerpt':'','tickers':[],'event_type':'market'}
    assert route(event,{'_public_translation_only':True},[],[],[],Policy())==([], 'public_quality_opinion_or_promotion')


def test_real_legacy_translation_queue_holds_spam_without_fabricating_scores(isolated_pipeline,monkeypatch):
    import news_pipeline
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    c=isolated_pipeline
    news_pipeline.ingest_items([{**c.item(),'title':'3 stocks to buy before the next rally',
        'source_excerpt':'These are our favorite stocks for the coming year.'}],c.clock)
    def translated(rows):
        return [dict(id=r['id'],title_he='שלוש מניות שכדאי לקנות',summary_he='רעיונות מניות',
            _public_translation_only=True,duplicate_of=0) for r in rows]
    result=news_pipeline.analyze_news_jobs(analyzer=translated,at=c.clock)
    assert result['analyzed']==1 and result['alerts']==0
    assert not c.rows('SELECT * FROM scanner_telegram_outbox')
    record=c.rows('SELECT * FROM scanner_news')[0]
    assert record['analysis_status']=='public_translated'
    assert all(record[k] is None for k in ('relevance','sentiment','materiality'))


def test_retained_spam_is_cancelled_without_telegram_on_restart(isolated,dispatch,monkeypatch):
    import scanner_engine
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    row=legacy(isolated,title='3 stocks to buy',version='a'*20)
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert not dispatch.post.called
    with isolated() as c:
        saved=dict(c.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?',(row['id'],)).fetchone())
    assert saved['status']=='cancelled'
    assert saved['last_error']=='public_quality_opinion_or_promotion'
    assert saved['dedupe_key']==row['dedupe_key']


def test_canonical_scored_public_floor_does_not_lower_custom_threshold(monkeypatch):
    from news_events.engine import route,Policy
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    event={'title':'Example cuts revenue guidance','tickers':['TEST'],'source_excerpt':''}
    result=dict(related=True,relevance=.79,materiality='high',sentiment='negative')
    assert route(event,result,[],[],['TEST'],Policy())[0]==[]
    assert route(event,dict(result,relevance=.85),[],[],['TEST'],Policy(stock_relevance=.90))[0]==[]
    assert route(event,dict(result,relevance=.85),[],[],['TEST'],Policy())[0]==[('important_stock_news',['TEST'])]
