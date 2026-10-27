"""Public editorial policy and exact release updates; synthetic sources only."""
from datetime import timedelta
import pytest

from test_news_events import env, NOW, RESULT, source
from news_events.engine import route, Policy, Analysis
from dataclasses import replace


def bulletin(**kw):
    return source(event_refs=(), event_type='market',
        title=kw.pop('title', 'New Zealand CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)'),
        source_excerpt=kw.pop('source_excerpt', ''), **kw)


def test_market_publication_requires_impact_not_only_topicality():
    event={'tickers':[], 'event_type':'market'}
    assert route(event, {**RESULT,'materiality':'low'},set(),set(),{},Policy()) == ([], 'low_importance')
    assert route(event, {**RESULT,'materiality':'medium'},set(),set(),{},Policy())[0] == [('market_news',[])]
    assert route(event, {**RESULT,'related':False},set(),set(),{},Policy()) == ([], 'irrelevant')
    assert route(event, {**RESULT,'relevance':.29},set(),set(),{},Policy()) == ([], 'below_market_threshold')


@pytest.mark.parametrize('relevance,allowed',[(.899,False),(.90,True),(1.0,True)])
def test_supplemental_market_updates_require_high_relevance(relevance,allowed):
    policy=Policy(market_low_materiality_relevance=.90)
    event={'tickers':[], 'event_type':'market'}
    result={**RESULT,'materiality':'low','relevance':relevance}
    assert bool(route(event,result,set(),set(),{},policy)[0]) is allowed
    assert route(event,{**result,'related':False},set(),set(),{},policy)==([], 'irrelevant')
    # Personal and company alerts retain their materiality gate.
    company={'tickers':['AAPL'],'event_type':'earnings'}
    assert route(company,result,{'AAPL'},set(),{'AAPL':{}},policy)==([], 'low_importance')


def test_supplemental_market_reuses_quality_freshness_and_duplicate_pipeline(env):
    p,s,_=env
    p.policy=replace(p.policy,market_low_materiality_relevance=.90)
    item=bulletin()
    eid=p.ingest(item,NOW)
    assert p.analyze(eid,lambda e:Analysis({**RESULT,'materiality':'low','relevance':.90}),NOW)=='done'
    assert p.queue(eid,NOW)==[('market_news',[])]
    assert p.deliver_preview(eid,NOW)[0]['topic']=='market_news'
    assert p.deliver_preview(eid,NOW)==[]
    old=p.ingest(bulletin(source_id='old',title='New Zealand CPI (Q/Q) Q2: 0.6%',
                         published_at=(NOW-timedelta(days=8)).isoformat()),NOW)
    assert s.event(old)['reason'] in {'backlog_blocked','stale_or_future'}
    assert p.queue(old,NOW)==[]
    assert s.event(eid)['body']['tickers']==[]


def test_effective_policy_explicit_supplemental_threshold():
    from news_events.bridge import effective_policy
    policy=effective_policy({'alert_min_relevance':.55,'broad_alert_min_relevance':.70},.30,6,6,168,
                            market_low_materiality_relevance=.90)
    assert policy.market_low_materiality_relevance==.90
    assert policy.personal_relevance==.55 and policy.stock_relevance==.70


def test_same_release_annual_addition_retained_as_new_material_version(env):
    p,s,_=env
    first=bulletin()
    eid=p.ingest(first,NOW)
    before=s.event(eid)['evidence_version']
    p.analyze(eid,lambda e:Analysis(RESULT),NOW)
    second=bulletin(provider='wire',source_id='annual',
        title='New Zealand CPI (Y/Y) Q3: 3.7% (est 3.8%; prev 4.1%)',
        collected_at=(NOW+timedelta(seconds=33)).isoformat())
    assert p.ingest(second,NOW+timedelta(seconds=33)) == eid
    event=s.event(eid)
    assert event['evidence_version'] != before and event['status']=='pending'
    assert len(event['body']['sources'])==2
    evidence=event['body']['normalized_evidence']
    assert any('0.7%' in v['text'] for v in evidence)
    assert any('3.7%' in v['text'] for v in evidence)
    assert len({k for v in evidence for k in v['claims'] if k.startswith('macro_release:')})==6


@pytest.mark.parametrize('title',[
    'Australia CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)',
    'New Zealand Core CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)',
    'New Zealand CPI (Q/Q) Q2: 0.7% (est 0.8%; prev 1.5%)',
    'New Zealand CPI (M/M) Sep: 0.7% (est 0.8%; prev 1.5%)',
    'New Zealand CPI (Q/Q) Q3 preliminary: 0.7% (est 0.8%; prev 1.5%)',
    'New Zealand CPI QOQ ACTUAL 0.7% (FORECAST 0.8%, PREVIOUS 1.5%)',
])
def test_different_or_unknown_release_identity_not_merged(env,title):
    p,s,_=env
    eid=p.ingest(bulletin(),NOW)
    assert p.ingest(bulletin(provider='other',title=title),NOW)!=eid


def test_conflicting_actual_same_release_is_retained_and_held(env):
    p,s,_=env
    eid=p.ingest(bulletin(),NOW)
    assert p.ingest(bulletin(provider='wire',title='New Zealand CPI (Q/Q) Q3: 0.9% (est 0.8%; prev 1.5%)'),NOW)==eid
    event=s.event(eid)
    assert event['reason']=='source_conflict' and len(event['body']['sources'])==2
    assert event['body']['conflicts']


def test_new_unstructured_information_is_never_discarded_or_auto_published(env):
    p,s,_=env
    eid=p.ingest(bulletin(),NOW)
    p.analyze(eid,lambda e:Analysis(RESULT),NOW)
    assert p.ingest(bulletin(provider='wire',source_excerpt='The statistics office also described revisions and a change in the underlying survey coverage.'),NOW)==eid
    event=s.event(eid)
    assert event['status']=='needs_material_review'
    assert 'survey coverage' in str(event['body']['normalized_evidence'])


def test_company_news_cannot_borrow_macro_identity(env):
    p,s,_=env
    eid=p.ingest(bulletin(),NOW)
    assert p.ingest(bulletin(provider='other',source_excerpt='Apple Inc. reports an unrelated supplier update.'),NOW)!=eid


def test_queue_priority_keeps_personal_first_then_concrete_then_stable_age():
    from news_events.editorial import priority
    events=[{'id':1,'tickers':[],'event_type':'business_update'},
            {'id':2,'tickers':[],'event_type':'earnings'},
            {'id':3,'tickers':['AAPL'],'event_type':'business_update'},
            {'id':4,'tickers':[],'event_type':'earnings'}]
    assert [e['id'] for e in sorted(events,key=lambda e:priority(e,{'AAPL'}))]==[3,2,4,1]


def test_own_source_conflict_cannot_supply_trusted_macro_anchor():
    from news_events.editorial import macro_release
    assert macro_release(bulletin(source_excerpt='New Zealand CPI (Q/Q) Q3: 0.9% (est 0.8%; prev 1.5%)').data()) is None
