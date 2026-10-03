"""No external services: real PostgreSQL, real age, application restart/restore."""
import sys,json,subprocess,copy
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_single_target_v2 as fixture
import database,scanner_engine as engine,recovery_state as recovery,active_snapshot
from test_recovery_holds import initialize_empty,target_schema,state,seed_legacy


@pytest.mark.usefixtures('pg')
class TestV2Postgres(fixture.TestV2Lifecycle):
    pass


def test_encrypted_v3_roundtrip_with_legacy_and_blocked_order(pg,tmp_path):
    initialize_empty();seed_legacy()
    def record(ticker):
        p=fixture.plan()
        s=dict(ticker=ticker,company='Synthetic',action='BUY',entry=100,stop_loss=p['stop'],
               target_plan=p,confidence=.9,time_horizon='days',reason='synthetic',relevant_news=[])
        with patch.object(engine,'now_z',return_value='2026-09-28T13:30:00Z'):
            return engine.record_signal(s,{}, {}, {}, 'isolated-v2')['id']
    first=record('V2TEST')
    bar=dict(at='2026-09-28T13:35:00Z',open=100,high=101,low=99.5,close=100)
    engine.process_bar('V2TEST',bar)
    held=record('V2HOLD')
    with database.get_db_connection() as c:
        c.execute("UPDATE scanner_orders SET status='recovery_uncertain' WHERE signal_id=?",(held,))
        c.execute("UPDATE scanner_signals SET status='RECOVERY_UNCERTAIN' WHERE id=?",(held,))
    before=state();data=recovery.export_postgres(pg)
    assert data['version']==data['recovery_format']==3
    assert len(data['hold_coverage']['order_ids'])==1
    key=tmp_path/'identity'
    subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()
    encrypted,_=recovery.encrypted_bytes(data,recipient)
    path=tmp_path/'synthetic.age';path.write_bytes(encrypted)
    decoded=recovery.decrypt(path,key)
    assert decoded==data
    with target_schema(pg) as target:
        recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
        assert state()==before
        engine.initialize_runtime();engine.process_bar('V2TEST',bar)
        assert state()==before
        assert record('V2HOLD')!=held
        with database.get_db_connection() as c:
            assert c.execute("SELECT status FROM scanner_signals ORDER BY id DESC LIMIT 1").fetchone()['status']=='DUPLICATE_BLOCKED'
        engine.process_bar('V2TEST',{**bar,'at':'2026-09-28T13:40:00Z','open':105,'high':106,'low':104,'close':105})
        after=state()
        assert after['reserved']==before['reserved']
        assert len(after['fills'])==len(before['fills'])+1
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        with pytest.raises(ValueError,match='already_imported'):
            recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
    damaged=copy.deepcopy(data);damaged.pop('snapshot_id');damaged['version']=damaged['recovery_format']=2
    with pytest.raises(ValueError,match='format3'):recovery.validate(damaged)
    damaged=copy.deepcopy(data);damaged.pop('snapshot_id')
    order=next(o for o in damaged['tables']['scanner_orders'] if o['signal_id']==first)
    order['plan_json']='{}'
    with pytest.raises(ValueError,match='contract'):recovery.validate(damaged)
