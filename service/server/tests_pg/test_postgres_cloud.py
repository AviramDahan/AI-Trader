import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
import psycopg

import active_snapshot
import database
import migrations
import scanner_engine as engine
from cloud_runtime import RoleLease

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_scanner_engine as lifecycle_tests


@pytest.mark.usefixtures('pg')
class TestExistingLifecycleOnPostgres(lifecycle_tests.ScannerEngineTests):
    """Run the existing unmodified lifecycle regression scenarios against PG."""
    pass


def test_migrations_idempotent_and_natural_key_upsert(pg):
    migrations.migrate()
    with database.get_db_connection() as conn:
        assert conn.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n']==2
        conn.execute("INSERT INTO scanner_quotes(ticker,price,as_of,source) VALUES('TEST',1,'2026-01-01','test')")
        conn.execute("INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('x','{}','2026-01-01')")


def test_duplicate_role_blocked_but_monitor_independent(pg):
    first=RoleLease('scanner')
    try:
        with pytest.raises(RuntimeError,match='already_owned'):
            RoleLease('scanner')
        monitor=RoleLease('monitor')
        monitor.check(); monitor.close()
    finally:
        first.close()
    replacement=RoleLease('scanner'); replacement.close()


def test_atomic_concurrent_outbox_claim(pg):
    with database.get_db_connection() as conn:
        for n in range(12):
            conn.execute("""INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at)
                VALUES(?,?,?,'pending',0,'2000-01-01','2000-01-01')""",(str(n),'test','isolated test'))
    with ThreadPoolExecutor(2) as pool:
        batches=list(pool.map(lambda _:engine._claim_telegram_outbox(6),range(2)))
    ids=[row['id'] for batch in batches for row in batch]
    assert len(ids)==len(set(ids))==12
    assert engine._claim_telegram_outbox(20)==[]


def _sqlite_portfolio(tmp_path):
    # Reuse original engine and simulation rules, only isolated database/provider.
    path=tmp_path/'source.db'
    with patch.object(database,'DATABASE_URL',''),patch.object(database,'_SQLITE_DB_PATH',str(path)):
        database.init_database()
        with database.get_db_connection() as conn:
            conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','test-only',100000)")
        engine.initialize_runtime()
        signal={'signal_id':None,'ticker':'AAPL','company':'Apple','action':'BUY','entry':100,'stop_loss':97,
                'confidence':.91,'time_horizon':'1-4 weeks','reason':'test','telegram_reason_he':'בדיקה',
                'telegram_news_he':[],'relevant_news':[]}
        candidate={'ticker':'AAPL','company':'Apple','technical_score':7,'combined_rank_score':.92,'atr':2,'average_dollar_volume':1e9}
        engine.record_signal(signal,candidate,{'action':'BUY','confidence':.91,'news_relevance':.9,'news_sentiment':.4},{},'test-scan')
        from datetime import datetime,timedelta,timezone
        at=datetime.now(timezone.utc)+timedelta(minutes=1)
        bar={'at':at.isoformat(),'open':100,'high':101,'low':99,'close':100}
        engine.process_bar('AAPL',bar)
        # TP1 is shadow only under unchanged single primary strategy.
        later={**bar,'at':(at+timedelta(minutes=5)).isoformat(),'open':103.5,'high':103.6,'low':103.4,'close':103.5}
        engine.process_bar('AAPL',later)
    return path, later


def test_active_snapshot_preserves_partial_fills_restarts_and_shadow(pg,tmp_path):
    with patch('telegram_status.refresh_telegram_status_cards',return_value={}):
        source,last_bar=_sqlite_portfolio(tmp_path)
        snapshot=active_snapshot.export_data(source)
        assert any(f['fill_type']=='tp' for f in snapshot['tables']['scanner_fills'])
        active_snapshot.import_data(snapshot,pg)
        with database.get_db_connection() as conn:
            before=[dict(r) for r in conn.execute('SELECT * FROM scanner_fills ORDER BY id').fetchall()]
            cash=conn.execute('SELECT cash FROM scanner_accounts').fetchone()['cash']
            assert conn.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        engine.process_bar('AAPL',last_bar)  # Replay after restart must do nothing.
        with database.get_db_connection() as conn:
            assert [dict(r) for r in conn.execute('SELECT * FROM scanner_fills ORDER BY id').fetchall()]==before
            assert conn.execute('SELECT cash FROM scanner_accounts').fetchone()['cash']==cash
        with pytest.raises(ValueError,match='already_imported'):
            active_snapshot.import_data(snapshot,pg)
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


def test_snapshot_import_refuses_running_monitor(pg,tmp_path):
    source,_=_sqlite_portfolio(tmp_path)
    data=active_snapshot.export_data(source)
    lease=RoleLease('monitor')
    try:
        with pytest.raises(ValueError,match='workers_must_be_stopped'):
            active_snapshot.import_data(data,pg)
    finally:
        lease.close()


