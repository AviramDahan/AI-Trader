"""Production boundary on disposable PostgreSQL schemas, no network/senders."""
import json
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock
import pytest


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
        return Mock(raise_for_status=Mock(),json=lambda:{'id':str(n),'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':50,'cost':.0001}})
    post=Mock(side_effect=[response(result,1),response(review,2)])
    monkeypatch.setattr(requests,'post',post)
    assert runtime.analyze_jobs(at)['analyzed']==1
    assert post.call_count==2 # One event job, two billable editorial stages.
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
