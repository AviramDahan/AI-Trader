"""Synthetic decision-time evidence only; no external providers or production."""
import copy
import gzip
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import stock_scanner as scanner
import scanner_targets as targets
import signal_news
import final_ai
import signal_research

NOW = datetime(2026, 10, 5, 20, 8, tzinfo=timezone.utc)


class Clock(datetime):
    instant = NOW
    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


def history():
    dates = pd.bdate_range(end='2026-10-05', periods=80)
    values = [100+i*.8 for i in range(80)]
    return pd.DataFrame(dict(Open=values,High=[x+2 for x in values],Low=[x-2 for x in values],
        Close=values,Volume=[1000000]*80),index=dates)


@pytest.fixture
def clock(monkeypatch):
    Clock.instant = NOW
    monkeypatch.setattr(scanner, 'datetime', Clock)
    monkeypatch.setattr(targets, 'datetime', Clock)
    monkeypatch.setattr(signal_news, 'datetime', Clock)
    monkeypatch.setattr(scanner.time, 'time', lambda: Clock.instant.timestamp())
    yield Clock
    Clock.instant = NOW


@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DATABASE_URL','')
    monkeypatch.setattr(database,'_SQLITE_DB_PATH',str(tmp_path/'isolated.db'))
    database.init_database()
    with database.get_db_connection() as c:
        c.executescript((Path(targets.__file__).parent/'news_events/schema.sql').read_text())
    return tmp_path


def canonical_fixture():
    source=dict(provider_id='prnewswire',source_id='synthetic',url='https://example.test/story',publisher='Official Wire',
        published_at='2026-10-05T18:00:00+00:00',collected_at='2026-10-05T18:01:00+00:00',
        title='Synthetic Corporation announces a new factory opening',
        source_excerpt='Synthetic Corporation announces a new factory opening with production scheduled for the next fiscal quarter.',
        source_type='rss',tickers=['TEST'],cik='123',event_type='business_update',rights='approved')
    event=dict(tickers=['TEST'],company_identity=[dict(ticker='TEST',company='Synthetic Corporation',cik='123',basis='cik')],
        title=source['title'],event_type='business_update',sources=[source],conflicts=[],
        normalized_evidence=[dict(text=source['source_excerpt'],claims={})])
    return dict(event_id='synthetic-event',status='analyzed',reason='low_importance',evidence_version='synthetic-version',
        created_at=source['collected_at'],updated_at=source['collected_at'],body_json=json.dumps(event))


def seed_canonical(conn):
    row=canonical_fixture()
    conn.execute('INSERT INTO ne_events(event_id,body_json,evidence_version,status,reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
        tuple(row[k] for k in ('event_id','body_json','evidence_version','status','reason','created_at','updated_at')))
    conn.commit()


def test_cached_partial_daily_never_becomes_completed(clock,tmp_path,monkeypatch):
    file=tmp_path/'old.gz';partial=history()
    fetched=datetime(2026,10,5,15,20,tzinfo=timezone.utc).timestamp()
    with gzip.open(file,'wt') as stream:
        json.dump(dict(schema=1,fetched_at=fetched,histories={'TEST':partial.to_json(orient='split',date_format='iso')}),stream)
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',file)
    cached,_=scanner._read_history_cache()
    assert cached['TEST'].index[-1].date().isoformat()=='2026-10-02'
    assert targets.single_source_structure(cached['TEST'])['data_as_of']=='2026-10-02'
    # The frozen pre-close observation must not be reclassified at midnight.
    clock.instant=datetime(2026,10,6,15,tzinfo=timezone.utc)
    assert targets.single_source_structure(cached['TEST'])['data_as_of']=='2026-10-02'


