"""Synthetic operational regressions; no production/network/AI/Telegram writes."""
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sec_intelligence as si
from test_sec_intelligence import isolated, filing

NOW = datetime(2026, 10, 14, 13, tzinfo=timezone.utc)
CIK = '0000000001'
ARGS = dict(universe={'TEST':{'company':'Synthetic','indexes':['sp500']}},mapping={CIK:['TEST']})

@pytest.mark.parametrize('partial', [False, True])
def test_initial_recent_respects_90days_without_deleting_retained_history(isolated, monkeypatch, partial):
    uid,_ = si.save_universe(ARGS['universe'], ARGS['mapping'], NOW)
    stored = filing(f'{CIK}-26-000001','4',NOW-timedelta(days=300))
    si._queue_filing(stored,CIK,['TEST'],uid,NOW-timedelta(days=1),[5])
    if partial:
        with isolated() as c:
            c.execute('INSERT INTO si_checkpoints(issuer_cik,catchup_active) VALUES(?,1)',(CIK,));c.commit()
    rows=[filing(f'{CIK}-26-000002','4',NOW-timedelta(days=90)),
          filing(f'{CIK}-26-000003','4',NOW-timedelta(days=91)),
          filing(f'{CIK}-26-000004','4',NOW-timedelta(days=200))]
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Fixture Operator fixture@example.com')
    def fetch(*_a,**kw):
        return json.dumps({'cik':1,'filings':{'recent':{k:[r[k] for r in rows] for k in rows[0]},'files':[]}}).encode(),{}
    monkeypatch.setattr(si,'fetch',fetch)
    result=si.discover_cycle(NOW,**ARGS)
    assert result['queued']==1
    assert si.discover_cycle(NOW+timedelta(minutes=1),**ARGS)['queued']==0
    with isolated() as c:
        assert {r['accession'] for r in c.execute('SELECT accession FROM si_filing_jobs')}=={stored['accessionNumber'],rows[0]['accessionNumber']}
        assert c.execute('SELECT catchup_active FROM si_checkpoints').fetchone()['catchup_active']==0

def test_known_outage_keeps_older_history_and_unknown_timestamps_are_not_boundary(isolated, monkeypatch):
    with isolated() as c:
        c.execute('INSERT INTO si_checkpoints(issuer_cik,last_accession,catchup_active,catchup_marker) VALUES(?,?,1,?)',(CIK,f'{CIK}-26-000001',f'{CIK}-26-000001'));c.commit()
    rows=[filing(f'{CIK}-26-000002','4',NOW-timedelta(days=200))]
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Fixture Operator fixture@example.com')
    monkeypatch.setattr(si,'fetch',lambda *_a,**_kw:(json.dumps({'cik':1,'filings':{'recent':{k:[r[k] for r in rows] for k in rows[0]},'files':[]}}).encode(),{}))
    assert si.discover_cycle(NOW,**ARGS)['queued']==1
    unknown=dict(rows[0],acceptanceDateTime=None)
    assert list(si._discovery_rows([unknown],NOW,initial=True))==[unknown]

def test_initial_continuation_keeps_horizon_across_restart(isolated, monkeypatch):
    fresh=filing(f'{CIK}-26-000005','4',NOW-timedelta(hours=1))
    first=filing(f'{CIK}-26-000004','4',NOW-timedelta(days=1));first['acceptanceDateTime']=None
    second=filing(f'{CIK}-26-000003','4',NOW-timedelta(days=200))
    pages=[{'name':f'CIK{CIK}-submissions-001.json','filingTo':'2026-10-13'},
           {'name':f'CIK{CIK}-submissions-002.json','filingTo':'2026-03-01'}]
    def fetch(url,*_a,**_kw):
        if '-001.json' in url:body={k:[v] for k,v in first.items()}
        elif '-002.json' in url:body={k:[v] for k,v in second.items()}
        else:body={'cik':1,'filings':{'recent':{k:[v] for k,v in fresh.items()},'files':pages}}
        return json.dumps(body).encode(),{}
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Fixture Operator fixture@example.com')
    monkeypatch.setattr(si,'fetch',fetch)
    assert si.discover_cycle(NOW,**ARGS)['queued']==2
    assert si.discover_cycle(NOW+timedelta(minutes=1),**ARGS)['queued']==0
    with isolated() as c:
        assert c.execute('SELECT count(*) n FROM si_filing_jobs').fetchone()['n']==2
        assert c.execute('SELECT catchup_active FROM si_checkpoints').fetchone()['catchup_active']==0
        assert c.execute('SELECT catchup_active FROM si_checkpoints').fetchone()['catchup_active']==0


