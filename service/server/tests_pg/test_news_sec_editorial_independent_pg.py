"""Independent real-PG editorial persistence only, in fixture-owned test_* schema."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from unittest.mock import Mock

NOW=datetime(2026,10,21,12,tzinfo=timezone.utc)
RESULT=dict(related=True,title_he='פורסם נתון אינפלציה',summary_he='פורסמו נתוני אינפלציה לרבעון.',
            interpretation_he='המשמעות הכלכלית אינה ודאית.',sentiment='neutral',materiality='medium',relevance=.5)


def fixture_pipeline():
    from database import get_db_connection
    from news_events.engine import Pipeline
    from news_events.store import Store
    store=Store(get_db_connection,sandbox=True);store.install()
    return Pipeline(store,{},lambda:(set(),set()),not_before=NOW-timedelta(days=1)),store


def bulletin(provider='first',**changes):
    from news_events.model import Source
    value=Source(provider,'one',f'https://{provider}.example/articles/123456',provider,
        NOW.isoformat(),NOW.isoformat(),'New Zealand CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)','',
        event_type='market',rights='approved')
    return replace(value,**changes)


def test_pg_release_components_restart_revision_withdrawal_no_trading(pg):
    from news_events.engine import Analysis,Pipeline
    from news_events.store import Store
    p,s=fixture_pipeline()
    with s.transaction() as c:
        baseline={table:c.execute('SELECT count(*) n FROM '+table).fetchone()['n']
                  for table in ('scanner_trades','scanner_orders','scanner_fills','scanner_signals')}
    analyze=Mock(return_value=Analysis(dict(RESULT)))
    first=bulletin();eid=p.ingest(first,NOW)
    assert p.analyze(eid,analyze,NOW)=='done'
    assert len(p.deliver_preview(eid,NOW))==1  # No transport exists in sandbox.
    old_version=s.event(eid)['evidence_version']
    later=NOW+timedelta(seconds=33)
    annual=bulletin('annual',title='New Zealand CPI (Y/Y) Q3: 3.7% (est 3.8%; prev 4.1%)',collected_at=later.isoformat())
    assert p.ingest(annual,later)==eid
    event=s.event(eid)
    assert event['status']=='pending' and event['evidence_version']!=old_version
    assert len({key for row in event['body']['normalized_evidence'] for key in row['claims'] if key.startswith('macro_release:')})==6
    assert p.analyze(eid,analyze,later)=='done'
    assert len(p.deliver_preview(eid,later))==1
    restarted=Pipeline(Store(s.connect,sandbox=True),{},p.membership,not_before=p.not_before)
    assert restarted.ingest(annual,later+timedelta(minutes=1))==eid
    assert restarted.deliver_preview(eid,later+timedelta(minutes=1))==[]
    assert analyze.call_count==2
    conflict=bulletin('revision',title='New Zealand CPI (Q/Q) Q3: 0.9% (est 0.8%; prev 1.5%)')
    assert restarted.ingest(conflict,later)==eid
    assert s.event(eid)['reason']=='source_conflict'
    assert restarted.analyze(eid,analyze,later)=='blocked'
    assert analyze.call_count==2
    s.withdraw(first.provider_id,first.source_id,later)
    assert s.event(eid)['reason']=='source_retracted'
    assert restarted.ingest(first,later) is None
    with s.transaction() as c:
        assert c.execute('SELECT count(*) n FROM ne_sources').fetchone()['n']==3
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==2
        for table,count in baseline.items():
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==count


def test_pg_ambiguous_release_bridge_quarantines_without_merging_history(pg):
    p,s=fixture_pipeline()
    a=bulletin();one=p.ingest(a,NOW)
    b=bulletin('second',title='Australia CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)')
    two=p.ingest(b,NOW);assert two!=one
    bridge=bulletin('third',event_refs=(b.url,))
    assert p.ingest(bridge,NOW) is None
    with s.transaction() as c:
        assert c.execute('SELECT count(*) n FROM ne_events').fetchone()['n']==2
        assert c.execute('SELECT count(*) n FROM ne_quarantine').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==0


def test_pg_actual_runtime_queue_and_send_time_recheck_low_market_importance(pg,monkeypatch):
    from news_events.engine import Analysis
    from news_events import runtime
    import scanner_engine
    p,s=fixture_pipeline();eid=p.ingest(bulletin(),NOW)
    assert p.analyze(eid,lambda _e:Analysis({**RESULT,'materiality':'low'}),NOW)=='done'
    monkeypatch.setattr(runtime,'state',lambda *_a:{'mode':'canonical','epoch':7})
    enqueue=Mock(side_effect=AssertionError('No Telegram enqueue allowed'))
    monkeypatch.setattr(scanner_engine,'enqueue_telegram',enqueue)
    assert runtime.queue_outbox(p,eid,NOW)==0
    enqueue.assert_not_called()
    record=s.event(eid);key='canonical:'+eid+':'+record['evidence_version']+':market_news'
    # Model an already queued older low-importance row, then enforce NEW route at send.
    with s.transaction(True) as c:
        c.execute('UPDATE ne_events SET reason=NULL WHERE event_id=?',(eid,))
        c.execute('INSERT INTO ne_outbox VALUES(?,?,?,?,?)',(key,eid,record['evidence_version'],'market_news',7))
    monkeypatch.setattr(runtime,'active',lambda:True)
    monkeypatch.setattr(runtime,'pipeline',lambda:p)
    monkeypatch.setattr(runtime,'membership',lambda *_a:(set(),set()))
    monkeypatch.setattr(runtime,'now',lambda:NOW)
    render=Mock(return_value='synthetic-approved-preview')
    monkeypatch.setattr(runtime,'message',render)
    assert runtime.delivery_message({'dedupe_key':key}) is None
    render.assert_not_called()
    with s.transaction(True) as c:
        c.execute('UPDATE ne_analysis SET result_json=? WHERE event_id=?',(json.dumps(RESULT),eid))
    assert runtime.delivery_message({'dedupe_key':key})=='synthetic-approved-preview'
    assert render.call_count==1
