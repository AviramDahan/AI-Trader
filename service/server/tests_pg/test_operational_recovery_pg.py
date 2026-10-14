"""Real isolated PostgreSQL with synthetic SEC responses only."""
import json
from datetime import datetime,timedelta,timezone
import database
import sec_intelligence as si


def test_initial_horizon_restart_preserves_jobs_without_public_replay(pg,monkeypatch):
    now=datetime.now(timezone.utc);cik='0000000001'
    universe={'TEST':{'company':'Synthetic','indexes':['sp500']}};mapping={cik:['TEST']}
    uid,_=si.save_universe(universe,mapping,now)
    def row(suffix,days):
        return dict(accessionNumber=f'{cik}-26-{suffix:06d}',form='4',acceptanceDateTime=si._z(now-timedelta(days=days)),primaryDocument='ownership.xml')
    stored=row(1,300);si._queue_filing(stored,cik,['TEST'],uid,now-timedelta(days=1),[5])
    with database.get_db_connection() as c:
        c.execute('INSERT INTO si_checkpoints(issuer_cik,catchup_active) VALUES(?,1)',(cik,))
        original=dict(c.execute('SELECT * FROM si_filing_jobs').fetchone());c.commit()
    rows=[row(2,89),row(3,200)]
    monkeypatch.setenv('NEWS_SEC_USER_AGENT','Fixture Operator fixture@example.com')
    monkeypatch.setattr(si,'fetch',lambda *_a,**_kw:(json.dumps({'cik':1,'filings':{'recent':{k:[r[k] for r in rows] for k in rows[0]},'files':[]}}).encode(),{}))
    assert si.discover_cycle(now,universe=universe,mapping=mapping)['queued']==1
    assert si.discover_cycle(now+timedelta(minutes=1),universe=universe,mapping=mapping)['queued']==0
    with database.get_db_connection() as c:
        retained=dict(c.execute('SELECT * FROM si_filing_jobs WHERE accession=?',(stored['accessionNumber'],)).fetchone())
        assert retained==original
        assert c.execute('SELECT count(*) n FROM si_filing_jobs').fetchone()['n']==2
        for table in ('scanner_signals','scanner_orders','scanner_fills','scanner_telegram_outbox','ai_call_usage'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0
