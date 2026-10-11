"""Real PostgreSQL + age, restored holds/Legacy/Shadow and retained contracts."""
import sys
import json
import copy
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_single_breakout as fixture
import database,scanner_engine as engine,recovery_state as recovery,active_snapshot
from test_recovery_holds import initialize_empty,target_schema,state,seed_legacy,record
from test_postgres_cloud import _sqlite_portfolio


@pytest.mark.usefixtures('pg')
class TestBreakoutPostgres(fixture.TestBreakoutLifecycle):
    pass


def seed_contract(ticker):
    p=fixture.plan()
    s=dict(ticker=ticker,company='Synthetic',action='BUY',entry=100,stop_loss=p['stop'],
           target_plan=p,confidence=.9,time_horizon='days',reason='synthetic',relevant_news=[])
    with patch.dict('os.environ',fixture.FLAGS),patch.object(engine,'now_z',return_value='2026-10-06T14:00:37Z'):
        return engine.record_signal(s,{}, {}, {}, 'isolated-breakout')['id']


def test_encrypted_v5_roundtrip_restart_and_compatible_return(pg,tmp_path):
    # Retain V1 Native/Shadow and Legacy alongside a new contract and expired hold.
    source,last=_sqlite_portfolio(tmp_path)
    active_snapshot.import_data(active_snapshot.export_data(source),pg)
    seed_legacy()
    active=seed_contract('BRKTEST')
    bar=dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)
    engine.process_bar('BRKTEST',bar)
    held=seed_contract('HELDTEST')
    engine._pending_recovery_check('HELDTEST',[],datetime(2026,10,6,14,10,tzinfo=timezone.utc))
    before=state();data=recovery.export_postgres(pg)
    assert data['recovery_format']==data['version']==5
    assert len(data['hold_coverage']['order_ids'])==1
    assert data['hold_coverage']['entry_reserved_notional']==before['reserved'][0]['amount']
    assert any(t['is_shadow'] for t in data['tables']['scanner_trades'])
    assert any(t['legacy_position_id'] for t in data['tables']['scanner_trades'])
    key=tmp_path/'identity'
    subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()
    encrypted,_=recovery.encrypted_bytes(data,recipient)
    path=tmp_path/'synthetic.age';path.write_bytes(encrypted)
    decoded=recovery.decrypt(path,key);assert decoded==data
    with target_schema(pg) as target,patch.dict('os.environ',STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED='false',STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED='false'):
        recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
        assert state()==before
        with database.get_db_connection() as c:
            assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        # Reader/executor-compatible rollback with creation OFF, restart and rebackup.
        engine.initialize_runtime();engine.process_bar('BRKTEST',bar)
        assert state()==before
        assert record('HELDTEST')['status']=='DUPLICATE_BLOCKED'
        assert state()==before
        again=recovery.export_postgres(target)
        assert again['version']==5 and again['hold_coverage']==data['hold_coverage']
        engine.process_bar('BRKTEST',{**bar,'at':'2026-10-06T14:10:00Z','open':104.5,'high':105,'low':104,'close':104.5})
        after=state()
        assert after['reserved']==before['reserved'] and after['holds']==before['holds']
        assert len(after['fills'])==len(before['fills'])+1
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        with pytest.raises(ValueError,match='already_imported'):
            recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
        assert state()==after
    for damage in ('version','window','hold','unknown'):
        broken=copy.deepcopy(data);broken.pop('snapshot_id')
        if damage=='version':broken['version']=broken['recovery_format']=4
        if damage=='hold':broken['hold_coverage']['entry_reserved_notional']+=1
        if damage=='window':
            o=next(o for o in broken['tables']['scanner_orders'] if o['signal_id']==held)
            contract=json.loads(o['plan_json']);contract['entry_execution']['entry_eligible_from']='2026-10-06T13:55:00Z'
            o['plan_json']=json.dumps(contract)
        if damage=='unknown':
            s=next(s for s in broken['tables']['scanner_signals'] if s['id']==held)
            p=json.loads(s['technical_json']);p['target_plan']['policy_version']='unrecognized_future_contract'
            s['technical_json']=json.dumps(p)
        with target_schema(pg) as target:
            with pytest.raises(ValueError):recovery.restore(broken,target,'synthetic-token-longer-than-32-characters')
            with database.get_db_connection() as c:
                assert c.execute('SELECT count(*) n FROM agents').fetchone()['n']==0


def test_no_new_contract_keeps_existing_format(pg):
    initialize_empty()
    assert recovery.export_postgres(pg)['recovery_format']==2
