"""Production boundary on disposable PostgreSQL schemas, no network/senders."""
import json
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock
import pytest


@pytest.mark.parametrize('populated',[False,True])
def test_compact_health_matches_entire_legacy_summary(live,populated,monkeypatch):
    from news_events import reporting
    from news_events.queue_health import queue_rows
    p,src,_,at,_=live
    if populated:
        eid=p.ingest(src,at)
        with p.store.transaction(True) as c:
            body=json.loads(c.execute('SELECT body_json FROM ne_events WHERE event_id=?',(eid,)).fetchone()['body_json'])
            body['providers']=['yahoo','sec'];body['queue_entered_at']='invalid clock'
            body['unused_large_evidence']='x'*200000
            c.execute('UPDATE ne_events SET body_json=? WHERE event_id=?',(json.dumps(body),eid))
            for i in range(5):
                p.store.metric(c,'analysis','failed' if i%2 else 'ok',at.isoformat(),eid,'yahoo',
                    raw_items=2,providers=['yahoo','sec'],latency=1.5,
                    calls=[{'cost':None,'input_tokens':None},{'cost':.001,'input_tokens':12,'output_tokens':8},{'cost':0,'output_tokens':0}])
            p.store.metric(c,'ingest','cross_source_duplicate',at.isoformat(),eid,'sec',raw_items=1)
            p.store.metric(c,'ingest','duplicate',at.isoformat(),eid)
    expected=reporting.report(p.store,at+timedelta(seconds=50));expected.pop('per_event')
    monkeypatch.setattr(reporting,'report',Mock(side_effect=AssertionError('No full report in PG health')))
    actual=reporting.health_report(p.store,at+timedelta(seconds=50))
    json.dumps(actual)  # SQL numeric aggregates must remain JSON-compatible.
    assert actual.keys()==expected.keys()
    for key,value in expected.items():
        if isinstance(value,float):assert actual[key]==pytest.approx(value)
        else:assert actual[key]==value
    with p.store.transaction() as c:
        rows=queue_rows(c)
        assert all(len(row['body_json'])<150 for row in rows)


def test_compact_health_persisted_without_per_event_history(live,monkeypatch):
    from news_events import watch,reporting
    import ai_operations
    p,src,_,at,_=live;p.ingest(src,at)
    monkeypatch.setattr(ai_operations,'enqueue',Mock())
    monkeypatch.setattr(reporting,'report',Mock(side_effect=AssertionError('Unbounded report called')))
    result=watch.check(at)
    assert result['alarms']==[] and 'per_event' not in result
    with p.store.transaction() as c:
        saved=json.loads(c.execute("SELECT value_json FROM scanner_settings WHERE key='news_canonical_health'").fetchone()['value_json'])
        assert saved==result


def test_four_hour_reports_do_not_delay_health_or_safety_alarms(live):
    from news_events import watch
    p,_,_,at,_=live  # 12:00 UTC, beginning of a four-hour bucket
    for minute in (0, 1, 60, 180, 239, 240):
        current=at+timedelta(minutes=minute)
        result=watch.check(current)
        assert result['alarms']==[]
        with p.store.transaction() as c:
            saved=json.loads(c.execute("SELECT value_json FROM scanner_settings WHERE key='news_canonical_health'").fetchone()['value_json'])
            assert saved['checked_at']==current.isoformat()
            count=c.execute("SELECT count(*) n FROM admin_alerts WHERE dedupe_key LIKE 'canonical_health:%'").fetchone()['n']
            assert count==(2 if minute==240 else 1)
    # An alarm just after a routine summary is NOT held until the next bucket.
    now=at+timedelta(minutes=241)
    with p.store.transaction() as c:
        c.execute('INSERT INTO scanner_service_status VALUES(?,?,?,?,?)',
                  ('monitor','error',now.isoformat(),now.isoformat(),'test-only'))
    assert 'monitor_degraded' in watch.check(now)['alarms']
    with p.store.transaction() as c:
        assert c.execute("SELECT count(*) n FROM admin_alerts WHERE dedupe_key LIKE 'canonical_rollback:%'").fetchone()['n']==1


