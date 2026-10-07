import pytest
from unittest.mock import Mock,patch
from news_events.model import Source,IdentityResolver
from news_events.yahoo_metadata import normalize_news

U={'SBUX':{'company':'Starbucks Corporation'},'LOW':{'company':"Lowe's"},'NVDA':{'company':'Nvidia Corporation'},'TSLA':{'company':'Tesla, Inc.'},'A':{'company':'Agilent Technologies'},'IT':{'company':'Gartner'},'ON':{'company':'ON Semiconductor'},'GS':{'company':'Goldman Sachs'}}
def resolve(title,hints,provider='yahoo_priority'):
 s=Source(provider,'x','https://example.com/article','Publisher','2026-09-28T00:00:00Z','2026-09-28T00:01:00Z',title,'',tickers=tuple(hints),raw_metadata={'provider_tickers':hints})
 return [r['ticker'] for r in IdentityResolver(U).resolve(s)]

@pytest.mark.parametrize('title,hints,expected',[
 ('Starbucks cuts outlook',['SBUX'],['SBUX']),
 ("Lowe's Companies (LOW) starts pilot",['LOW'],['LOW']),
 ('Nvidia wins contract',['NVDA'],['NVDA']),
 ('$NVDA wins contract',['NVDA'],['NVDA']),
 ('NASDAQ:NVDA wins contract',['NVDA'],['NVDA']),
 ('Broad market report includes Tesla and Nvidia',['TSLA','NVDA'],[]),
 ('Starbucks rival closes locations',['SBUX'],[]),
 ('Starbucks vs Nvidia comparison',['SBUX','NVDA'],[]),
 ('A new product is ON its way IT seems',['A','ON','IT'],[]),
 ('Goldman Sachs upgrades Nvidia stock rating',['GS','NVDA'],['NVDA']),
 ('Nvidia wins contract',[],[]),
 ('General market news',['NVDA'],[]),
])
def test_primary_subject_with_structured_hint(title,hints,expected):
 assert resolve(title,hints)==expected

def test_non_yahoo_keeps_existing_identity_behavior():
 assert resolve('Nvidia wins contract',['NVDA'],'investing')==[]

def test_shared_news_fields_unchanged_and_scanner_provenance_preserved():
 from stock_scanner import fetch_recent_news
 payload={'news':[{'title':'Nvidia announces results','publisher':'Publisher','link':'https://example.com/story','providerPublishTime':1000,'relatedTickers':['NVDA','TSLA'],'summary':'Explicit source summary.'}]}
 session=Mock();session.get.return_value.json.return_value=payload
 with patch('stock_scanner.requests.Session',return_value=session),patch('stock_scanner.time.time',return_value=1001):old=fetch_recent_news('NVDA','Nvidia Corporation',168)
 new=normalize_news(payload,'NVDA','Nvidia Corporation',168,1001)
 assert new[0]['provider_tickers']==['NVDA','TSLA']
 metadata={'provider_tickers','tickers','relatedTickers','original_url','provenance'}
 assert [{k:v for k,v in r.items() if k not in metadata} for r in new]==[{k:v for k,v in r.items() if k not in metadata} for r in old]
 assert old[0]['relatedTickers']==['NVDA','TSLA'] and old[0]['original_url']==payload['news'][0]['link']
 assert old[0]['provenance']==[{'ingestion_provider':'scanner_yahoo','original_url':payload['news'][0]['link'],
   'publisher':'Publisher','published_at':old[0]['published_at']}]
 from news_events.providers import ExistingProvider,Config
 from datetime import datetime,timezone
 s=ExistingProvider(Config('yahoo_priority','','Publisher',rights='approved'),lambda *_:{}).normalize({**new[0],'id':new[0]['url'],'excerpt':new[0]['source_excerpt']},datetime.now(timezone.utc))
 assert s.raw_metadata['provider_tickers']==['NVDA','TSLA']
 assert s.publisher=='Publisher' and s.source_excerpt=='Explicit source summary.'
