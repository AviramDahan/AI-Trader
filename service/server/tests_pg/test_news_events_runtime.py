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