@pytest.fixture
def live(pg,monkeypatch):
    from database import get_db_connection
    from news_events.store import Store
    from news_events.engine import Pipeline
    from news_events import runtime
    from news_events.model import Source
    at=datetime(2026,9,27,12,tzinfo=timezone.utc)
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME','true')
    with get_db_connection() as c:
        c.execute("UPDATE ne_control SET mode='canonical',not_before=?,epoch=1 WHERE id=1",((at-timedelta(minutes=1)).isoformat(),))
    store=Store(get_db_connection,production=True)
    members=[set(),set()]
    p=Pipeline(store,{'AAPL':{'company':'Apple Inc.'}},lambda:members,not_before=at-timedelta(minutes=1))
    monkeypatch.setattr(runtime,'pipeline',lambda:p)
    monkeypatch.setattr(runtime,'now',lambda:at)
    monkeypatch.setattr(runtime,'membership',lambda *a:members)
    src=Source('licensed','one','https://example.org/article/12345','Publisher',at.isoformat(),at.isoformat(),
        'Apple Inc. financial results','Apple Inc. announced quarterly financial results and maintained guidance for the next financial year with no change.',
        event_type='earnings',rights='approved')
    result=dict(related=True,title_he='אפל פרסמה תוצאות',summary_he='החברה פרסמה תוצאות ושמרה על התחזית.',
        interpretation_he='ייתכן שיש השפעה על החברה.',sentiment='positive',materiality='high',relevance=.95)
    return p,src,result,at,members


def test_canonical_outbox_atomic_restart_and_dispatch_membership(live):
    from news_events.engine import Analysis
    from news_events.runtime import queue_outbox,delivery_message,project
    p,src,result,at,members=live;eid=p.ingest(src,at)
    p.analyze(eid,lambda _:Analysis(result),at)
    project(p,eid,at)
    assert queue_outbox(p,eid,at)==1
    assert queue_outbox(p,eid,at)==0
    with p.store.transaction() as c:
        rows=c.execute('SELECT * FROM scanner_telegram_outbox').fetchall()
        assert len(rows)==1
        assert c.execute('SELECT count(*) n FROM scanner_news_jobs').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']==0
    assert delivery_message(dict(rows[0]))
    members[1].add('AAPL') # Broad message is not delivered to now-wrong topic.
    assert delivery_message(dict(rows[0])) is None


def test_old_path_cannot_enqueue_when_canonical(live):
    from scanner_engine import enqueue_telegram
    p,_,_,at,_=live
    with p.store.transaction(True) as c:
        assert not enqueue_telegram(c,'market-news:old','market_news','test',published_at=at.isoformat())
        # Trading lifecycle unaffected by the news switch.
        assert enqueue_telegram(c,'tp:test','tp','test')


@pytest.mark.parametrize('publisher',['PR Newswire','Investing.com'])
def test_wire_syndication_one_analysis_and_outbox_after_restart(live,publisher):
    from dataclasses import replace
    from news_events.engine import Analysis
    from news_events.runtime import queue_outbox
    p,src,result,at,_=live
    src=replace(src,provider_id='prnewswire' if publisher=='PR Newswire' else 'investing',publisher=publisher,
        title='Apple Inc. Announces Definitive Agreement To Acquire Example, A Leading Technology Company')
    eid=p.ingest(src,at);ai=Mock(return_value=Analysis(result))
    p.analyze(eid,ai,at);assert queue_outbox(p,eid,at)==1
    yahoo=replace(src,provider_id='yahoo',publisher=publisher,source_id='yahoo-copy',
        url='https://finance.yahoo.com/news/apple-acquires-example-123456.html',source_excerpt='')
    if publisher=='Investing.com':
        yahoo=replace(yahoo,published_at=(at+timedelta(minutes=1)).isoformat())
        at+=timedelta(minutes=2)
    assert p.ingest(yahoo,at)==eid
    p.analyze(eid,ai,at);assert queue_outbox(p,eid,at)==0
    p.recover_interrupted(at);p.ingest(yahoo,at);p.analyze(eid,ai,at)
    ai.assert_called_once()
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM ne_events').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM ne_sources').fetchone()['n']==2
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==1


def test_rollback_fences_canonical_dispatch(live):
    from news_events.engine import Analysis
    from news_events.runtime import queue_outbox,delivery_message
    p,src,result,at,_=live;eid=p.ingest(src,at);p.analyze(eid,lambda _:Analysis(result),at)
    queue_outbox(p,eid,at)
    with p.store.transaction(True) as c:
        row=dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        c.execute("UPDATE ne_control SET mode='phase1',epoch=epoch+1 WHERE id=1")
    assert delivery_message(row) is None