def test_completed_session_triggers_refresh_before_ttl(clock,tmp_path,monkeypatch):
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',tmp_path/'cache.gz')
    fetched=datetime(2026,10,5,15,20,tzinfo=timezone.utc).timestamp()
    old=scanner._finalize_download(history(),fetched)
    scanner._write_history_cache({'TEST':old},fetched)
    network=Mock(return_value={'TEST':history()})
    monkeypatch.setattr(scanner,'_download_history',network)
    frames,info=scanner.load_historical_data(['TEST'],scanner.settings())
    assert network.call_args.args==(['TEST'],)
    assert info['status']=='incremental_refresh' and frames['TEST'].index[-1].date().isoformat()=='2026-10-05'
    scanner.load_historical_data(['TEST'],scanner.settings())
    assert network.call_count==1


def test_partial_refresh_preserves_per_symbol_observation(clock,tmp_path,monkeypatch):
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',tmp_path/'cache.gz')
    old_stamp=datetime(2026,10,2,20,10,tzinfo=timezone.utc).timestamp()
    old=scanner._finalize_download(history().iloc[:-1],old_stamp)
    new=scanner._finalize_download(history(),NOW.timestamp())
    scanner._write_history_cache({'OLD':old,'NEW':new},NOW.timestamp())
    restored,_=scanner._read_history_cache()
    assert restored['OLD'].attrs['history_fetched_at']==old_stamp
    assert restored['NEW'].attrs['history_fetched_at']==NOW.timestamp()


def test_history_partial_fallback_reports_only_lagging_symbols_without_changing_data(clock,tmp_path,monkeypatch):
    file = tmp_path/'cache.gz'
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',file)
    old_stamp = datetime(2026,10,2,20,10,tzinfo=timezone.utc).timestamp()
    old = scanner._finalize_download(history().iloc[:-1],old_stamp)
    new = scanner._finalize_download(history(),NOW.timestamp())
    scanner._write_history_cache({'OLD':old,'NEW':new},NOW.timestamp())
    before = file.read_bytes()
    network = Mock(return_value={})
    monkeypatch.setattr(scanner,'_download_history',network)
    frames,info = scanner.load_historical_data(['OLD','NEW'],scanner.settings())
    assert info['status']=='partial_fallback'
    assert info['current_symbols']==1 and info['lagging_symbols']==['OLD']
    assert info['expected_session']=='2026-10-05'
    assert info['refresh_requested_symbols']==1 and info['refresh_received_symbols']==0
    assert info['refresh_error_code']=='incomplete_refresh'
    assert network.call_args.args==(['OLD'],)
    assert file.read_bytes()==before
    assert frames['OLD'].index[-1].date().isoformat()=='2026-10-02'
    assert frames['OLD'].attrs['history_fetched_at']==old_stamp


def test_history_failed_refresh_with_current_cache_not_reported_as_stale(clock,tmp_path,monkeypatch):
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',tmp_path/'cache.gz')
    stamp = NOW.timestamp()-72001
    # Simulate a valid frozen completed observation whose TTL has just expired.
    old = scanner._finalize_download(history(),NOW.timestamp())
    scanner._write_history_cache({'TEST':old},stamp)
    network = Mock(side_effect=RuntimeError('SECRET https://private.invalid/token'))
    monkeypatch.setattr(scanner,'_download_history',network)
    frames,info = scanner.load_historical_data(['TEST'],scanner.settings())
    assert info['status']=='refresh_failed_cache_current' and info['current_symbols']==1
    assert info['refresh_error_type']=='RuntimeError'
    assert info['refresh_error_code']=='provider_refresh_failed'
    assert 'SECRET' not in json.dumps(info) and 'https://' not in json.dumps(info)
    assert frames['TEST'].attrs['history_fetched_at']==NOW.timestamp()


def test_history_all_lagging_keeps_stale_fallback_and_original_observation(clock,tmp_path,monkeypatch):
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',tmp_path/'cache.gz')
    stamp = datetime(2026,10,2,20,10,tzinfo=timezone.utc).timestamp()
    old = scanner._finalize_download(history().iloc[:-1],stamp)
    scanner._write_history_cache({'OLD':old},stamp)
    monkeypatch.setattr(scanner,'_download_history',Mock(return_value={}))
    frames,info = scanner.load_historical_data(['OLD'],scanner.settings())
    assert info['status']=='stale_fallback' and info['current_symbols']==0
    assert info['lagging_symbols']==['OLD']
    assert frames['OLD'].attrs['history_fetched_at']==stamp


