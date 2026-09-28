"""News policy tests: isolated DB, fake AI, no public delivery."""
from dataclasses import replace
from unittest.mock import Mock
import pytest
from news_events.engine import Policy, route, Analysis
from news_events.model import event_type
from news_events.factual_evidence import factual_title
from test_news_events import env, source, NOW, RESULT


@pytest.mark.parametrize('topic,tickers,held,relevance,materiality,allowed',[
    ('portfolio_watchlist',['AAPL'],{'AAPL'},.55,'medium',True),
    ('portfolio_watchlist',['AAPL'],{'AAPL'},.54,'medium',False),
    ('portfolio_watchlist',['AAPL'],{'AAPL'},.9,'low',False),
    ('important_stock_news',['AAPL'],set(),.70,'medium',True),
    ('important_stock_news',['AAPL'],set(),.69,'high',False),
    ('market_news',[],set(),.40,'medium',True),
    ('market_news',[],set(),.39,'high',True),
    ('market_news',[],set(),.30,'medium',True),
    ('market_news',[],set(),.29,'high',False),
])
def test_boundaries(topic,tickers,held,relevance,materiality,allowed):
    event=dict(tickers=tickers,event_type='market' if not tickers else 'earnings')
    routes,_=route(event,{**RESULT,'sentiment':'neutral','relevance':relevance,'materiality':materiality},held,set(),{'AAPL'},Policy())
    assert (topic in [r[0] for r in routes])==allowed


@pytest.mark.parametrize('title,stock',[
    ('Apple Inc. announces $500M buyback',True),
    ('China cuts tariffs on U.S. agricultural goods',False),
    ('Oil rises above $107 as Hormuz tensions continue',False),
])
def test_factual_title_one_job_one_delivery(env,title,stock):
    p,s,_=env
    item=source(title=title,source_excerpt='',event_type=event_type(title,''),event_refs=())
    eid=p.ingest(item,NOW)
    assert factual_title(s.event(eid)['body'])
    ai=Mock(return_value=Analysis(RESULT))
    assert p.analyze(eid,ai,NOW)=='done'
    p.deliver_preview(eid,NOW)
    assert p.ingest(replace(item,provider_id='direct',source_id='copy'),NOW)==eid
    p.analyze(eid,ai,NOW)
    assert p.deliver_preview(eid,NOW)==[]
    ai.assert_called_once()


@pytest.mark.parametrize('title',[
    'Is GE still the best stock to own?', 'Why investors should watch Tesla',
    '3 stocks that could explode', 'Could Apple be ready for a rally?',
])
def test_opinion_not_classified(title):
    assert event_type(title,'earnings guidance')=='unknown'


@pytest.mark.parametrize('title',[
    'KeyBanc upgrades First Solar','GM warns of heightened U.S. competition',
    'Starbucks to close select stores and cuts outlook',
    'Apple Inc. announces financing','Apple Inc. reports data breach',
    'Apple Inc. appoints new CEO','Company reports clinical trial results',
    'Company announces restructuring','Company wins major contract',
])
def test_real_event_classification(title):
    assert event_type(title,'')!='unknown'


def test_secondary_mention_cannot_use_title_path(env):
    p,s,_=env
    item=source(title='Competitor launches product challenging Apple Inc.',source_excerpt='',event_type='business_update')
    eid=p.ingest(item,NOW)
    assert not factual_title(s.event(eid)['body'])
    ai=Mock()
    assert p.analyze(eid,ai,NOW)=='insufficient_information'
    ai.assert_not_called()


@pytest.mark.parametrize('rights',['review_required','internal_review'])
def test_unapproved_title_not_evidence(env,rights):
    p,s,_=env
    eid=p.ingest(source(title='Apple Inc. announces buyback',source_excerpt='',rights=rights),NOW)
    assert not factual_title(s.event(eid)['body'])
