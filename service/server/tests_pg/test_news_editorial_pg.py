"""Canonical publication boundary on disposable PostgreSQL, no live services."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import pytest


@pytest.fixture
def editorial(pg,monkeypatch):
    from database import get_db_connection
    from news_events.store import Store
    from news_events.engine import Pipeline
    from news_events.model import Source
    from news_events import runtime
    now=datetime(2026,10,22,12,tzinfo=timezone.utc)
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME','true')
    with get_db_connection() as c:
        assert c.execute('SELECT current_schema() name').fetchone()['name'].startswith('test_')
        c.execute("UPDATE ne_control SET mode='canonical',not_before=?,epoch=57 WHERE id=1",((now-timedelta(minutes=1)).isoformat(),))
    store=Store(get_db_connection,production=True)
    p=Pipeline(store,{},lambda:(set(),set()),not_before=now-timedelta(minutes=1))
    monkeypatch.setattr(runtime,'pipeline',lambda:p)
    monkeypatch.setattr(runtime,'now',lambda:now)
    monkeypatch.setattr(runtime,'membership',lambda *a:(set(),set()))
    source=Source('fixture','qoq','https://example.invalid/articles/10001','Synthetic source',
        now.isoformat(),now.isoformat(),'New Zealand CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)','',
        event_type='market',rights='approved')
    result=dict(related=True,title_he='מדד המחירים לצרכן פורסם',summary_he='פורסמו נתונים לתקופה המדווחת.',
        interpretation_he='זהו נתון כלכלי ולא המלצת מסחר.',sentiment='neutral',materiality='medium',relevance=.8)
    return p,source,result,now


def test_low_materiality_stored_but_not_enqueued(editorial):
    from news_events.engine import Analysis
    from news_events.runtime import queue_outbox
    p,src,result,now=editorial
    eid=p.ingest(src,now)
    assert p.analyze(eid,lambda e:Analysis({**result,'materiality':'low'}),now)=='done'
    assert queue_outbox(p,eid,now)==0
    assert p.store.event(eid)['reason']=='low_importance'
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']==0


def test_release_update_restart_stale_outbox_and_conflict(editorial):
    from news_events.engine import Analysis,Pipeline
    from news_events.store import Store
    from news_events.runtime import queue_outbox,delivery_message
    p,src,result,now=editorial
    eid=p.ingest(src,now)
    assert p.analyze(eid,lambda e:Analysis(result),now)=='done'
    assert queue_outbox(p,eid,now)==1
    with p.store.transaction() as c:
        old=dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
    assert delivery_message(old)
    annual=replace(src,provider_id='second',source_id='yoy',url='https://example.invalid/articles/10002',
        title='New Zealand CPI (Y/Y) Q3: 3.7% (est 3.8%; prev 4.1%)')
    assert p.ingest(annual,now)==eid
    assert delivery_message(old) is None  # Old version cannot send.
    assert p.analyze(eid,lambda e:Analysis(result),now)=='done'
    assert queue_outbox(p,eid,now)==1
    restarted=Pipeline(Store(p.store.connect,production=True),{},p.membership,not_before=p.not_before)
    assert restarted.ingest(annual,now)==eid
    assert queue_outbox(restarted,eid,now)==0
    conflicting=replace(src,provider_id='conflict',source_id='revision',url='https://example.invalid/articles/10003',
        title='New Zealand CPI (Q/Q) Q3: 0.9% (est 0.8%; prev 1.5%)')
    assert restarted.ingest(conflicting,now)==eid
    assert restarted.store.event(eid)['reason']=='source_conflict'
    with p.store.transaction() as c:
        for row in c.execute('SELECT * FROM scanner_telegram_outbox'):
            assert delivery_message(dict(row)) is None
        assert c.execute('SELECT count(*) n FROM ne_events').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM ne_sources').fetchone()['n']==3
        assert c.execute('SELECT count(*) n FROM ne_versions').fetchone()['n']==3
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==2
        assert c.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_fills').fetchone()['n']==0