@pytest.mark.parametrize('at,day',[('2026-10-05T12:00:00Z','2026-10-02'),
    ('2026-10-05T20:04:59Z','2026-10-02'),('2026-10-05T20:05:00Z','2026-10-05'),
    ('2026-07-03T16:00:00Z','2026-07-02'),('2026-10-04T16:00:00Z','2026-10-02')])
def test_completed_session_weekend_holiday_and_finalization(at,day):
    assert scanner.latest_completed_session(datetime.fromisoformat(at.replace('Z','+00:00'))).isoformat()==day


def test_technical_and_context_use_completed_not_partial_day(clock):
    clock.instant=datetime(2026,10,5,15,tzinfo=timezone.utc)
    f=history();f.loc[f.index[-1],'Close']=1000
    cfg=scanner.settings()|dict(min_dollar_volume=0,min_atr_pct=0,max_atr_pct=100,min_technical_score=0)
    candidate=scanner.analyze_history('TEST','Synthetic',f,cfg)
    assert candidate['price_as_of']==candidate['single_target_source']['data_as_of']=='2026-10-02'
    assert candidate['entry']!=1000
    assert scanner._market_context({'SPY':f,'QQQ':f})['SPY']['as_of']=='2026-10-02'


def test_canonical_news_no_publication_requirement_and_no_writes(db):
    with database.get_db_connection() as c:seed_canonical(c)
    result=signal_news.existing_news([dict(ticker='TEST',company='Synthetic Corporation')],72,NOW)
    assert result['TEST'][0]['canonical_event_id']=='synthetic-event'
    assert result['TEST'][0]['provenance'][0]['rights']=='approved'
    with database.get_db_connection() as c:
        assert c.execute('SELECT status,reason FROM ne_events').fetchone()['reason']=='low_importance'
        assert c.execute('SELECT count(*) FROM ne_analysis').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM scanner_orders').fetchone()[0]==0


def test_fresh_observation_on_older_canonical_event_is_not_lost(db):
    with database.get_db_connection() as c:
        seed_canonical(c)
        c.execute("UPDATE ne_events SET created_at='2026-09-01T00:00:00Z'")
        c.commit()
    rows=signal_news.existing_news([dict(ticker='TEST',company='Synthetic Corporation')],72,NOW)
    assert rows['TEST'][0]['published_at']=='2026-10-05T18:00:00+00:00'


@pytest.mark.parametrize('damage',['identity','secondary','rights','conflict','future','stale','naive','retracted','unknown','backlog','opinion'])
def test_canonical_fail_closed_guards(damage):
    row=canonical_fixture();event=json.loads(row['body_json']);s=event['sources'][0]
    if damage=='identity':event['company_identity']=[]
    if damage=='secondary':s['title']='Other Corporation wins contract; Synthetic Corporation mentioned later'
    if damage=='rights':s['rights']='review_required'
    if damage=='conflict':event['conflicts']=['contradiction']
    if damage=='future':s['published_at']='2026-10-06T18:00:00Z'
    if damage=='stale':s['published_at']='2026-09-01T18:00:00Z'
    if damage=='naive':s['published_at']='2026-10-05 18:00:00'
    if damage=='retracted':row['reason']='source_retracted'
    if damage=='unknown':event['event_type']='unknown'
    if damage=='backlog':row['reason']='backlog_blocked'
    if damage=='opinion':event['title']=s['title']='Why investors should watch Synthetic Corporation'
    row['body_json']=json.dumps(event)
    try:result=signal_news.eligible_observations(row,dict(ticker='TEST',company='Synthetic Corporation'),72,NOW)
    except ValueError:result=[]
    assert not result