def test_submissions_cap_is_bounded_and_distinct_from_documents(isolated,monkeypatch):
    seen=[]
    def fetch(url,*_a,**kw):
        seen.append(kw['max_bytes'])
        return json.dumps({'cik':1,'filings':{'recent':{},'files':[]}}).encode(),{}
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Fixture Operator fixture@example.com')
    monkeypatch.setattr(si,'fetch',fetch)
    assert si.discover_cycle(NOW,**ARGS)['status']=='ok'
    assert seen==[8_000_000]


def test_large_valid_submissions_pass_actual_bounded_transport(isolated,monkeypatch):
    import sec_transport
    from unittest.mock import MagicMock
    raw=json.dumps({'cik':1,'filings':{'recent':{},'files':[]},'synthetic_padding':'x'*4_600_000}).encode()
    response=MagicMock();response.__enter__.return_value=response
    response.status_code=200;response.headers={'Content-Encoding':'identity','Content-Length':str(len(raw))}
    response.iter_content.return_value=[raw]
    session=MagicMock();session.__enter__.return_value=session;session.get.return_value=response
    monkeypatch.setattr(sec_transport.requests,'Session',lambda:session)
    monkeypatch.setattr(sec_transport,'reserve',lambda:None)
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Fixture Operator fixture@example.com')
    assert si.discover_cycle(NOW,**ARGS)['status']=='ok'
    assert session.get.call_args.kwargs['allow_redirects'] is False
    assert session.trust_env is False


def test_partial_delta_preserves_known_marker_after_restart(isolated,monkeypatch):
    marker=f'{CIK}-26-000001'
    with isolated() as c:
        c.execute('INSERT INTO si_checkpoints(issuer_cik,last_accession,last_checked_at) VALUES(?,?,?)',(CIK,marker,si._z(NOW-timedelta(days=1))));c.commit()
    rows=[filing(f'{CIK}-26-000003','4',NOW-timedelta(days=10)),filing(f'{CIK}-26-000002','4',NOW-timedelta(days=200)),filing(marker,'4',NOW-timedelta(days=300))]
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Fixture Operator fixture@example.com')
    monkeypatch.setattr(si,'MAX_PENDING',1)
    monkeypatch.setattr(si,'fetch',lambda *_a,**_kw:(json.dumps({'cik':1,'filings':{'recent':{k:[r[k] for r in rows] for k in rows[0]},'files':[]}}).encode(),{}))
    assert si.discover_cycle(NOW,**ARGS)['queued']==1
    with isolated() as c:
        cp=c.execute('SELECT * FROM si_checkpoints').fetchone()
        assert cp['catchup_active']==1 and cp['catchup_marker']==marker
        c.execute("UPDATE si_filing_jobs SET status='processed'");c.commit()
    assert si.discover_cycle(NOW+timedelta(minutes=1),**ARGS)['queued']==1
    with isolated() as c:
        assert c.execute('SELECT count(*) n FROM si_filing_jobs').fetchone()['n']==2


def test_provider_projection_only_exposes_allowlisted_errors_and_valid_http():
    import admin_system_status as ops
    row={'provider_id':'globenewswire','status':'requires_configuration','last_success_at':NOW.isoformat(),
         'last_attempt_at':NOW.isoformat(),'http_status':'403','error_code':'http_error'}
    assert ops.provider_view(row)['http_status']==403
    assert ops.provider_view(row)['last_success_at']==NOW.isoformat()
    row.update(error_code='https://private.invalid/SECRET',http_status='NaN')
    view=ops.provider_view(row)
    assert view['error_code'] is None and view['http_status'] is None and 'SECRET' not in json.dumps(view)