def test_old_delivery_receipt_prevents_new_provider_replay(live):
    from news_events.engine import Analysis
    from news_events.runtime import queue_outbox
    p,src,result,at,_=live;eid=p.ingest(src,at);p.analyze(eid,lambda _:Analysis(result),at)
    with p.store.transaction(True) as c:
        c.execute('INSERT INTO ne_cutover_receipts VALUES(?,?,?)',(src.url,'important_stock_news',at.isoformat()))
    assert queue_outbox(p,eid,at)==0


def test_cutover_refuses_active_worker_and_does_not_modify_state(live):
    from database import get_db_connection
    from news_events.cutover import switch
    with get_db_connection() as lease:
        lease.execute('SELECT pg_advisory_lock(719322,11)')
        with pytest.raises(RuntimeError,match='stop_scanner'):switch('phase1','test')
        lease.execute('SELECT pg_advisory_unlock(719322,11)')


def test_budget_block_does_not_claim_event(live,monkeypatch):
    from news_events import runtime
    import ai_budget
    p,src,_,at,_=live;p.ingest(src,at)
    monkeypatch.setattr(ai_budget,'check',Mock(side_effect=ai_budget.BudgetUnavailable('budget_exhausted')))
    with pytest.raises(ai_budget.BudgetUnavailable):runtime.analyze_jobs(at)
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_fills').fetchone()['n']==0


def test_success_before_crash_recovers_outbox_without_more_ai(live,monkeypatch):
    from news_events.engine import Analysis
    from news_events import runtime
    p,src,result,at,_=live;eid=p.ingest(src,at)
    p.analyze(eid,lambda _:Analysis(result),at)
    monkeypatch.setattr(runtime,'completion',Mock(side_effect=AssertionError('must not call AI twice')))
    assert runtime.analyze_jobs(at)['alerts']==1
    assert runtime.analyze_jobs(at)['alerts']==0


def test_canonical_full_budget_usage_outbox_dispatch_once(live,monkeypatch):
    from news_events import runtime
    import ai_budget,requests,stock_scanner,scanner_engine
    p,src,result,at,_=live;eid=p.ingest(src,at)
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    monkeypatch.setenv('OPENROUTER_MODEL','openai/gpt-6-luna')
    monkeypatch.setenv('OPENROUTER_API_KEY','isolated-fixture-not-a-key')
    monkeypatch.setattr(ai_budget,'check',Mock())
    monkeypatch.setattr(ai_budget,'acquire_request_slot',Mock())
    review=dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,duplicate_of=0,material_new_fact=False,explanation='תקין')
    def response(value,n):
        return Mock(raise_for_status=Mock(),json=lambda:{'id':str(n),'choices':[{'message':{'content':None,
            'tool_calls':[{'type':'function','function':{'name':'submit_news_result','arguments':json.dumps(value)}}]},'finish_reason':'tool_calls'}],
            'usage':{'prompt_tokens':100,'completion_tokens':50,'cost':.0001}})
    post=Mock(side_effect=[response(result,1),response(review,2)])
    monkeypatch.setattr(requests,'post',post)
    assert runtime.analyze_jobs(at)['analyzed']==1
    assert post.call_count==2 # One event job, two billable editorial stages.
    for call in post.call_args_list:
        wire=call.kwargs['json']
        assert wire['tool_choice']['function']['name']=='submit_news_result'
        assert 'response_format' not in wire
        assert 'Start with {' not in wire['messages'][0]['content']
    with p.store.transaction() as c:
        assert c.execute('SELECT COUNT(*) n FROM ai_call_usage').fetchone()['n']==2
        assert c.execute('SELECT COUNT(*) n FROM ne_ai_call_links').fetchone()['n']==2
        assert abs(c.execute('SELECT SUM(actual_cost) v FROM ai_call_usage').fetchone()['v']-.0002)<1e-9
        # Make the fixture due relative to the real dispatcher clock.
        c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2020-01-01T00:00:00Z'")
    sender=Mock(return_value='sent')
    monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert scanner_engine.process_telegram_outbox()['sent']==0
    sender.assert_called_once()


