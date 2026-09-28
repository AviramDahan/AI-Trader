from datetime import datetime,timezone
from unittest.mock import Mock, patch
import pytest
from news_events.providers import RSSProvider,Config
from news_events.model import IdentityResolver,Source,event_type
from news_events.yahoo_metadata import normalize_news


def test_globe_stock_categories_preserved_us_only_and_publisher_namespace():
    xml=b'''<rss xmlns:dc="http://dublincore.org/documents/dcmi-namespace/"><channel><item>
    <title>Nvidia announces results</title><link>https://example.com/article</link>
    <pubDate>Mon, 28 Sep 2026 07:00:00 GMT</pubDate><dc:publisher>Nvidia Corporation</dc:publisher>
    <category domain="https://www.globenewswire.com/rss/stock">NASDAQ:NVDA</category>
    <category domain="https://www.globenewswire.com/rss/stock">Copenhagen:FLS</category>
    <category>NYSE:FAKE</category><dc:subject>Results</dc:subject></item></channel></rss>'''
    p=RSSProvider(Config('globenewswire','https://example.com/rss','GlobeNewswire',enabled=True,rights='approved'),Mock(request=Mock(return_value=xml)))
    raw=p.fetch({},datetime.now(timezone.utc))['items'][0]
    s=p.normalize(raw,datetime.now(timezone.utc))
    assert s.tickers==('NVDA',) and s.publisher=='Nvidia Corporation'
    assert s.raw_metadata['subjects']==['Results'] and s.raw_metadata['exchanges']==['NASDAQ']
    assert IdentityResolver({'NVDA':{'company':'Nvidia Corporation'}}).resolve(s)

def test_yahoo_related_tickers_survive_but_query_quote_is_not_article_identity():
    raw={'quotes':[{'symbol':'DELL','longname':'Dell Technologies'}],'news':[{'title':'HP announces new contract','link':'https://example.com/article','providerPublishTime':1000,'relatedTickers':['HPQ','DELL']}]}
    rows=normalize_news(raw,'DELL','Dell Technologies',168,1001)
    assert rows[0]['provider_tickers']==['HPQ','DELL']
    assert 'company' not in rows[0]
    assert 'source_excerpt' not in rows[0]


def test_yahoo_news_adapter_preserves_scanner_contract_without_changing_scanner():
    from stock_scanner import fetch_recent_news
    payload={'news':[{'title':'Dell announces a contract','publisher':'Example',
        'link':'https://example.com/article','providerPublishTime':1000,
        'relatedTickers':['DELL','IBM'],'summary':'Explicit provider summary.'}]}
    session=Mock()
    session.get.return_value.json.return_value=payload
    with patch('stock_scanner.requests.Session',return_value=session), patch('stock_scanner.time.time',return_value=1001):
        original=fetch_recent_news('DELL','Dell Technologies',168)
    enriched=normalize_news(payload,'DELL','Dell Technologies',168,1001)
    assert [{k:v for k,v in row.items() if k not in ('provider_tickers','tickers')} for row in enriched]==original

@pytest.mark.parametrize('title,excerpt,expected', [
 ('Nvidia announces new factory','Apple Inc. is a customer.', ['NVDA']),
 ('Seattle tower across from Amazon sold for $12 million','',['']),
 ('Evereve hires Target executive','', ['']),
 ('Goldman Sachs upgrades Nvidia stock rating','',['NVDA']),
 ('Nvidia: Goldman Sachs raises price target','',['NVDA']),
])
def test_primary_subject_not_incidental(title,excerpt,expected):
    universe={'NVDA':{'company':'Nvidia Corporation'},'AAPL':{'company':'Apple Inc.'},'AMZN':{'company':'Amazon'},'TGT':{'company':'Target Corporation'},'GS':{'company':'Goldman Sachs'}}
    s=Source('yahoo','id','https://example.com/article','Yahoo','2026-09-28T00:00:00Z','2026-09-28T00:01:00Z',title,excerpt,tickers=tuple(universe),rights='approved')
    assert [i['ticker'] for i in IdentityResolver(universe).resolve(s)]==([] if expected==[''] else expected)

@pytest.mark.parametrize('title,kind', [
 ("Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot",'product'),
 ('GE Aerospace Ships Redesigned Engines to Boeing','product'),
 ('S&P Global Expands into Onchain Finance with OpenZeppelin Deal','business_update'),
 ('Amgen Sells its Deerfield Campus for $151 Million','asset_sale'),
 ('General Motors warns of heightened U.S. competition','business_risk')])
def test_observed_classifier_gaps(title,kind):
    assert event_type(title,'')==kind
