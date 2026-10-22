"""Approved market-brief extension; all sources/AI/database are synthetic."""
from dataclasses import replace
from datetime import timedelta
from copy import deepcopy
import pytest

from test_news_events import env, NOW, RESULT, source
from news_events.engine import Policy, Analysis, route


def market(**kwargs):
    return source(event_refs=(), event_type='market',
        title=kwargs.pop('title', 'S&P 500 rises 0.2%'),
        source_excerpt=kwargs.pop('source_excerpt', ''), **kwargs)


def low():
    return {**RESULT, 'materiality':'low', 'relevance':.7,
        'title_he':'מדד השוק עלה בשיעור מדווח',
        'summary_he':'המקור דיווח על עלייה במדד. זהו עדכון שוק ולא המלצת מסחר.'}


def test_approved_brief_routes_while_default_policy_stays_unchanged(env):
    p,s,_=env
    eid=p.ingest(market(),NOW);event=s.event(eid)['body']
    assert route(event,low(),set(),set(),{},Policy()) == ([], 'low_importance')
    assert route(event,low(),set(),set(),{},Policy(market_briefs_enabled=True)) == ([('market_news',[])],None)


@pytest.mark.parametrize('field,value', [
    ('related',False),('relevance',.29),('materiality','unknown'),
    ('title_he','x'*241),('summary_he','x'*601),('summary_he',''),
])
def test_briefs_do_not_relax_relevance_or_trim_reviewed_qualifiers(env,field,value):
    p,s,_=env;eid=p.ingest(market(),NOW)
    assert not route(s.event(eid)['body'],{**low(),field:value},set(),set(),{},Policy(market_briefs_enabled=True))[0]


@pytest.mark.parametrize('change', [
    'tickers','company_identity','cik','source_tickers','provider_tickers',
    'rights','conflict','evidence','unmatched_title','bad_url','bad_timestamp',
])
def test_factual_identity_rights_and_matching_source_cannot_be_bypassed(env,change):
    from news_events.market_briefs import eligible
    p,s,_=env;eid=p.ingest(market(),NOW);event=deepcopy(s.event(eid)['body'])
    if change=='tickers':event['tickers']=['AAPL']
    elif change=='company_identity':event['company_identity']=[{'ticker':'AAPL'}]
    elif change=='cik':event['sources'][0]['cik']='320193'
    elif change=='source_tickers':event['sources'][0]['tickers']=['AAPL']
    elif change=='provider_tickers':event['sources'][0]['raw_metadata']['provider_tickers']=['AAPL']
    elif change=='rights':event['sources'][0]['rights']='internal_review'
    elif change=='conflict':event['conflicts']=['contradictory facts']
    elif change=='evidence':event['normalized_evidence']=[]
    elif change=='unmatched_title':event['sources'][0]['title']='Another report'
    elif change=='bad_url':event['sources'][0]['url']='https://user:secret@example.invalid/news'
    elif change=='bad_timestamp':event['sources'][0]['published_at']='missing'
    assert not eligible(event,low())


@pytest.mark.parametrize('title', [
    'Could gold rise tomorrow?', 'Why investors should watch inflation',
    'A vague market update with no explicit reported fact',
])
def test_long_excerpt_alone_is_not_a_factual_headline(env,title):
    p,s,_=env
    eid=p.ingest(market(title=title,source_excerpt='A lengthy financial excerpt with enough words for source context does not make this headline a factual report.'),NOW)
    assert not route(s.event(eid)['body'],low(),set(),set(),{},Policy(market_briefs_enabled=True))[0]


def test_strict_optin_and_company_low_importance_unchanged(env):
    p,s,_=env;eid=p.ingest(market(),NOW);event=s.event(eid)['body']
    for value in ('true',1,None):
        assert not route(event,low(),set(),set(),{},Policy(market_briefs_enabled=value))[0]
    eid=p.ingest(source(),NOW);event=s.event(eid)['body']
    assert route(event,low(),{'AAPL'},set(),{'AAPL'},Policy(market_briefs_enabled=True)) == ([], 'low_importance')


def test_brief_render_keeps_whole_reviewed_context_and_sanitized_source(env):
    from news_events.runtime import message
    p,s,_=env
    eid=p.ingest(market(url='https://example.invalid/news/12345?token=secret&utm_source=tracking&id=7'),NOW)
    event=s.event(eid)['body'];rendered=message(event,low(),'market_news',[])
    assert rendered.startswith('📰 עדכון שוק קצר\n\n')
    assert low()['title_he'] in rendered and low()['summary_he'] in rendered
    assert 'מקור: yahoo' in rendered and 'https://example.invalid/news/12345?id=7' in rendered
    assert 'secret' not in rendered and 'utm_' not in rendered
    assert 'פרשנות AI:' not in rendered and low()['interpretation_he'] not in rendered
    for materiality in ('medium','high'):
        ordinary=message(event,{**low(),'materiality':materiality},'market_news',[])
        assert ordinary.startswith('📰 '+low()['title_he']) and 'עדכון שוק קצר' not in ordinary


@pytest.mark.parametrize('hours', [-1,7])
def test_existing_queue_age_gates_hold_briefs_even_after_analysis(env,hours):
    p,s,_=env;p.policy=replace(p.policy,market_briefs_enabled=True)
    eid=p.ingest(market(),NOW);assert p.analyze(eid,lambda e:Analysis(low()),NOW)=='done'
    assert p.queue(eid,NOW+timedelta(hours=hours)) == []
    assert s.event(eid)['reason']=='stale_or_future'
