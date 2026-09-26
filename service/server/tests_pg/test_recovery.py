"""Recovery uses synthetic isolated data only; no Telegram or live positions."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import active_snapshot
import recovery_state as recovery
import database
import scanner_engine as engine
from test_postgres_cloud import _sqlite_portfolio


def test_recovery_encrypted_restore_and_continuation(pg,tmp_path):
    source,last=_sqlite_portfolio(tmp_path)
    data=recovery.sanitize(active_snapshot.export_data(source))
    assert any(f['fill_type']=='tp' for f in data['tables']['scanner_fills'])
    assert any(t['is_shadow'] for t in data['tables']['scanner_trades'])
    assert all('token' not in r for r in data['tables']['agents'])
    import subprocess
    identity=tmp_path/'identity'
    subprocess.run(['age-keygen','-o',str(identity)],capture_output=True,check=True)
    recipient=subprocess.run(['age-keygen','-y',str(identity)],capture_output=True,check=True).stdout.decode().strip()
    encrypted,sizes=recovery.encrypted_bytes(data,recipient)
    artifact=tmp_path/'recovery.age';artifact.write_bytes(encrypted)
    assert b'AAPL' not in encrypted
    restored=recovery.decrypt(artifact,identity)
    assert restored==data
    recovery.restore(restored,pg,'isolated-new-scanner-token-32-characters')
    exported=recovery.export_postgres(pg)
    assert exported['tables']==data['tables']
    with database.get_db_connection() as conn:
        assert conn.execute('SELECT token FROM agents').fetchone()['token']=='isolated-new-scanner-token-32-characters'
        assert conn.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
    bar={**last,'at':(datetime.fromisoformat(last['at'])+timedelta(minutes=5)).isoformat(),
         'open':107,'high':107.1,'low':106.9,'close':107}
    def proceed():
        engine.process_bar('AAPL',last)
        engine.process_bar('AAPL',bar)
        engine.process_bar('AAPL',bar)
        with database.get_db_connection() as conn:
            return [[dict(r) for r in conn.execute(q).fetchall()] for q in (
                'SELECT cash,realized_pnl,fees_paid FROM scanner_accounts ORDER BY id',
                'SELECT id,strategy,is_shadow,status,remaining_quantity,current_stop,realized_pnl,fees,outcome FROM scanner_trades ORDER BY id',
                'SELECT trade_id,fill_type,target_index,quantity,price,gross_pnl,fee FROM scanner_fills ORDER BY id')]
    with patch.object(database,'DATABASE_URL',''),patch.object(database,'_SQLITE_DB_PATH',str(source)):
        expected=proceed()
    assert proceed()==expected
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    print('RECOVERY_FIXTURE_BYTES='+json.dumps(sizes))


def test_recovery_rejects_secret_and_corruption(pg,tmp_path):
    source,_=_sqlite_portfolio(tmp_path)
    data=recovery.sanitize(active_snapshot.export_data(source))
    data.pop('snapshot_id')
    data['tables']['agents'][0]['token']='forbidden'
    with pytest.raises(ValueError,match='authentication_columns'):
        recovery.validate(data)
    del data['tables']['agents'][0]['token']
    data['tables']['agents'][0]['name']='sk-or-v1-forbiddenkey'
    with pytest.raises(ValueError,match='secret_pattern'):
        recovery.validate(data)


def test_restore_refuses_different_execution_policy(pg,tmp_path):
    source,_=_sqlite_portfolio(tmp_path)
    data=recovery.sanitize(active_snapshot.export_data(source))
    with patch.dict('os.environ',{'STOCK_SCANNER_LEVEL_MONITOR_INTERVAL':'123'}):
        with pytest.raises(ValueError,match='runtime_policy_mismatch'):
            recovery.restore(data,pg,'isolated-token-long-enough-123456789')


def test_recovery_retention(tmp_path):
    from recovery_backup import retention_paths,prune
    start=datetime(2026,1,1)
    for day in range(90):
        for relative in retention_paths(start+timedelta(days=day)):
            path=tmp_path/relative;path.parent.mkdir(exist_ok=True);path.write_bytes(b'encrypted')
    prune(tmp_path)
    assert len(list((tmp_path/'hourly').glob('*.age')))==24
    assert len(list((tmp_path/'daily').glob('*.age')))==7
    assert len(list((tmp_path/'weekly').glob('*.age')))==4
