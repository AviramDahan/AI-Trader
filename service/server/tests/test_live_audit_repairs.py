"""Live-audit regressions using synthetic records and no network."""
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import sec_intelligence as si
import signal_research as research
from news_presentation import hide_relay_branding
from test_sec_intelligence import isolated, filing
from test_signal_research import db, NOW
from decision_explanation import public_reason
from test_signal_inputs import clock, history


@pytest.mark.parametrize('reason', ['pre_entry_not_above_completed_high',
                                  'entry_not_above_completed_high', 'pre_completed_high_unavailable'])
def test_breakout_rejection_is_a_target_stage(reason):
    assert research.reason_stage(reason) == 'targets'


def test_known_publisher_wrapper_and_repeated_cleanup_preserve_assertion():
    source = 'לפי הכותרת שפרסם The Wall Street Journal, החברה בוחנת מכירה של פעילות.'
    rendered = hide_relay_branding(source)
    assert 'The Wall Street Journal' not in rendered
    assert 'החברה בוחנת מכירה של פעילות' in rendered
    assert rendered.startswith('לפי דיווח,')
    assert hide_relay_branding(rendered) == rendered
    assert hide_relay_branding('דיווח דיווח כי החברה העלתה תחזית.') == 'לפי דיווח, החברה העלתה תחזית.'
    subject = 'The Wall Street Journal הודיע על השקת מוצר; "דיווח דיווח" הוא שם הספר.'
    assert hide_relay_branding(subject) == subject


@pytest.mark.parametrize('code', ['sec_document_too_large', 'submissions_issuer_mismatch'])
def test_discovery_retains_known_safe_error_not_raw_exception(isolated, monkeypatch, code):
    now = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
    monkeypatch.setenv('NEWS_SEC_USER_AGENT', 'Synthetic Operator test@example.com')
    def fail(*_a, **_kw):
        raise ValueError(code)
    monkeypatch.setattr(si, 'fetch', fail)
    result = si.discover_cycle(now, universe={'TEST': {'company':'Synthetic','indexes':['sp500']}},
                               mapping={'0000000001':['TEST']})
    assert result['errors'] == [code]
    assert result['failure_details'][0]['phase'] == 'recent_fetch'
    with isolated() as c:
        row = c.execute('SELECT * FROM si_checkpoints').fetchone()
        assert row['error_code'] == code and row['last_checked_at'] is None
    assert result['failure_details'][0]['issuer_cik'] == '0000000001'


@pytest.mark.parametrize('name', ['not-a-submissions-file.json', 'CIK0000000002-submissions-001.json'])
def test_invalid_continuation_cannot_be_skipped_or_completed(isolated, monkeypatch, name):
    now = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
    monkeypatch.setenv('NEWS_SEC_USER_AGENT', 'Synthetic Operator test@example.com')
    recent = filing('0000000001-26-000001', '4', now-timedelta(minutes=1))
    body = {'cik':1,'filings': {'recent': {k:[v] for k,v in recent.items()},
                              'files':[{'name':name,'filingTo':'2026-10-11'}]}}
    calls=[]
    def fetch(url,*_a,**_kw):
        calls.append(url)
        return json.dumps(body).encode(), {'etag':'synthetic'}
    monkeypatch.setattr(si,'fetch',fetch)
    args=dict(universe={'TEST':{'company':'Synthetic','indexes':['sp500']}}, mapping={'0000000001':['TEST']})
    for instant in (now,now+timedelta(minutes=6)):
        result=si.discover_cycle(instant,**args)
        assert result['errors']==['invalid_sec_continuation_file']
        with isolated() as c:
            cp=c.execute('SELECT * FROM si_checkpoints').fetchone()
            assert cp['last_accession'] is None and cp['last_checked_at'] is None
            assert cp['older_file_index']==0
            assert c.execute('SELECT count(*) n FROM si_filing_jobs').fetchone()['n']==1
    assert len(calls)==2


def test_research_reports_missing_sec_evidence_and_safe_ai_reason(db):
    with database.get_db_connection() as c:
        c.execute('''INSERT INTO si_decisions(scan_id,ticker,mode,baseline_rank_score,sec_adjustment,
            enhanced_rank_score,evidence_ids_json,shortlist_limit,decided_at)
            VALUES('s2','TEST','paper',.8,0,.8,'[]',25,?)''', ('2026-10-07T14:00:00Z',))
        decision={'action':'HOLD','confidence':.75,'news_relevance':.8,
                  'reason':'Synthetic evidence does not yet support entry.', 'private':'DO-NOT-EXPOSE'}
        c.execute('''INSERT INTO scanner_candidates(scan_id,ticker,stage,status,metrics_json,created_at)
            VALUES('s2','TEST','ai_decision','observed',?,?)''', (json.dumps(decision),'2026-10-07T14:00:00Z'))
        c.commit()
        r=research.report(c,48,NOW)
        case=next(row for row in r['records'] if row['scan_id']=='s2')
        assert case['sec_decision']['evidence_status']=='UNKNOWN_NO_RETAINED_EVIDENCE'
        assert case['sec_decision']['evidence_ids']==[]
        assert case['ai_decision']['reason']==decision['reason']
        assert 'DO-NOT-EXPOSE' not in json.dumps(r)


