"""Phase 2 only: isolated state, simulated providers/AI, NO Telegram sender."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest

from news_events.model import Source, canonical_url, IdentityResolver
from news_events.store import Store
from news_events.engine import Pipeline, Analysis
from news_events.providers import Config, RSSProvider, BenzingaProvider, TipRanksProvider, ExistingProvider, ProviderFailure, Transport, registry
from news_events.evidence import SECEvidence
from news_events.analysis import CanonicalAnalyzer
from news_events.reporting import report

NOW=datetime(2026,9,27,12,tzinfo=timezone.utc)
UNIVERSE={'AAPL':{'company':'Apple Inc.','cik':'320193'},'DELL':{'company':'Dell Technologies Inc.','cik':'1571996'},
          'HOOD':{'company':'Robinhood Markets, Inc.','cik':'1783879'},'A':{'company':'Agilent Technologies, Inc.'}}
SEC='https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/form4.xml'
FACTS='Apple Inc. announced financial results with revenue of 100 million dollars for the latest quarter and retained its prior guidance.'
RESULT=dict(related=True,title_he='אפל דיווחה על תוצאות כספיות',summary_he='החברה פרסמה את תוצאות הרבעון ושמרה על התחזית.',
            interpretation_he='ייתכן שהדיווח משפיע על החברה, אין זו המלצת מסחר.',sentiment='positive',materiality='high',relevance=.95)
REVIEW=dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,duplicate_of=0,material_new_fact=False,explanation='תקין')


@pytest.fixture
def env(tmp_path):
    path=tmp_path/'isolated.sqlite'
    def connect():
        c=sqlite3.connect(path,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
    store=Store(connect,sandbox=True);store.install()
    members=[{'AAPL'},set()]
    pipeline=Pipeline(store,UNIVERSE,lambda:members,not_before=NOW-timedelta(days=1))
    return pipeline,store,members


def source(provider='yahoo',**kw):
    args=dict(provider_id=provider,source_id='first',url=f'https://{provider}.example/articles/report-12345',
        publisher=provider,published_at=NOW.isoformat(),collected_at=NOW.isoformat(),title='Apple Inc. quarterly results',
        source_excerpt=FACTS,event_type='earnings',event_refs=(SEC,),rights='approved')
    args.update(kw);return Source(**args)


def rows(store,sql):
    with store.transaction() as c:return [dict(r) for r in c.execute(sql)]


def test_three_providers_one_event_one_analysis_job_and_no_duplicate_telegram(env):
    p,s,_=env;ids=[p.ingest(source(provider),NOW) for provider in ('sec','yahoo','benzinga','telegram')]
    assert len(set(ids))==1
    ai=Mock(return_value=Analysis(RESULT))
    for event in ids:p.analyze(event,ai,NOW)
    ai.assert_called_once()
    assert len(p.deliver_preview(ids[0],NOW))==1
    assert p.deliver_preview(ids[0],NOW)==[]
    assert len(rows(s,'SELECT * FROM ne_delivery'))==1
    assert len(s.event(ids[0])['body']['providers'])==4
    assert report(s,NOW)['analysis_jobs_avoided_by_identical_evidence']==3


def test_concurrent_analysis_claim_does_not_hold_database_over_ai(env):
    p,s,_=env;eid=p.ingest(source(),NOW);entered=threading.Event();release=threading.Event()
    def ai(event):
        entered.set();assert release.wait(5);return Analysis(RESULT)
    with ThreadPoolExecutor(2) as pool:
        future=pool.submit(p.analyze,eid,ai,NOW);assert entered.wait(5)
        with s.transaction(True) as c:s.metric(c,'probe','db_available',NOW.isoformat())
        assert p.analyze(eid,Mock(side_effect=AssertionError('duplicate')),NOW)=='running'
        release.set();assert future.result()=='done'


def test_material_update_new_version_not_duplicate(env):
    p,s,_=env;eid=p.ingest(source(),NOW);ai=Mock(return_value=Analysis(RESULT));p.analyze(eid,ai,NOW)
    p.deliver_preview(eid,NOW);before=s.event(eid)['evidence_version']
    update=source(source_excerpt=FACTS+' Revenue corrected to 120 million.',
                  claims={'revenue_millions':{'value':120,'quote':'Revenue corrected to 120 million.'}})
    assert p.ingest(update,NOW)==eid
    assert s.event(eid)['evidence_version']!=before
    assert p.analyze(eid,ai,NOW)=='done';assert ai.call_count==2
    assert len(p.deliver_preview(eid,NOW))==1


def test_date_formatting_and_provenance_only_do_not_rerun_ai(env):
    p,s,_=env;eid=p.ingest(source(),NOW);ai=Mock(return_value=Analysis(RESULT));p.analyze(eid,ai,NOW)
    p.ingest(source(collected_at=(NOW+timedelta(minutes=5)).isoformat(),source_excerpt='  '+FACTS+'  '),NOW)
    p.ingest(source('investing'),NOW);p.analyze(eid,ai,NOW)
    assert ai.call_count==1
    assert s.event(eid)['body']['published_at']==NOW.isoformat()


def test_source_revision_never_rejuvenates_original_event_publication(env):
    p,s,_=env;eid=p.ingest(source(),NOW)
    p.ingest(source(source_excerpt=FACTS+' A new official fact was added.',source_type='official/regulatory',
        published_at=(NOW+timedelta(minutes=30)).isoformat(),collected_at=(NOW+timedelta(minutes=30)).isoformat()),NOW+timedelta(minutes=30))
    assert s.event(eid)['body']['published_at']==NOW.isoformat()


def test_no_same_ticker_day_or_homepage_merging(env):
    p,s,_=env
    a=p.ingest(source(event_refs=('https://example.org/',)),NOW)
    b=p.ingest(source('other',source_excerpt=FACTS+' Another independent event occurred.',event_refs=('https://example.org/',)),NOW)
    assert a!=b


def test_source_conflict_preserved_primary_preferred_not_published(env):
    p,s,_=env
    a=source(claims={'revenue':{'value':100,'quote':'revenue of 100 million'}},source_type='official/regulatory')
    eid=p.ingest(a,NOW)
    p.ingest(source('telegram',source_excerpt=FACTS.replace('100','200'),claims={'revenue':{'value':200,'quote':'revenue of 200 million'}}),NOW)
    conflict=s.event(eid)['body']['conflicts'][0]
    assert conflict['preferred_primary_values']==['100']
    ai=Mock();assert p.analyze(eid,ai,NOW)=='blocked';ai.assert_not_called()
    assert p.deliver_preview(eid,NOW)==[]


def test_conflicting_numbers_detected_without_provider_structured_claims(env):
    p,s,_=env;eid=p.ingest(source(source_type='official/regulatory'),NOW)
    p.ingest(source('benzinga',source_excerpt=FACTS.replace('100','200')),NOW)
    assert s.event(eid)['reason']=='source_conflict'


def test_material_update_after_analysis_preserves_prior_delivery_but_cancels_stale_pending(env):
    p,s,_=env;eid=p.ingest(source(),NOW);p.analyze(eid,lambda e:Analysis(RESULT),NOW);p.queue(eid,NOW)
    p.ingest(source(source_excerpt=FACTS+' Additional business guidance was announced.',source_type='official/regulatory'),NOW)
    assert p.deliver_preview(eid,NOW)==[]
    assert rows(s,'SELECT status FROM ne_delivery')[0]['status']=='cancelled'


def test_paraphrase_without_proven_material_new_fact_does_not_trigger_extra_ai(env):
    p,s,_=env;eid=p.ingest(source(),NOW);ai=Mock(return_value=Analysis(RESULT));p.analyze(eid,ai,NOW)
    p.ingest(source('benzinga',source_excerpt='Apple Inc. published results for the latest financial quarter while maintaining guidance according to its public company announcement.'),NOW)
    assert p.analyze(eid,ai,NOW)=='needs_material_review';assert ai.call_count==1


def test_long_evidence_not_silently_truncated(env):
    p,s,_=env;eid=p.ingest(source(source_excerpt=FACTS*200),NOW);ai=Mock()
    assert p.analyze(eid,ai,NOW)=='evidence_budget_exceeded';ai.assert_not_called()


def test_secondary_reference_does_not_fuse_different_issuers(env):
    p,s,_=env;a=p.ingest(source(),NOW)
    b=p.ingest(source('other',title='Dell Technologies Inc. financial results',
        source_excerpt=FACTS.replace('Apple Inc.','Dell Technologies Inc.')),NOW)
    assert a!=b


def test_provider_concurrent_collect_is_leased(env):
    p,s,_=env;entered=threading.Event();release=threading.Event()
    provider=Mock(provider_id='leased',config=Config('leased','','leased'))
    def fetch(state,now):entered.set();assert release.wait(5);return {'items':[]}
    provider.fetch.side_effect=fetch
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(p.collect,[provider],NOW);assert entered.wait(5)
        p.collect([provider],NOW);assert provider.fetch.call_count==1
        release.set();assert first.result()['leased']['status']=='ok'


def test_evidence_failure_backoff_survives_restart(env):
    p,s,m=env;eid=p.ingest(source(source_excerpt='Apple Inc. Form 4'),NOW)
    fetch=Mock(side_effect=ProviderFailure('http_error',429,900))
    evidence=SECEvidence('test@example.invalid',fetch,lambda:NOW)
    assert not p.enrich(eid,[evidence],NOW)
    restarted=Pipeline(Store(s.connect,sandbox=True),UNIVERSE,lambda:m,not_before=p.not_before)
    assert not restarted.enrich(eid,[evidence],NOW+timedelta(minutes=1));assert fetch.call_count==1


@pytest.mark.parametrize('provider',['investing','benzinga','tipranks','sec_edgar','yahoo','telegram_channels'])
def test_source_neutral_portfolio_and_important_stock_routing(env,provider):
    p,s,m=env;eid=p.ingest(source(provider),NOW);p.analyze(eid,lambda e:Analysis(RESULT),NOW)
    assert p.queue(eid,NOW)==[('portfolio_watchlist',['AAPL'])]
    m[0]=set()
    assert p.queue(eid,NOW)==[('important_stock_news',['AAPL'])]
    previews=p.deliver_preview(eid,NOW)
    assert [r['topic'] for r in previews]==['important_stock_news']


def test_market_wide_without_ticker(env):
    p,s,_=env
    eid=p.ingest(source(title='Federal Reserve interest rates',source_excerpt='The Federal Reserve announced its latest interest rate decision at a public scheduled press conference today.',event_type='market',event_refs=()),NOW)
    p.analyze(eid,lambda e:Analysis({**RESULT,'sentiment':'neutral','materiality':'low'}),NOW)
    assert p.deliver_preview(eid,NOW)[0]['topic']=='market_news'


@pytest.mark.parametrize('changes,reason',[
    ({'title':'A company reports earnings','source_excerpt':'A company is in the news without any verified issuer name or exchange ticker.','tickers':('A',)},'identity_unverified'),
    ({'published_at':(NOW-timedelta(days=2)).isoformat()},'backlog_blocked'),
    ({'published_at':(NOW+timedelta(hours=1)).isoformat()},'stale_or_future'),
    ({'event_type':'unknown'},'unsupported_or_noise'),
    ({'source_excerpt':'Apple Inc. results'},'insufficient_information'),
    ({'rights':'review_required'},'license_required')])
def test_deterministic_skip_no_ai(env,changes,reason):
    p,s,_=env;eid=p.ingest(source(**changes),NOW);ai=Mock()
    p.analyze(eid,ai,NOW);ai.assert_not_called()
    assert s.event(eid)['body']['non_publication_reason']==reason


def test_provider_failure_isolation_retry_after_and_terminal(env):
    p,s,_=env
    healthy=Mock(provider_id='good',config=Config('good','','good'),normalize=lambda raw,now:source('good'))
    healthy.fetch.return_value={'items':[{}]}
    limited=Mock(provider_id='rate',config=Config('rate','','rate'))
    limited.fetch.side_effect=ProviderFailure('http_error',429,900)
    auth=Mock(provider_id='auth',config=Config('auth','','auth'))
    auth.fetch.side_effect=ProviderFailure('http_error',403,0,True)
    states=p.collect([healthy,limited,auth],NOW)
    assert states['good']['status']=='ok';assert states['rate']['status']=='rate_limited'
    assert states['rate']['next_at']==(NOW+timedelta(seconds=900)).isoformat()
    p.collect([limited,auth],NOW+timedelta(seconds=1))
    assert limited.fetch.call_count==1;assert auth.fetch.call_count==1
    limited.fetch.side_effect=None;limited.fetch.return_value={'items':[]}
    assert p.collect([limited],NOW+timedelta(seconds=901))['rate']['status']=='ok'


def test_restart_caches_analysis_and_delivery(env):
    p,s,m=env;eid=p.ingest(source(),NOW);p.analyze(eid,lambda e:Analysis(RESULT),NOW);p.deliver_preview(eid,NOW)
    restarted=Pipeline(Store(s.connect,sandbox=True),UNIVERSE,lambda:m,not_before=NOW-timedelta(days=1))
    restarted.store.install();ai=Mock()
    restarted.ingest(source('benzinga'),NOW);assert restarted.analyze(eid,ai,NOW)=='done'
    ai.assert_not_called();assert restarted.deliver_preview(eid,NOW)==[]


def test_interrupted_paid_call_not_blindly_retried(env):
    p,s,_=env;eid=p.ingest(source(),NOW);version=s.event(eid)['evidence_version']
    with s.transaction(True) as c:
        c.execute("INSERT INTO ne_analysis(event_id,version,status,started_at,owner) VALUES(?,?,'running',?,'crashed')",(eid,version,(NOW-timedelta(hours=1)).isoformat()))
    assert p.recover_interrupted(NOW)==1
    ai=Mock();assert p.analyze(eid,ai,NOW)=='interrupted_unknown';ai.assert_not_called()


def test_sec_evidence_for_other_discovery_source_cache_and_identity(env):
    from test_news_evidence import XML
    p,s,_=env;eid=p.ingest(source('investing',source_excerpt='Apple Inc. Form 4'),NOW)
    fetch=Mock(return_value=(XML,SEC))
    evidence=SECEvidence('AI-Trader test@example.invalid',fetch,lambda:NOW)
    assert p.enrich(eid,[evidence],NOW)
    assert not p.enrich(eid,[evidence],NOW)
    fetch.assert_called_once()
    event=s.event(eid)['body'];assert event['providers']==['investing','sec_evidence']
    assert event['published_at']==NOW.isoformat()
    assert 'price per share: 200' in str(event['normalized_evidence'])
    assert not evidence.can_handle({**event,'cik':['1571996']})


def test_quality_review_retained_one_job_per_event_no_nested_retry(env):
    p,s,_=env;eid=p.ingest(source(),NOW)
    client=Mock(side_effect=[(RESULT,{'model':'openai/gpt-6-luna','input_tokens':100,'output_tokens':40,'cost':.001}),
                             (REVIEW,{'model':'openai/gpt-6-luna','input_tokens':90,'output_tokens':30,'cost':.0009})])
    analyzer=CanonicalAnalyzer(client)
    assert p.analyze(eid,analyzer,NOW)=='done'
    p.ingest(source('benzinga'),NOW);p.analyze(eid,analyzer,NOW)
    assert client.call_count==2 # NOT one HTTP call: independent quality gate.
    r=report(s,NOW);assert r['billable_calls']==2;assert r['known_cost']==pytest.approx(.0019)


def test_terminal_quality_rejection_not_repeated_on_same_content(env):
    p,s,_=env;eid=p.ingest(source(),NOW)
    bad={**REVIEW,'faithful':False}
    client=Mock(side_effect=[(RESULT,{}),(bad,{}),(RESULT,{}),(bad,{})])
    ai=CanonicalAnalyzer(client)
    assert p.analyze(eid,ai,NOW)=='failed';assert client.call_count==4
    p.ingest(source('telegram'),NOW);p.analyze(eid,ai,NOW)
    assert client.call_count==4;assert p.deliver_preview(eid,NOW)==[]
    assert 'faithful' in s.event(eid)['reason']
    assert report(s,NOW)['calls_with_unknown_cost']==4


def test_strict_schema_extra_keys_and_ungrounded_numbers_fail(env):
    p,s,_=env;eid=p.ingest(source(),NOW)
    client=Mock(return_value=({**RESULT,'invented_extra_field':True},{}))
    assert p.analyze(eid,CanonicalAnalyzer(client),NOW)=='failed'
    assert client.call_count==1


def test_rss_atom_and_disabled_license_config():
    cfg=Config('rss','https://feed.example/rss','Publisher',enabled=True,rights='internal_review')
    transport=Mock();transport.request.return_value=b'<rss><channel><item><guid>1</guid><title>Apple Inc. earnings</title><link>https://source.example/articles/12345?utm_source=test</link><pubDate>Sun, 27 Sep 2026 12:00:00 GMT</pubDate><description>Source excerpt only.</description></item></channel></rss>'
    adapter=RSSProvider(cfg,transport);raw=adapter.fetch({},NOW)['items'][0];event=adapter.normalize(raw,NOW)
    assert event.url=='https://source.example/articles/12345';assert event.published_at==NOW.isoformat()
    with pytest.raises(ProviderFailure,match='disabled'):RSSProvider(replace(cfg,enabled=False),transport).fetch({},NOW)
    with pytest.raises(ProviderFailure,match='license_required'):RSSProvider(replace(cfg,rights='review_required'),transport).fetch({},NOW)
    transport.request.return_value=b'<!DOCTYPE rss><rss/>'
    with pytest.raises(ProviderFailure,match='unsafe_xml'):adapter.fetch({},NOW)


def test_benzinga_official_contract_and_tipranks_configured_contract():
    transport=Mock();transport.request.return_value=json.dumps([{'id':1,'title':'Apple Inc. earnings','url':'https://news.example/articles/12345',
        'created':'Sun, 27 Sep 2026 12:00:00 GMT','updated':'Sun, 27 Sep 2026 12:01:00 GMT','body':FACTS,'stocks':[{'name':'AAPL'}]}]).encode()
    cfg=Config('benzinga','https://api.benzinga.com/api/v2/news','Benzinga',enabled=True,rights='approved',credential='fixture-only')
    adapter=BenzingaProvider(cfg,transport);fetched=adapter.fetch({'cursor':NOW.isoformat()},NOW)
    assert adapter.normalize(fetched['items'][0],NOW).tickers==('AAPL',)
    assert transport.request.call_args.args[1]['updatedSince']==int(NOW.timestamp())-300
    assert 'tickers' not in transport.request.call_args.args[1]
    missing=TipRanksProvider(replace(cfg,provider_id='tipranks'),transport)
    with pytest.raises(ProviderFailure,match='enterprise_contract_required'):missing.fetch({},NOW)
    contract={'auth_header':'Authorization','auth_prefix':'Bearer ','items_field':'news','cursor_param':'cursor',
        'next_cursor_field':'next','fields':{'id':'identifier','title':'headline','excerpt':'summary','url':'url','published_at':'time'}}
    transport.request.return_value=json.dumps({'news':[{'identifier':'t1','headline':'Apple Inc. earnings','summary':FACTS,
        'url':'https://example.org/articles/12345','time':NOW.isoformat()}],'next':'next1'}).encode()
    adapter=TipRanksProvider(replace(cfg,provider_id='tipranks'),transport,contract)
    assert adapter.fetch({},NOW)['cursor']=='next1'


@pytest.mark.parametrize('endpoint',['http://feed.example/rss','https://127.0.0.1/rss','https://feed.example:444/rss','https://user:pass@feed.example/rss'])
def test_transport_rejects_unsafe_targets_without_network(endpoint):
    with pytest.raises(ProviderFailure,match='unsafe_endpoint'):Transport(['feed.example']).request(endpoint)


def test_legacy_adapters_normalize_without_source_specific_routing():
    cfg=Config('telegram_channels','https://example.org','Telegram',enabled=True,rights='approved')
    collector=Mock(return_value={'items':[{'url':'https://example.org/articles/12345','title':'Apple Inc. earnings',
        'source_excerpt':FACTS,'published_at':NOW.isoformat(),'verified_tickers':['AAPL']}],'coverage':{'kind':'shared_feed'}})
    adapter=registry([cfg],{'telegram_channels':collector})[0]
    event=adapter.normalize(adapter.fetch({},NOW)['items'][0],NOW)
    assert event.source_excerpt==FACTS;assert event.tickers==('AAPL',)


def test_scanner_union_identity_uses_shared_official_cik_mapping():
    from news_events.bridge import scanner_identity_catalog,effective_policy
    universe=scanner_identity_catalog({'members':{'AAPL':{'company':'Apple Inc.','indexes':['S&P 500','Nasdaq-100']}}},
        {'all_cik_to_tickers':{'0000320193':['AAPL'],'0000000010':['OUTSIDE']}})
    assert list(universe)==['AAPL'];assert universe['AAPL']['cik']=='320193'
    policy=effective_policy({'alert_min_relevance':.7,'broad_alert_min_relevance':.85},.6,6,6,168)
    assert policy.personal_relevance==.7;assert policy.stock_relevance==.85


def test_existing_collector_checkpoint_etag_survives_restart(env):
    p,s,_=env
    collector=Mock(return_value={'items':[],'checkpoint':{'offset':12},'etag':'test-etag','status':'not_modified'})
    provider=ExistingProvider(Config('legacy','','official',enabled=True,rights='approved'),collector)
    p.collect([provider],NOW);p.collect([provider],NOW+timedelta(minutes=6))
    saved=collector.call_args.args[0]
    assert json.loads(saved['checkpoint_json'])=={'offset':12};assert saved['etag']=='test-etag'


def test_naive_source_timestamp_is_not_invented():
    cfg=Config('investing','https://www.investing.com/rss/news.rss','Investing')
    raw={'id':'i1','title':'Apple Inc. earnings','excerpt':FACTS,'url':'https://example.org/articles/12345',
         'published_at':'2026-09-27 14:48:32'}
    with pytest.raises(ValueError,match='source_timezone_missing'):RSSProvider(cfg).normalize(raw,NOW)


def test_entire_invalid_feed_is_not_reported_healthy(env):
    p,s,_=env
    provider=Mock(provider_id='invalid',config=Config('invalid','','invalid'))
    provider.fetch.return_value={'items':[{},{}]};provider.normalize.side_effect=ValueError('source_timezone_missing')
    state=p.collect([provider],NOW)['invalid']
    assert state['status']=='requires_configuration';assert state['invalid_items']==2
    p.collect([provider],NOW+timedelta(hours=1));assert provider.fetch.call_count==1


def test_production_schema_cannot_be_installed(tmp_path):
    path=tmp_path/'legacy.sqlite'
    def connect():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    c=connect();c.execute('CREATE TABLE scanner_trades(id INT)');c.commit();c.close()
    with pytest.raises(ValueError,match='production_sqlite_forbidden'):Store(connect,sandbox=True).install()