def test_snapshot_validation_refuses_corrupt_partial_accounting(pg,tmp_path):
    source,_=_sqlite_portfolio(tmp_path)
    data=active_snapshot.export_data(source)
    del data['snapshot_id']
    data['tables']['scanner_trades'][0]['remaining_quantity']-=.1
    with pytest.raises(ValueError,match='fill_accounting_mismatch'):
        active_snapshot.validate(data)


def test_migrated_portfolio_continues_identically_to_sqlite(pg,tmp_path):
    source,last_bar=_sqlite_portfolio(tmp_path)
    data=active_snapshot.export_data(source)
    active_snapshot.import_data(data,pg)
    from datetime import datetime,timedelta
    bars=[{**last_bar,'at':(datetime.fromisoformat(last_bar['at'])+timedelta(minutes=5)).isoformat(),
           'open':107,'high':107.1,'low':106.9,'close':107},
          {**last_bar,'at':(datetime.fromisoformat(last_bar['at'])+timedelta(minutes=10)).isoformat(),
           'open':110,'high':110.1,'low':109.9,'close':110}]
    def execute():
        for bar in bars:
            engine.process_bar('AAPL',bar)
            engine.process_bar('AAPL',bar)
        with database.get_db_connection() as conn:
            return [[dict(r) for r in conn.execute(query).fetchall()] for query in (
                'SELECT cash,realized_pnl,fees_paid FROM scanner_accounts ORDER BY id',
                'SELECT id,strategy,is_shadow,status,remaining_quantity,current_stop,realized_pnl,fees,outcome FROM scanner_trades ORDER BY id',
                'SELECT trade_id,fill_type,target_index,quantity,price,gross_pnl,fee FROM scanner_fills ORDER BY id')]
    with patch.object(database,'DATABASE_URL',''),patch.object(database,'_SQLITE_DB_PATH',str(source)):
        expected=execute()
    assert execute()==expected


def test_concurrent_price_bar_cannot_double_fill(pg,tmp_path):
    source,last_bar=_sqlite_portfolio(tmp_path)
    active_snapshot.import_data(active_snapshot.export_data(source),pg)
    from datetime import datetime,timedelta
    bar={**last_bar,'at':(datetime.fromisoformat(last_bar['at'])+timedelta(minutes=5)).isoformat(),
         'open':107,'high':107.1,'low':106.9,'close':107}
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _:engine.process_bar('AAPL',bar),range(2)))
    with database.get_db_connection() as conn:
        rows=conn.execute("SELECT event_key,count(*) n FROM scanner_fills GROUP BY event_key").fetchall()
        assert all(r['n']==1 for r in rows)
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


def test_price_execution_completes_while_ai_is_stalled(pg,tmp_path):
    """No external call: a stalled AI task cannot own an accounting transaction."""
    import threading
    import time
    import requests
    import ai_provider
    from datetime import datetime,timedelta
    source,last_bar=_sqlite_portfolio(tmp_path)
    active_snapshot.import_data(active_snapshot.export_data(source),pg)
    entered=threading.Event()
    release=threading.Event()
    def stalled_ai(*args,**kwargs):
        entered.set()
        release.wait(20)
        raise requests.Timeout('isolated AI timeout')
    with patch.dict(os.environ,{'OPENROUTER_API_KEY':'isolated-test-key','OPENROUTER_NEWS_MODEL':'test/model'}), \
         patch.object(ai_provider.requests,'post',side_effect=stalled_ai), ThreadPoolExecutor(1) as pool:
        future=pool.submit(ai_provider.json_completion,'Isolated test',{})
        assert entered.wait(2)
        try:
            bar={**last_bar,'at':(datetime.fromisoformat(last_bar['at'])+timedelta(minutes=5)).isoformat(),
                 'open':107,'high':107.1,'low':106.9,'close':107}
            started=time.perf_counter()
            engine.process_bar('AAPL',bar)
            print('STAGING_MONITOR_PROCESS_MS='+str(round((time.perf_counter()-started)*1000,3)))
            assert not future.done()
            assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        finally:
            release.set()
        with pytest.raises(ValueError,match='openrouter_transport_failed'):
            future.result(timeout=2)


def test_api_dashboard_reads_imported_postgres_portfolio(pg,tmp_path,monkeypatch):
    source,_=_sqlite_portfolio(tmp_path)
    active_snapshot.import_data(active_snapshot.export_data(source),pg)
    monkeypatch.setenv('AI_TRADER_API_BACKGROUND_TASKS','false')
    from routes import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app()) as client:
        response=client.get('/api/scanner/dashboard')
    assert response.status_code==200
    value=response.json()
    assert value['paper_only'] is True
    assert value['main_portfolio']['open_position_count']==1
    assert value['lifecycle_verification']['accounting_ok']
