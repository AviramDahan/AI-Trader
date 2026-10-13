"""Same full application price-retry regressions in real isolated PostgreSQL."""
import sys
from pathlib import Path
import pytest
import copy
import json
import subprocess
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_entry_price_retry as fixture


@pytest.mark.usefixtures('pg')
class TestPriceRetryPostgres(fixture.TestPriceRetryLifecycle):
    pass


def record_retry(ticker):
    import scanner_engine as engine
    p=fixture.narrow_plan()
    signal=dict(ticker=ticker,company='Synthetic',action='BUY',entry=100,stop_loss=p['stop'],
                target_plan=p,confidence=.91,time_horizon='days',reason='synthetic',relevant_news=[])
    cfg=engine.lifecycle_settings() | {'active_strategy':'single','slippage_bps':5}
    with patch.dict('os.environ',fixture.FLAGS),patch.object(engine,'now_z',return_value=fixture.STAMP),patch.object(engine,'lifecycle_settings',return_value=cfg):
        return engine.record_signal(signal,{}, {}, {}, 'synthetic-price-retry')


def process(ticker,minute,opening):
    import scanner_engine as engine
    bar=dict(at=f'2026-10-06T14:{minute:02d}:00Z',open=opening,high=max(opening+.2,100.2),
             low=min(opening-.1,99.99),close=opening+.05)
    with patch.object(engine,'now_z',return_value='2026-10-06T14:30:00Z'):
        engine.process_bar(ticker,bar)
    return bar


@pytest.mark.parametrize('mixed',[False,True])
def test_real_age_format6_roundtrip_holds_legacy_shadow_short_and_restart(pg,tmp_path,mixed):
    import database,scanner_engine as engine,recovery_state as recovery,active_snapshot
    import test_automatic_short as short_fixture
    from test_recovery_holds import initialize_empty,seed_legacy,record,state,target_schema
    initialize_empty()
    if mixed:
        seed_legacy()
        with patch.object(engine,'now_z',return_value=fixture.STAMP):record('BASE')
        process('BASE',5,100.05)  # Normal V1 Native + STAGED Shadow are preserved.
        short_fixture.record();engine.process_bar('SHORTTEST',short_fixture.bar())
        record_retry('ACTIVE');process('ACTIVE',5,99.8);process('ACTIVE',10,100.05)
    record_retry('HELD');process('HELD',5,99.8)
    later=dict(at='2026-10-06T14:15:00Z',open=100,high=100.2,low=99.9,close=100.1)
    engine._pending_recovery_check('HELD',[later],datetime(2026,10,6,14,20,tzinfo=timezone.utc))
    before=state();data=recovery.export_postgres(pg)
    assert data['version']==data['recovery_format']==6
    assert len(data['hold_coverage']['order_ids'])==1
    assert data['hold_coverage']['entry_reserved_notional']==before['reserved'][0]['amount']
    if mixed:
        assert any(t['is_shadow'] for t in data['tables']['scanner_trades'])
        assert any(t['legacy_position_id'] for t in data['tables']['scanner_trades'])
        assert any(t['side']=='short' for t in data['tables']['scanner_trades'])
    key=tmp_path/'synthetic-identity'
    subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()
    encrypted,_=recovery.encrypted_bytes(data,recipient)
    path=tmp_path/'synthetic.age';path.write_bytes(encrypted)
    decoded=recovery.decrypt(path,key);assert decoded==data
    with target_schema(pg) as target,patch.dict('os.environ',STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED='false',
        STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED='false',STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED='false'):
        recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
        assert state()==before
        with database.get_db_connection() as c:assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        engine.initialize_runtime();engine.process_bar('HELD',later)
        engine._expire_recovered_orders('HELD',datetime(2026,10,9,tzinfo=timezone.utc))
        assert state()==before and record('HELD')['status']=='DUPLICATE_BLOCKED'
        assert state()==before
        again=recovery.export_postgres(target)
        assert again['version']==6 and again['hold_coverage']==data['hold_coverage']
        if mixed:
            with patch.object(engine,'now_z',return_value='2026-10-06T14:30:00Z'):
                engine.process_bar('ACTIVE',dict(at='2026-10-06T14:15:00Z',open=103,high=103.2,low=102.8,close=103.1))
            after=state()
            assert len(after['fills'])==len(before['fills'])+1
            assert after['holds']==before['holds'] and after['reserved']==before['reserved']
            assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        stable=state()
        with pytest.raises(ValueError,match='already_imported'):recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
        assert state()==stable
    for damage in ('format','version','observation','reservation'):
        broken=copy.deepcopy(data);broken.pop('snapshot_id')
        held=next(o for o in broken['tables']['scanner_orders'] if o['status']=='recovery_uncertain')
        contract=json.loads(held['plan_json'])
        if damage=='format':broken['version']=broken['recovery_format']=5
        if damage=='version':contract['entry_price_retry']['version']='unsupported'
        if damage=='observation':contract['last_entry_price_block']['reason']='fill_rr_below_2'
        if damage=='reservation':broken['hold_coverage']['entry_reserved_notional']+=1
        held['plan_json']=json.dumps(contract)
        broken['snapshot_id']=active_snapshot.digest(broken)
        expected={'format':'entry_price_retry_requires_format6','version':'unsupported_entry_price_retry',
                  'observation':'entry_price_retry_contract_invalid','reservation':'recovery_hold_reservation_mismatch'}[damage]
        with target_schema(pg) as target:
            with pytest.raises(ValueError,match=expected):recovery.restore(broken,target,'synthetic-token-longer-than-32-characters')
            with database.get_db_connection() as c:assert c.execute('SELECT count(*) n FROM agents').fetchone()['n']==0
