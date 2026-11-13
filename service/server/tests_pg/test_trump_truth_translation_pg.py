"""Real PostgreSQL leases/cache/recovery, synthetic posts and inference only."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

AT=datetime(2026,10,22,13,tzinfo=timezone.utc)


@pytest.fixture
def source(pg,monkeypatch):
    import trump_truth_posts as t,scanner_engine,stock_scanner
    from database import get_db_connection
    for key,value in {'TELEGRAM_TRUMP_TRUTH_ENABLED':'true','TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED':'true',
        'TELEGRAM_TRUMP_TRUTH_NOT_BEFORE':(AT-timedelta(minutes=5)).isoformat(),
        'TELEGRAM_MARKET_NEWS_THREAD_ID':'991','NEWS_EVENTS_RUNTIME':'false'}.items():monkeypatch.setenv(key,value)
    monkeypatch.setattr(scanner_engine,'now_z',lambda:AT.isoformat())
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    text=t.HEADER+'\nWe will not raise tariffs by 5%.\n'+t.LABEL
    msg=NS(id=10,date=AT,message=text,action=None,peer_id=NS(channel_id=t.CHANNEL_ID),
        entities=[NS(offset=len(text[:text.rindex(t.LABEL)].encode('utf-16-le'))//2,length=len(t.LABEL),
                     url='https://truthsocial.com/@realDonaldTrump/117500000000000123')])
    item,reason=t.extract(msg,AT)
    assert reason is None and t.ingest([item],AT)['inserted']==1
    return get_db_connection


def approved(system,payload,schema):
    return ({'text_he':'לא נעלה את המכסים ב־5%.'} if 'text_he' in schema['properties'] else
            {'faithful':True,'fluent_hebrew':True,'complete':True,'unsupported_claims':False})


def row(connect):
    with connect() as c:return dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())


def test_concurrent_preparation_one_lease_two_local_requests(source):
    import trump_truth_translation as h
    call=Mock(side_effect=approved)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:h.prepare(at=AT,completion=call),range(3)))
    assert sum(v['prepared'] for v in results)==1 and call.call_count==2
    assert row(source)['status']==h.READY


def test_model_runs_outside_transaction_and_retry_dispatch_is_cached(source,monkeypatch):
    import trump_truth_translation as h,scanner_engine as engine,stock_scanner
    def callback(*args):
        # Separate connection can NOWAIT lock the row while generation is active.
        with source() as c:
            c.execute('SELECT id FROM scanner_telegram_outbox FOR UPDATE NOWAIT')
        return approved(*args)
    assert h.prepare(at=AT,completion=callback)['prepared']==1
    sender=Mock(side_effect=['connect_timeout','sent'])
    monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    monkeypatch.setattr(h,'local_json',lambda *a:pytest.fail('model in send'))
    assert engine.process_telegram_outbox()['failed']==1 and row(source)['status']==h.RETRY
    with source() as c:c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    assert engine.process_telegram_outbox()['sent']==1
    assert engine.process_telegram_outbox()['sent']==0 and sender.call_count==2


def test_restart_stale_preparation_preserves_last_attempt_budget(source):
    import trump_truth_translation as h,trump_truth_posts as t
    r=row(source);envelope=json.loads(r['message'])
    value={'version':h.VERSION,'binding':h.binding(r,envelope),'attempts':2,'status':'working','text_he':''}
    with source() as c:
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',(h.cache_key(r),h.wire(value),AT.isoformat()))
        c.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=?',(h.WORKING,(AT-timedelta(seconds=1)).isoformat()))
    assert h.prepare(at=AT,completion=lambda *a:pytest.fail('third translation'))['prepared']==1
    assert 'אינו זמין' in t.delivery_message(row(source),AT)


def test_rollback_previous_deployed_selector_ignores_every_hebrew_state(source):
    import trump_truth_translation as h
    for state in (h.PENDING,h.WORKING,h.READY,h.RETRY,h.SENDING):
        with source() as c:
            c.execute('UPDATE scanner_telegram_outbox SET status=?',(state,))
            assert not c.execute("SELECT id FROM scanner_telegram_outbox WHERE status IN ('pending','retry','community_pending','trump_pending','trump_retry') AND next_attempt_at<=?",(AT.isoformat(),)).fetchall()


def test_missing_cache_after_active_restore_never_sends_english(source,monkeypatch):
    import trump_truth_translation as h,scanner_engine as engine,stock_scanner
    assert h.prepare(at=AT,completion=approved)['prepared']==1
    with source() as c:c.execute("DELETE FROM scanner_settings WHERE key LIKE 'trump_truth_hebrew_v1:%'")
    sender=Mock();monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    assert engine.process_telegram_outbox()['sent']==0
    assert sender.call_count==0 and row(source)['status']=='cancelled'


def test_unknown_delivery_after_restart_never_auto_resends_and_no_trading_writes(source,monkeypatch):
    import trump_truth_translation as h,scanner_engine as engine,stock_scanner
    h.prepare(at=AT,completion=approved)
    with source() as c:
        c.execute("UPDATE scanner_telegram_outbox SET status=?,next_attempt_at='2000-01-01T00:00:00Z'",(h.SENDING,))
    sender=Mock();monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    assert engine.process_telegram_outbox()['sent']==0 and sender.call_count==0
    assert row(source)['status']=='failed' and 'unknown' in row(source)['last_error']
    with source() as c:
        for table in ('scanner_orders','scanner_trades','scanner_signals','scanner_fills','scanner_news'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n']==0
