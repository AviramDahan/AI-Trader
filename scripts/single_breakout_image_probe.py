"""Synthetic Linux image proof only; refuses non-isolated databases. No network AI."""
import os
import sys
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from urllib.parse import urlparse

action=sys.argv[1]
url=os.environ.get('DATABASE_URL','')
if urlparse(url).hostname!='breakout-pg' or urlparse(url).path not in ('/isolated_breakout','/restored_breakout'):
    raise SystemExit('isolated_breakout_database_required')
os.environ.update(STOCK_SCANNER_ENABLED='false',STOCK_SCANNER_TELEGRAM_ENABLED='false',
                  TELEGRAM_NEWS_STREAM_ENABLED='false',STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED='false')
import requests
requests.sessions.Session.request=lambda *a,**k:(_ for _ in ()).throw(AssertionError('external_requests_forbidden'))
import recovery_state as recovery
ROOT=Path('/proof')

if action=='old_refused':
    try:
        recovery.decrypt(ROOT/'synthetic.age',ROOT/'identity')
    except ValueError as exc:
        assert str(exc)=='not_a_recovery_snapshot'
    else:
        raise AssertionError('old_binary_must_reject_format5')
else:
    sys.path.insert(0,'/app/service/server/tests')
    sys.path.insert(0,'/app/service/server/tests_pg')
    import migrations,database,scanner_engine as engine
    import single_breakout_policy as policy
    import stock_scanner as scanner
    from test_single_breakout import plan
    from test_recovery_holds import initialize_empty,seed_legacy,record,state
    from test_single_target_v2 import plan as old_plan
    stamp='2026-10-06T14:00:37Z'
    bar=dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)

    def checksum():
        return hashlib.sha256(json.dumps(state(),sort_keys=True).encode()).hexdigest()

    def new(ticker,p):
        s=dict(ticker=ticker,company='Synthetic',action='BUY',entry=100,stop_loss=p['stop'],target_plan=p,
               confidence=.91,time_horizon='days',reason='synthetic',relevant_news=[])
        with patch.object(engine,'now_z',return_value=stamp):
            return engine.record_signal(s,{}, {}, {}, 'isolated-image')

    if action=='prepare':
        assert not policy.enabled()
        migrations.migrate();initialize_empty();seed_legacy()
        with patch.object(engine,'now_z',return_value=stamp):record('BASE')
        engine.process_bar('BASE',bar) # Real V1 Native and STAGED Shadow.
        new('OLDV2',old_plan());engine.process_bar('OLDV2',bar)
        assert recovery.export_postgres(url)['version']==3
    elif action=='activate':
        assert policy.enabled()
        c=dict(atr=1,price_zones=plan()['zones'],price_as_of='2026-09-25',recent_high_20d=99)
        # Keep the actual scanner decision time fixed; never submit to an AI provider.
        with patch.object(scanner,'datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,10,6,14,0,37,tzinfo=timezone.utc)
            p=scanner._candidate_target_plan(c,'BUY',100,{'min_risk_reward':2})
        new('BRK',p);engine.process_bar('BRK',{**bar,'at':'2026-10-06T14:00:00Z'})
        engine.process_bar('BRK',bar)
        new('HELD',p)
        engine._pending_recovery_check('HELD',[],datetime(2026,10,6,14,10,tzinfo=timezone.utc))
        data=recovery.export_postgres(url)
        assert data['version']==5 and len(data['hold_coverage']['order_ids'])==1
        subprocess.run(['age-keygen','-o',str(ROOT/'identity')],check=True,capture_output=True)
        recipient=subprocess.check_output(['age-keygen','-y',str(ROOT/'identity')]).decode().strip()
        encrypted,_=recovery.encrypted_bytes(data,recipient)
        (ROOT/'synthetic.age').write_bytes(encrypted)
        (ROOT/'state.sha256').write_text(checksum())
    elif action in ('rollback','restart'):
        assert not policy.enabled()
        before=checksum();engine.initialize_runtime();engine.process_bar('BRK',bar)
        assert checksum()==before==(ROOT/'state.sha256').read_text()
        assert record('HELD')['status']=='DUPLICATE_BLOCKED'
        assert checksum()==before
        data=recovery.export_postgres(url)
        assert data['version']==5 and len(data['hold_coverage']['order_ids'])==1
    elif action=='restore':
        assert not policy.enabled()
        migrations.migrate()
        data=recovery.decrypt(ROOT/'synthetic.age',ROOT/'identity')
        recovery.restore(data,url,'synthetic-token-more-than-32-characters')
        engine.initialize_runtime();engine.process_bar('BRK',bar)
        assert checksum()==(ROOT/'state.sha256').read_text()
        with database.get_db_connection() as c:
            assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
    elif action=='exit':
        before=state()
        engine.process_bar('BRK',{**bar,'at':'2026-10-06T14:10:00Z','open':104.5,'high':105,'low':104,'close':104.5})
        after=state()
        assert after['holds']==before['holds'] and after['reserved']==before['reserved']
        assert len(after['fills'])==len(before['fills'])+1
        engine.initialize_runtime();engine.process_bar('BRK',bar)
        assert state()==after
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    elif action=='forward':
        assert policy.enabled()
        before=checksum();engine.initialize_runtime();engine.process_bar('BRK',bar)
        assert checksum()==before
        assert recovery.export_postgres(url)['version']==5
    else:
        raise ValueError('unsupported_test_phase')
print(json.dumps(dict(phase=action,status='PASS',build_sha=os.environ.get('BUILD_SHA'))))
