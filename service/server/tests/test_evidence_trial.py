from copy import deepcopy
import pytest
from news_events.evidence_trial import assess


def event(title,kind='product',provider='yahoo_priority',excerpt=''):
    return {'company_identity':[{'ticker':'LOW','company':"Lowe's Companies"}],
      'tickers':['LOW'],'event_type':kind,'sources':[{'provider_id':provider,
      'title':title,'source_excerpt':excerpt,'tickers':['LOW'],'publisher':'Verified publisher',
      'rights':'approved','source_type':'aggregator','url':'https://example.com/story',
      'published_at':'2026-09-28T00:00:00Z'}]}


@pytest.mark.parametrize('title,kind',[
 ("Lowe's Companies starts 20 minute drone delivery pilot",'product'),
 ("Lowe's Companies raises FY guidance",'guidance'),
 ("Lowe's Companies appoints Jane Smith as CEO",'management'),
 ("Lowe's Companies announces $500 million buyback",'buyback'),
])
def test_specific_title_is_minimum_evidence(title,kind):
    assert assess(event(title,kind))['eligible']


@pytest.mark.parametrize('title',[
 "Why investors are watching Lowe's Companies", "Lowe's Companies could launch drone delivery pilot",
 "Lowe's Companies ready for a big move", "Lowe's Companies launches drone delivery pilot?",
])
def test_headline_noise_fails(title):
    assert not assess(event(title))['eligible']


def test_long_excerpt_not_enough_without_factual_event():
    e=event("Lowe's Companies",excerpt='These are many words about a company and investor interest without any specific event at all.')
    assert not assess(e)['eligible']


def test_combined_canonical_source_metadata_and_excerpt():
    e=event("Lowe's Companies update")
    alternate=deepcopy(e['sources'][0]);alternate.update(provider_id='globenewswire',
      url='https://example.com/release',title='Company announcement',source_excerpt='Starts a drone delivery pilot.')
    e['sources'].append(alternate)
    r=assess(e)
    assert r['eligible'] and r['evidence_used'][0]['provider']=='globenewswire'
    assert r['flags']['distinct_source_urls']==2


def test_investing_title_only_requires_alternate_evidence():
    e=event("Lowe's Companies starts drone delivery pilot",provider='investing')
    assert not assess(e)['eligible']
    e['sources'].append(event("Lowe's Companies starts drone delivery pilot")['sources'][0])
    assert assess(e)['eligible']


def test_telegram_relay_alone_fails():
    assert not assess(event("Lowe's Companies starts drone delivery pilot",provider='telegram_channels'))['eligible']


@pytest.mark.parametrize('field,value',[('publisher',''),('published_at','invalid'),('rights','denied')])
def test_source_provenance_required(field,value):
    e=event("Lowe's Companies starts drone delivery pilot");e['sources'][0][field]=value
    assert not assess(e)['eligible']


def test_identity_and_classification_still_required():
    e=event("Lowe's Companies starts drone delivery pilot");e['company_identity']=[]
    assert not assess(e)['eligible']


def test_unquoted_structured_claim_does_not_invent_evidence():
    e=event("Lowe's Companies update")
    e['sources'][0]['claims']={'pilot':{'value':'drone','quote':'Starts a drone delivery pilot.'}}
    assert not assess(e)['eligible']
    e=event("Lowe's Companies starts drone delivery pilot",kind='unknown')
    assert not assess(e)['eligible']


def test_duplicate_observation_is_not_independent_confirmation():
    e=event("Lowe's Companies starts drone delivery pilot")
    e['sources'].append(deepcopy(e['sources'][0]))
    assert assess(e)['flags']['distinct_source_urls']==1


def test_rss_preserves_description_and_encoded_content():
    from datetime import datetime,timezone
    from unittest.mock import Mock
    from news_events.providers import RSSProvider,Config
    xml=b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>
    <title>Company announcement</title><link>https://example.com/story</link>
    <pubDate>Mon, 28 Sep 2026 07:00:00 GMT</pubDate>
    <description>Short official excerpt.</description><content:encoded>Additional official details.</content:encoded>
    </item></channel></rss>'''
    p=RSSProvider(Config('globenewswire','https://example.com/rss','GlobeNewswire',enabled=True,rights='approved'),Mock(request=Mock(return_value=xml)))
    raw=p.fetch({},datetime.now(timezone.utc))['items'][0]
    assert 'Short official excerpt.' in raw['excerpt'] and 'Additional official details.' in raw['excerpt']