def test_terminal_quality_does_not_reanalyze_or_publish(live,monkeypatch):
    from news_events import runtime
    from news_events.analysis import AnalysisFailure
    import ai_budget
    p,src,_,at,_=live;p.ingest(src,at)
    monkeypatch.setattr(ai_budget,'check',Mock())
    ai=Mock(side_effect=AnalysisFailure('news_quality_rejected:faithful',[]))
    monkeypatch.setattr(runtime,'completion',ai)
    runtime.analyze_jobs(at);runtime.analyze_jobs(at)
    ai.assert_called_once()
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0


def test_automatic_safety_rollback_never_changes_trade_tables(live,monkeypatch):
    from news_events import watch
    import ai_operations
    p,_,_,at,_=live
    admin=Mock();monkeypatch.setattr(ai_operations,'enqueue',admin)
    watch.fail_back('test_integrity_alarm',at)
    with p.store.transaction() as c:
        assert c.execute('SELECT mode FROM ne_control').fetchone()['mode']=='phase1'
        for table in ('scanner_trades','scanner_fills','scanner_accounts','scanner_orders'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0
    admin.assert_called_once()


def test_monitor_rollback_retains_safe_prices_context_and_stays_latched(live,monkeypatch):
    from news_events import watch
    import ai_operations
    p,_,_,at,_=live
    monkeypatch.setattr(ai_operations,'enqueue',Mock())
    with p.store.transaction() as c:
        for component,detail in [('monitor','Processed 0 bars'),('prices','NVDA:stale_or_missing_bars token=SECRET')]:
            c.execute('INSERT INTO scanner_service_status VALUES(?,?,?,?,?)',(component,'error',at.isoformat(),at.isoformat(),detail))
    result=watch.check(at)
    assert 'monitor_degraded' in result['alarms']
    assert result['monitor_context']['prices']['reason_codes']==['stale_or_missing_bars']
    assert 'SECRET' not in json.dumps(result['monitor_context'])
    with p.store.transaction() as c:
        assert c.execute('SELECT mode FROM ne_control').fetchone()['mode']=='phase1'
        c.execute("UPDATE scanner_service_status SET status='ok'")
    assert watch.check(at+timedelta(minutes=1)) is None
    with p.store.transaction() as c:
        assert c.execute('SELECT mode FROM ne_control').fetchone()['mode']=='phase1'
        saved=json.loads(c.execute("SELECT value_json FROM scanner_settings WHERE key='news_canonical_health'").fetchone()['value_json'])
        assert saved['monitor_context']==result['monitor_context']


def test_old_event_new_work_does_not_trigger_queue_growth(live,monkeypatch):
    from dataclasses import replace
    from news_events import watch
    from news_events.reporting import report
    from news_events.engine import Analysis
    import ai_operations
    p,src,result,at,_=live
    monkeypatch.setattr(ai_operations,'enqueue',Mock())
    eid=p.ingest(replace(src,source_excerpt=''),at)
    with p.store.transaction(True) as c:
        c.execute("UPDATE ne_events SET status='blocked',reason='insufficient_information' WHERE event_id=?",(eid,))
    later=at+timedelta(minutes=85)
    assert p.ingest(replace(src,collected_at=later.isoformat()),later)==eid
    health=watch.check(later+timedelta(seconds=5))
    assert health['queue_size']==1 and health['oldest_queue_seconds']==5
    assert health['oldest_queue_event_id']==eid and health['alarms']==[]
    assert report(p.store,later+timedelta(seconds=5))['oldest_queue_seconds']==5
    assert p.store.event(eid)['body']['published_at']==at.isoformat()
    ai=Mock(return_value=Analysis(result))
    p.analyze(eid,ai,later);p.analyze(eid,ai,later)
    ai.assert_called_once()
    with p.store.transaction() as c:
        assert c.execute('SELECT mode FROM ne_control').fetchone()['mode']=='canonical'
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0


@pytest.mark.parametrize('status',['pending','analyzing'])
def test_real_stuck_queue_still_triggers_same_safety_limit(live,monkeypatch,status):
    from news_events import watch
    import ai_operations
    p,src,_,at,_=live;eid=p.ingest(src,at)
    monkeypatch.setattr(ai_operations,'enqueue',Mock())
    with p.store.transaction(True) as c:c.execute('UPDATE ne_events SET status=? WHERE event_id=?',(status,eid))
    assert watch.check(at+timedelta(hours=1))['alarms']==[]
    health=watch.check(at+timedelta(hours=1,seconds=1))
    assert health['alarms']==['queue_growth']
    with p.store.transaction() as c:
        assert c.execute('SELECT mode FROM ne_control').fetchone()['mode']=='phase1'
        assert c.execute('SELECT count(*) n FROM scanner_fills').fetchone()['n']==0


def test_queue_volume_limit_unchanged(live,monkeypatch):
    from news_events import watch
    import ai_operations
    p,src,_,at,_=live;eid=p.ingest(src,at)
    monkeypatch.setattr(ai_operations,'enqueue',Mock())
    with p.store.transaction(True) as c:
        for i in range(300):
            c.execute('INSERT INTO ne_events SELECT ?,body_json,evidence_version,status,reason,created_at,updated_at FROM ne_events WHERE event_id=?',(f'queued-{i}',eid))
    health=watch.check(at)
    assert health['queue_size']==301 and health['oldest_queue_seconds']==0
    assert health['alarms']==['queue_growth']


def test_backlog_never_projects_into_dashboard_or_six_hour_review(live):
    from dataclasses import replace
    from news_events.runtime import project
    p,src,_,at,_=live
    eid=p.ingest(replace(src,published_at=(at-timedelta(hours=1)).isoformat()),at)
    assert p.store.event(eid)['reason']=='backlog_blocked'
    assert project(p,eid,at) is None
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM scanner_news').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_trade_news').fetchone()['n']==0


