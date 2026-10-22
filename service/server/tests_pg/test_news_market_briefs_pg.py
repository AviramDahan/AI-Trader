"""Real outbox/dispatch contracts on disposable test_* PostgreSQL schemas."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock
import pytest
from test_news_editorial_pg import editorial


def brief(editorial):
    p,src,result,now=editorial
    p.policy=replace(p.policy,market_briefs_enabled=True)
    return p,src,{**result,'materiality':'low'},now


def test_brief_real_outbox_dedupe_restart_and_live_flag_revocation(editorial,monkeypatch):
    from news_events.engine import Analysis,Pipeline
    from news_events.store import Store
    from news_events import runtime
    p,src,result,now=brief(editorial)
    eid=p.ingest(src,now);analyzer=Mock(return_value=Analysis(result))
    assert p.analyze(eid,analyzer,now)=='done'
    assert runtime.queue_outbox(p,eid,now)==1
    with p.store.transaction() as c:
        row=dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        assert row['event_type']=='market_news'
        assert c.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_fills').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_news_jobs').fetchone()['n']==0
    assert runtime.delivery_message(row).startswith('📰 עדכון שוק קצר')
    restarted=Pipeline(Store(p.store.connect,production=True),{},p.membership,not_before=p.not_before,policy=p.policy)
    monkeypatch.setattr(runtime,'pipeline',lambda:restarted)
    assert restarted.ingest(src,now)==eid
    assert runtime.queue_outbox(restarted,eid,now)==0
    restarted.policy=replace(restarted.policy,market_briefs_enabled=False)
    assert runtime.delivery_message(row) is None
    assert runtime.queue_outbox(restarted,eid,now)==0
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==1
    analyzer.assert_called_once()


def test_flag_on_does_not_replay_old_low_importance_history(editorial,monkeypatch):
    from news_events.engine import Analysis
    from news_events import runtime
    import scanner_engine
    p,src,result,now=editorial
    eid=p.ingest(src,now);assert p.analyze(eid,lambda _:Analysis({**result,'materiality':'low'}),now)=='done'
    assert runtime.queue_outbox(p,eid,now)==0
    p.policy=replace(p.policy,market_briefs_enabled=True)
    monkeypatch.setattr(scanner_engine,'set_service_status',Mock())
    monkeypatch.setattr(runtime,'completion',Mock(side_effect=AssertionError('No historical AI replay')))
    assert runtime.analyze_jobs(now)==dict(analyzed=0,alerts=0,errors=[])
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==1
    assert p.store.event(eid)['reason']=='low_importance'


@pytest.mark.parametrize('invalidate', ['epoch','expiry','withdraw','version'])
def test_send_time_safety_gates_remain_authoritative(editorial,invalidate,monkeypatch):
    from news_events.engine import Analysis
    from news_events import runtime
    p,src,result,now=brief(editorial)
    eid=p.ingest(src,now);p.analyze(eid,lambda _:Analysis(result),now)
    assert runtime.queue_outbox(p,eid,now)==1
    with p.store.transaction() as c:row=dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
    if invalidate=='epoch':
        with p.store.transaction(True) as c:c.execute('UPDATE ne_control SET epoch=epoch+1 WHERE id=1')
    elif invalidate=='expiry':monkeypatch.setattr(runtime,'now',lambda:now+timedelta(hours=7))
    elif invalidate=='withdraw':p.store.withdraw(src.provider_id,src.source_id,now)
    else:
        update=replace(src,provider_id='second',source_id='annual',url='https://example.invalid/articles/10002',
            title='New Zealand CPI (Y/Y) Q3: 3.7% (est 3.8%; prev 4.1%)')
        assert p.ingest(update,now)==eid
    assert runtime.delivery_message(row) is None