@pytest.mark.parametrize('secret', ['https://private.invalid/secret', 'operator@private.invalid',
    'Bearer synthetic-secret', 'password=synthetic', 'api_key:synthetic',
    'sk-or-v1-synthetic-key', '-----BEGIN PRIVATE KEY-----'])
def test_sensitive_explanation_never_persisted_or_public(secret):
    assert public_reason('Normal text. '+secret) is None
    assert public_reason('x'*900+secret) is None


def test_explanation_is_bounded_and_bidi_controls_are_not_executed():
    assert len(public_reason('x'*900))==800
    assert public_reason('\u202eSynthetic\nexplanation\u2069')=='Synthetic explanation'
    assert public_reason(None) is None


@pytest.mark.parametrize('mode,adjustment,expected', [('paper',0,False),('paper',.04,True),('shadow',.04,False)])
def test_retained_sec_evidence_is_distinct_from_ranking_change(mode,adjustment,expected):
    row={'mode':mode,'sec_snapshot_id':'synthetic','evidence_ids_json':'["synthetic-evidence"]','sec_adjustment':adjustment}
    view=research.sec_evidence_view(row)
    assert view['evidence_status']=='RETAINED_EVIDENCE'
    assert view['ranking_changed_in_paper'] is expected
    row['evidence_ids_json']='malformed'
    assert research.sec_evidence_view(row)['evidence_status']=='UNKNOWN_NO_RETAINED_EVIDENCE'


def test_sec_unknown_error_is_sanitized_http_retry_is_preserved(isolated,monkeypatch):
    from retry_policy import DeferredProviderError
    now=datetime(2026,10,12,15,tzinfo=timezone.utc)
    args=dict(universe={'TEST':{'company':'Synthetic','indexes':['sp500']}},mapping={'0000000001':['TEST']})
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Synthetic Operator test@example.com')
    for exc, code in [(ValueError('https://private.invalid/?secret=DO-NOT-EXPOSE'),'ValueError'),
                      (DeferredProviderError(429,600),'DeferredProviderError')]:
        def fail(*_a,**_kw):raise exc
        monkeypatch.setattr(si,'fetch',fail)
        result=si.discover_cycle(now,**args)
        assert result['errors']==[code]
        assert 'DO-NOT-EXPOSE' not in json.dumps(result)
        with isolated() as c:
            c.execute("DELETE FROM si_checkpoints");c.commit()
        if code=='DeferredProviderError':
            detail=result['failure_details'][0]
            assert detail['http_status']==429
            assert detail['retry_after']==si._z(now+timedelta(seconds=600))


def test_incomplete_sec_catchup_cannot_be_completed_by_not_modified(isolated,monkeypatch):
    now=datetime(2026,10,12,15,tzinfo=timezone.utc)
    args=dict(universe={'TEST':{'company':'Synthetic','indexes':['sp500']}},mapping={'0000000001':['TEST']})
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Synthetic Operator test@example.com')
    with isolated() as c:
        c.execute('''INSERT INTO si_checkpoints(issuer_cik,last_checked_at,catchup_active,older_file_index)
                     VALUES(?,?,1,2)''',('0000000001',si._z(now-timedelta(hours=1))))
        c.commit()
    seen=[]
    def fetch(*_a,**kw):seen.append(kw);return None,{}
    monkeypatch.setattr(si,'fetch',fetch)
    assert si.discover_cycle(now,**args)['errors']==['sec_unexpected_not_modified']
    with isolated() as c:
        cp=c.execute('SELECT * FROM si_checkpoints').fetchone()
        assert cp['catchup_active']==1 and cp['older_file_index']==2
        assert cp['last_checked_at']==si._z(now-timedelta(hours=1))
    assert seen[0]['etag']==''


