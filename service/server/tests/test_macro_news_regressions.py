from unittest.mock import Mock
from datetime import timedelta
import pytest
from news_events.model import event_type
from news_events.factual_evidence import sufficient
from news_events.engine import Analysis
from test_news_events import env,source,NOW,RESULT

SOFR='Secured overnight financing rate: 3.90% September 25th vs 3.88% September 24th|FJ'
TALKS='Mediators Expected To Hold Separate Talks With US And Iran On Monday Or Tuesday, With Iran\'s Araqchi And Qatari Mediators Remaining In US - Official Briefed On The Negotiations To RTRS'
BOE='Bank of England’s Ramsden says rates may need to rise if inflation pressures build'
CITI='October Fed meeting hinges on this key economic data, Citi says'


@pytest.mark.parametrize('title',[SOFR,TALKS,BOE,
    "ECB's President Lagarde: The inflation outlook will be higher in 2027 and 2028 than we expected a few months ago.|FJ",
    'U.S. TWO-YEAR TREASURY YIELD REACHES 4.952%, HIGHEST SINCE MAY 2024',
    'Russia plans to extend diesel export ban through october - Tass|FJ',
    'Russia Said To Be Preparing Document To Extend Diesel Export Ban For Another Month – TASS'])
def test_real_headlines_eligible_without_identity_or_excerpt(env,title):
    p,s,_=env
    assert event_type(title,'')=='market'
    item=source(title=title,source_excerpt='',event_type=event_type(title,''),event_refs=())
    eid=p.ingest(item,NOW)
    assert s.event(eid)['status']=='pending'
    assert sufficient(s.event(eid)['body'])
    ai=Mock(return_value=Analysis({**RESULT,'sentiment':'neutral','relevance':.4}))
    assert p.analyze(eid,ai,NOW)=='done'
    assert p.queue(eid,NOW)==[('market_news',[])]
    assert ai.call_args.args[0]['title']==title  # uncertainty and numbers unchanged
    p.analyze(eid,ai,NOW);ai.assert_called_once()


def test_vague_citi_title_remains_insufficient(env):
    p,s,_=env
    eid=p.ingest(source(title=CITI,source_excerpt='',event_type=event_type(CITI,'')),NOW)
    ai=Mock()
    assert p.analyze(eid,ai,NOW)=='insufficient_information'
    ai.assert_not_called()


@pytest.mark.parametrize('title',[
    'Company announces financing tied to SOFR',
    'SOFR-linked financing announced by Company',
    'Company to hold talks with US customers about Iran',
    'Iran reaches out to Arab states',
    'Could US and Iran hold talks with mediators?',
])
def test_not_every_sofr_or_geopolitics_mention_is_macro(title):
    assert event_type(title,'')!='market'


def test_stale_and_backlog_still_never_call_ai(env):
    p,s,_=env
    eid=p.ingest(source(title=SOFR,source_excerpt='',event_type='market',published_at=(NOW-timedelta(days=2)).isoformat()),NOW)
    ai=Mock()
    assert p.analyze(eid,ai,NOW)=='blocked'
    assert s.event(eid)['reason']=='backlog_blocked'
    assert p.queue(eid,NOW)==[]
    ai.assert_not_called()


@pytest.mark.parametrize('title',[
    "WATCH LIVE: ECB President Lagarde speaks",
    "ECB's President Lagarde: He was great",
    "ECB's President Lagarde: We discussed the inflation outlook",
    'Trump: Kim is my friend',
    'Trump: Discussed locations for data centers',
    'Could Apple agree to buy a startup?',
    '3 stocks to buy before the Fed cuts rates',
    'Russia may consider changes to diesel exports',
    'Russia plans to extend diesel export ban',
])
def test_noise_does_not_gain_factual_title_evidence(env,title):
    p,s,_=env
    eid=p.ingest(source(title=title,source_excerpt='',event_type=event_type(title,''),event_refs=()),NOW)
    assert not sufficient(s.event(eid)['body'])


@pytest.mark.parametrize('title,expected',[
    ('$BA | FAA To Delay Approval Of Boeing MAX 10 While Studying Software Issue','regulatory'),
    ('AMD agrees to buy World Labs AI startup for $8.2b. $AMD|FJ','merger'),
])
def test_observed_business_classification(title,expected):
    assert event_type(title,'')==expected


def test_corporate_outlook_not_misclassified_as_central_bank():
    assert event_type('Apple Inc. raises guidance despite higher inflation','')=='guidance'
