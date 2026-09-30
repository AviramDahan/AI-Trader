import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from news_source_metadata import retain


def test_raw_hints_remain_hints_and_first_observation_is_immutable():
    first=retain({'title':'Original','provider_tickers':['AAPL'],'relatedTickers':['AAPL'],
                  'publisher':'Publisher','summary':'Supplied summary','source_excerpt':'Supplied summary',
                  'api_key':'DO NOT COPY','tickers':['INVALID_VERIFICATION']},collected_at='first')
    later=retain({'title':'Changed','provider_tickers':['AMD'],'source_excerpt':''},first,collected_at='later')
    assert later['first_observation']['provider_tickers']==['AAPL']
    assert later['first_observation']['collected_at']=='first'
    assert later['source_excerpt']==''
    assert 'api_key' not in first and 'tickers' not in first
    assert first['summary']=='Supplied summary'


def test_same_title_missing_excerpt_keeps_original_evidence():
    old=retain({'title':'Original','source_excerpt':'Original summary'},collected_at='first')
    new=retain({'title':'Original','source_excerpt':''},old,collected_at='next')
    assert new['source_excerpt']=='Original summary'


def test_malformed_hints_do_not_create_tickers():
    assert retain({'relatedTickers':'AAPL','provider_tickers':None},collected_at='now')['relatedTickers']==[]


def test_source_url_does_not_persist_credentials():
    data=retain({'original_url':'https://example.com/story?id=123&token=SECRET#SECRET',
                 'url':'https://user:SECRET@example.com/story'},collected_at='now')
    assert data['original_url']=='https://example.com/story?id=123'
    assert 'url' not in data
    assert 'SECRET' not in str(data)