def test_yahoo_plus_canonical_preserves_provenance_without_repeating_story():
    row=signal_news.eligible_observations(canonical_fixture(),dict(ticker='TEST',company='Synthetic Corporation'),72,NOW)[0]
    yahoo=dict(row,provenance=[dict(ingestion_provider='scanner_yahoo')])
    result=signal_news.merge([yahoo],[row])
    assert len(result)==1 and len(result[0]['provenance'])==2


def test_reference_quote_never_claims_old_price_is_fresh(clock,monkeypatch):
    data=pd.DataFrame({'Close':[100.]},index=pd.DatetimeIndex(['2026-10-03T00:00:00Z']))
    ticker=Mock();ticker.history.return_value=data
    monkeypatch.setattr(scanner.yf,'Ticker',lambda _:ticker)
    quote=scanner.research_reference_quote('TEST')
    assert not quote['fresh'] and not quote['eligible_for_entry']
    assert ticker.history.call_args.kwargs['prepost'] is True


def test_decision_retained_once_allowlisted_and_not_prompt(db,monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','ollama')
    trace=final_ai.new_trace('synthetic','TEST',7)
    trace['decision']=dict(action='HOLD',confidence=.7,news_sentiment=0,news_relevance=.9,
        filter_failures=['ai_hold','ai_confidence_below_threshold'],confidence_threshold=.8,relevance_threshold=.6,
        prompt='DO NOT RETAIN',reason='PRIVATE MODEL TEXT')
    final_ai.persist(trace);final_ai.persist(trace)
    with database.get_db_connection() as c:
        rows=c.execute("SELECT metrics_json FROM scanner_candidates WHERE stage='ai_decision'").fetchall()
        assert len(rows)==1
        assert 'DO NOT RETAIN' not in rows[0]['metrics_json'] and 'PRIVATE MODEL TEXT' not in rows[0]['metrics_json']
        assert json.loads(rows[0]['metrics_json'])['filter_failures']==trace['decision']['filter_failures']


def test_session_wait_is_not_quality_rejection(db):
    with database.get_db_connection() as c:
        c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
        c.execute("""INSERT INTO scanner_candidates(scan_id,ticker,stage,status,reason,metrics_json,created_at)
            VALUES('synthetic','TEST','final','rejected','pre_waiting_regular_session','{}',?)""",(NOW.isoformat(),))
        c.commit()
        r=signal_research.report(c,48,NOW+timedelta(seconds=1))
        assert r['session_waits']=={'pre_waiting_regular_session':1}
        assert not r['rejection_reasons']


def test_canonical_fallback_and_cached_yahoo_freshness(db,clock,monkeypatch):
    with database.get_db_connection() as c:seed_canonical(c)
    candidate=dict(ticker='TEST',company='Synthetic Corporation',technical_direction='BUY',
        technical_score=7,average_dollar_volume=1e9)
    monkeypatch.setattr(scanner,'fetch_recent_news',Mock(side_effect=RuntimeError('isolated Yahoo failure')))
    monkeypatch.setattr(scanner,'_read_news_cache',lambda:{})
    monkeypatch.setattr(scanner,'_write_news_cache',Mock())
    ranked,rejected=scanner.enrich_and_rank_candidates([candidate],{},scanner.settings())
    assert len(ranked)==1 and not rejected and ranked[0]['news'][0]['canonical_event_id']=='synthetic-event'
    # A cache entry inside the fetch TTL cannot revive an expired headline.
    monkeypatch.setattr(signal_news,'existing_news',lambda *a:{})
    monkeypatch.setattr(scanner,'_read_news_cache',lambda:{'TEST':dict(fetched_at=NOW.timestamp(),items=[
        dict(title='Old title',relevance=1,published_at='2026-09-01T00:00:00Z')])})
    ranked,rejected=scanner.enrich_and_rank_candidates([candidate],{},scanner.settings())
    assert not ranked and rejected[0]['reason']=='insufficient_current_news'