def test_unknown_acceptance_date_does_not_fake_retention_boundary(isolated,monkeypatch):
    now=datetime(2026,10,12,15,tzinfo=timezone.utc)
    cik='0000000001'
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Synthetic Operator test@example.com')
    recent=filing(f'{cik}-26-000003','4',now-timedelta(minutes=1))
    first=filing(f'{cik}-26-000002','4',now-timedelta(days=1));first['acceptanceDateTime']=None
    second=filing(f'{cik}-26-000001','4',now-timedelta(days=2))
    files=[{'name':f'CIK{cik}-submissions-001.json','filingTo':'2026-10-11'},
           {'name':f'CIK{cik}-submissions-002.json','filingTo':'2026-10-10'}]
    def fetch(url,*_a,**_kw):
        if 'submissions-001' in url:body={k:[v] for k,v in first.items()}
        elif 'submissions-002' in url:body={k:[v] for k,v in second.items()}
        else:body={'cik':1,'filings':{'recent':{k:[v] for k,v in recent.items()},'files':files}}
        return json.dumps(body).encode(),{}
    monkeypatch.setattr(si,'fetch',fetch)
    args=dict(universe={'TEST':{'company':'Synthetic','indexes':['sp500']}},mapping={cik:['TEST']})
    si.discover_cycle(now,**args)
    with isolated() as c:
        cp=c.execute('SELECT * FROM si_checkpoints').fetchone()
        assert cp['catchup_active']==1 and cp['older_file_index']==1
    si.discover_cycle(now+timedelta(minutes=1),**args)
    with isolated() as c:
        assert c.execute('SELECT count(*) n FROM si_filing_jobs').fetchone()['n']==3
        assert c.execute('SELECT catchup_active FROM si_checkpoints').fetchone()['catchup_active']==0


def test_mandatory_credit_and_source_subject_survive_cleanup(monkeypatch):
    from telegram_topics import with_news_community_link
    monkeypatch.setenv('TELEGRAM_COMMUNITY_URL','https://t.me/+synthetic')
    text="לפי הכותרת שפרסם The Wall Street Journal, החברה הודיעה על שינוי.\n\nGlobal Voices — Synthetic Author\nתרגום/תקציר AI · CC BY https://creativecommons.org/licenses/by/4.0/"
    rendered=with_news_community_link(text,'stock_news')
    assert 'The Wall Street Journal' not in rendered
    assert 'Global Voices — Synthetic Author' in rendered
    assert 'https://creativecommons.org/licenses/by/4.0/' in rendered
    assert with_news_community_link(rendered,'stock_news')==rendered


def test_short_history_has_diagnostic_but_is_not_a_technical_candidate(clock,monkeypatch):
    import stock_scanner as scanner
    frame=history().iloc[-8:]
    monkeypatch.setattr(scanner.yf,'download',lambda *_a,**_kw:frame)
    result=scanner._download_history(['NEW'])
    assert not result
    assert result.gaps['NEW']==dict(reason='insufficient_completed_history',completed_bars=8,required_bars=65)
    assert scanner.analyze_history('NEW','Synthetic',frame,scanner.settings()) is None


def test_short_history_refresh_keeps_other_cache_and_source_times(clock,tmp_path,monkeypatch):
    import stock_scanner as scanner
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',tmp_path/'cache.gz')
    frame=scanner._finalize_download(history(),clock.instant.timestamp())
    existing={f'OLD{i}':frame for i in range(20)}
    scanner._write_history_cache(existing,clock.instant.timestamp())
    before=scanner.HISTORY_CACHE_FILE.read_bytes()
    monkeypatch.setattr(scanner.yf,'download',lambda *_a,**_kw:history().iloc[-8:])
    frames,meta=scanner.load_historical_data([*existing,'NEW'],scanner.settings())
    assert set(frames)==set(existing) and meta['current_symbols']==20
    assert meta['history_gap_details']['NEW']['reason']=='insufficient_completed_history'
    assert meta['history_gap_details']['NEW']['completed_bars']==8
    assert scanner.HISTORY_CACHE_FILE.read_bytes()==before
    assert frames['OLD0'].attrs['history_fetched_at']==clock.instant.timestamp()


def test_successful_batch_refresh_also_explains_short_history(clock,tmp_path,monkeypatch):
    import pandas as pd
    import stock_scanner as scanner
    monkeypatch.setattr(scanner,'HISTORY_CACHE_FILE',tmp_path/'cache.gz')
    existing={f'OLD{i}':history() for i in range(20)}
    batch=pd.concat({**existing,'NEW':history().iloc[-8:]},axis=1)
    monkeypatch.setattr(scanner.yf,'download',lambda *_a,**_kw:batch)
    frames,meta=scanner.load_historical_data([*existing,'NEW'],scanner.settings())
    assert meta['status']=='refreshed' and set(frames)==set(existing)
    assert meta['history_gap_details']['NEW']['completed_bars']==8
    assert meta['missing_symbols']==['NEW']