@pytest.mark.parametrize('outcome',['recovered','quality_rejected','terminal'])
def test_canonical_final_admin_outcome_atomic_private_once(live,outcome):
    from news_events.analysis import CanonicalAnalyzer
    from news_events.admin_outcome import persist
    p,src,result,at,_=live;eid=p.ingest(src,at)
    good=dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,duplicate_of=0,
              material_new_fact=False,explanation='תקין')
    usage={'final_alert_owner':True,'cost':.001}
    error=ValueError('openrouter_schema_failed:{"reason":"invalid_json"}')
    error.canonical_usage=usage.copy()
    last=error if outcome=='terminal' else (dict(good,faithful=outcome=='recovered'),usage.copy())
    client=Mock(side_effect=[(result,usage.copy()),error,last])
    status=p.analyze(eid,CanonicalAnalyzer(client),at)
    assert status==('done' if outcome=='recovered' else 'failed')
    p.analyze(eid,CanonicalAnalyzer(client),at);p.recover_interrupted(at)
    assert client.call_count==3
    with p.store.transaction() as c:
        rows=c.execute('SELECT * FROM admin_alerts').fetchall();assert len(rows)==1
        assert rows[0]['status']=='pending'
        text=rows[0]['message']
        assert ('התאוששות' if outcome=='recovered' else 'נדחתה' if outcome=='quality_rejected' else 'כשל סופי') in text
        assert text.splitlines()[-1].startswith('Timestamp: ') and text.endswith('(Israel)')
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_fills').fetchone()['n']==0
    # Reconciliation cannot duplicate or change the original outcome timestamp.
    with p.store.transaction(True) as c:
        v=p.store.event(eid)['evidence_version']
        persist(c,eid,v,status,None,[dict(final_alert_owner=True,success=False)],at)
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM admin_alerts').fetchone()['n']==1
        assert c.execute('SELECT message FROM admin_alerts').fetchone()['message']==text


def test_final_admin_insert_failure_rolls_back_completion_not_telemetry(live,monkeypatch):
    from news_events import admin_outcome
    from news_events.engine import Analysis
    p,src,result,at,_=live;eid=p.ingest(src,at)
    original_persist=admin_outcome.persist
    monkeypatch.setattr(admin_outcome,'persist',Mock(side_effect=RuntimeError('test atomic failure')))
    with pytest.raises(RuntimeError,match='atomic failure'):
        p.analyze(eid,lambda _:Analysis(result),at)
    with p.store.transaction() as c:
        assert c.execute('SELECT status FROM ne_analysis').fetchone()['status']=='running'
        assert c.execute('SELECT count(*) n FROM admin_alerts').fetchone()['n']==0
    monkeypatch.setattr(admin_outcome,'persist',original_persist)
    assert p.recover_interrupted(at+timedelta(hours=1))==1
    assert p.recover_interrupted(at+timedelta(hours=2))==0
    with p.store.transaction() as c:
        rows=c.execute('SELECT message FROM admin_alerts').fetchall();assert len(rows)==1
        assert 'התוצאה אינה ידועה' in rows[0]['message']
