"""Isolated PostgreSQL + real age; never production or external HTTP."""
import copy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_automatic_short as fixture
import database, scanner_engine as engine, recovery_state as recovery
from test_recovery_holds import initialize_empty, seed_legacy, target_schema, state, record as long_record


@pytest.mark.usefixtures('pg')
class TestShortPostgres(fixture.TestAutomaticShort):
    pass


def test_real_age_format4_restore_legacy_long_shadow_short_and_hold(pg,tmp_path):
    initialize_empty();seed_legacy()
    with patch.object(engine,'now_z',return_value='2026-09-28T13:30:00Z'):
        long_record('LONGTEST')
    engine.process_bar('LONGTEST',fixture.bar())
    fixture.record();engine.process_bar('SHORTTEST',fixture.bar())
    fixture.record('HELD')
    from datetime import datetime,timezone
    engine._pending_recovery_check('HELD',[],datetime(2026,9,28,13,50,tzinfo=timezone.utc))
    with database.get_db_connection() as c:
        # Original validity elapsed; a hold must still reserve collateral.
        c.execute("UPDATE scanner_orders SET valid_until='2026-09-28T13:45:00Z' WHERE status='recovery_uncertain'")
    before=state();data=recovery.export_postgres(pg)
    assert data['recovery_format']==data['version']==4
    assert data['hold_coverage']['entry_reserved_notional']==100
    key=tmp_path/'synthetic-identity'
    subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()
    encrypted,_=recovery.encrypted_bytes(data,recipient)
    path=tmp_path/'synthetic.age';path.write_bytes(encrypted)
    decoded=recovery.decrypt(path,key)
    assert decoded==data
    with target_schema(pg) as target:
        recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
        assert state()==before
        with patch.dict('os.environ',STOCK_SCANNER_SHORT_ENABLED='false'):
            engine.initialize_runtime()
            for ticker in ('SHORTTEST','LONGTEST','HELD'):engine.process_bar(ticker,fixture.bar())
        assert state()==before
        assert fixture.record('HELD')['status']=='DUPLICATE_BLOCKED'
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        # Disabling new creation must not disable short TP, long TP or Legacy.
        engine.process_bar('SHORTTEST',fixture.bar(40,open=96,high=96.5,low=95,close=95.2))
        engine.process_bar('LONGTEST',fixture.bar(40,open=110,high=111,low=109,close=110))
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        after=state();assert after['reserved']==before['reserved']
        assert recovery.export_postgres(target)['recovery_format']==4 # held short alone needs v4
        with pytest.raises(ValueError,match='already_imported'):
            recovery.restore(decoded,target,'synthetic-token-longer-than-32-characters')
    for damage in ('downgrade','missing_plan','wrong_side','wrong_target','missing_hold'):
        bad=copy.deepcopy(data);bad.pop('snapshot_id')
        t=next(t for t in bad['tables']['scanner_trades'] if t['side']=='short')
        if damage=='downgrade':bad['version']=bad['recovery_format']=3
        elif damage=='missing_plan':t['settings_json']='{}'
        elif damage=='wrong_side':t['side']='long'
        elif damage=='wrong_target':t['tp2']+=1
        else:bad['hold_coverage']['order_ids']=[]
        with pytest.raises((ValueError,KeyError)):recovery.validate(bad)


def test_hold_without_trade_alone_still_requires_format4(pg):
    initialize_empty();fixture.record('ALONE')
    from datetime import datetime,timezone
    engine._pending_recovery_check('ALONE',[],datetime(2026,9,28,13,50,tzinfo=timezone.utc))
    data=recovery.export_postgres(pg)
    assert not data['tables']['scanner_trades'] and not data['tables']['scanner_fills']
    assert data['version']==4 and data['hold_coverage']['entry_reserved_notional']==100
