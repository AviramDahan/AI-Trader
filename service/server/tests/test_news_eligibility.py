from dataclasses import replace
from datetime import datetime, timezone
import pytest
from news_events.model import Source, IdentityResolver, event_type
from news_events.eligibility import sufficient_evidence
from news_events.engine import route, Policy

U = {'NVDA': {'company': 'Nvidia Corporation'}, 'AAPL': {'company': 'Apple Inc.'},
     'MEDP': {'company': 'Medpace Holdings Inc.'}, 'A': {'company': 'Agilent Technologies Inc.'},
     'IT': {'company': 'Gartner Inc.'}, 'ON': {'company': 'ON Semiconductor Corporation'}}

def source(title, tickers=(), excerpt=''):
    return Source('yahoo','id','https://example.com/article','Publisher','2026-09-28T07:00:00Z',
                  '2026-09-28T07:01:00Z',title,excerpt,tickers=tickers,rights='approved')

@pytest.mark.parametrize('title,ticker,basis', [
    ('Nvidia announces results','NVDA','verified_alias_plus_provider_ticker'),
    ('Medpace (MEDP) announces results','MEDP','company_name_plus_parenthesized_ticker'),
    ('Apple (AAPL) announces results','AAPL','company_name_plus_parenthesized_ticker')])
def test_supported_identity(title,ticker,basis):
    ids=IdentityResolver(U).resolve(source(title,(ticker,) if '(' not in title else ()))
    assert ids == [{'ticker':ticker,'company':U[ticker]['company'],'cik':'','basis':basis}]

@pytest.mark.parametrize('title,tickers', [('Big news today',('NVDA',)),('A big IT deal is ON',('A','IT','ON')),('Apple grows in the orchard',()),('Nvidia (AAPL) announces results',())])
def test_no_unverified_identity(title,tickers):
    assert IdentityResolver(U).resolve(source(title,tickers)) == []

@pytest.mark.parametrize('headline', [
 'Broker upgrades Nvidia to Buy', 'Broker cuts Nvidia price target to $150',
 'Nvidia wins major customer order', 'Nvidia announces financing',
 'Nvidia confirms data breach', 'Medpace clinical trial results meet endpoint',
 'FDA rejects Medpace drug', 'Nvidia CFO resigns', 'Nvidia announces restructuring',
 'Dell general counsel sells $2.33 million in shares', 'Nvidia announces debt issuance',
 'Nvidia announces reverse stock split', 'Nvidia announces supply-chain disruption',
 'Nvidia announces asset sale', 'Nvidia signs licensing deal'])
def test_event_categories(headline):
    assert event_type(headline,'') != 'unknown'

def event(title='Nvidia announces new contract', excerpt='Customer is Acme Robotics.'):
    s=source(title,('NVDA',),excerpt).data()
    return {'tickers':['NVDA'],'company_identity':[{'ticker':'NVDA','company':'Nvidia Corporation'}],
            'published_at':s['published_at'],'event_type':'business_update','sources':[s],
            'normalized_evidence':[{'text':title+' '+excerpt}]}

def test_combined_short_evidence():
    assert sufficient_evidence(event())

def test_short_excerpts_from_same_canonical_company_combine():
    e=event('Nvidia announces contract','Acme customer.')
    e['sources'].append(source('Nvidia contract announcement',('NVDA',),'Three years.').data())
    assert sufficient_evidence(e)

def test_vague_headline_and_unrelated_metadata_are_not_facts():
    e=event('Could Nvidia be the next big winner?','')
    e['sources'][0]['raw_metadata']={'untrusted':'huge contract'}
    assert not sufficient_evidence(e)
    assert not sufficient_evidence(event('Nvidia announces news',''))

def test_enrichment_completes_facts():
    e=event('Nvidia announces news','')
    assert not sufficient_evidence(e)
    e['sources'][0]['source_excerpt']='Nvidia reports revenue of $2 billion.'
    assert sufficient_evidence(e)

@pytest.mark.parametrize('held,relevance,materiality,expected', [
 (True,.65,'medium','portfolio_watchlist'),(False,.80,'high','important_stock_news'),
 (True,.64,'high',None),(True,.95,'low',None),(False,.79,'high',None)])
def test_neutral_routing_keeps_thresholds(held,relevance,materiality,expected):
    result={'related':True,'sentiment':'neutral','relevance':relevance,'materiality':materiality}
    routes,_=route({'tickers':['NVDA'],'event_type':'business_update'},result,{'NVDA'} if held else set(),set(),U,Policy())
    assert [t for t,_ in routes] == ([expected] if expected else [])
