"""Synthetic-only full application image transition test. No external services.

All application imports resolve inside the selected immutable image. Only market
transport and the clock are mocked. Nothing mounts over application modules.
"""
import json, os, sys, subprocess
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import requests
import database, scanner_engine as e, cloud_runtime as cloud, migrations

assert os.environ['DATABASE_URL'].startswith('postgresql://isolated:')
assert os.environ.get('AI_TRADER_CLOUD') == 'true'
ROOT = Path('/proof')
AT = '2026-09-28T13:30:00Z'
BAR = dict(at='2026-09-28T13:35:00Z', open=100, high=101, low=99.5, close=100)


def state():
    with database.get_db_connection() as c:
        return {k:[dict(r) for r in c.execute(q)] for k,q in {
            'account':'SELECT cash,fees_paid,realized_pnl FROM scanner_accounts ORDER BY id',
            'legacy_wallet':'SELECT id,cash FROM agents ORDER BY id',
            'legacy_positions':'SELECT id,quantity,entry_price FROM positions ORDER BY id',
            'trades':'SELECT id,remaining_quantity,fees,realized_pnl,current_stop FROM scanner_trades ORDER BY id',
            'fills':'SELECT id,trade_id,quantity,price,fee FROM scanner_fills ORDER BY id',
            'reservation':"SELECT COALESCE(SUM(limit_price*quantity),0) amount FROM scanner_orders WHERE status IN ('pending','recovery_uncertain') AND purpose='entry'",
            'holds':"SELECT id,status,signal_id,limit_price,quantity,valid_until FROM scanner_orders WHERE status='recovery_uncertain' ORDER BY id"}.items()}


def save(name):
    ROOT.joinpath(name+'.json').write_text(json.dumps(state()))


def unchanged(name):
    assert state() == json.loads(ROOT.joinpath(name+'.json').read_text()), name


def v2_plan():
    import stock_scanner
    zs=[dict(low=low,high=high,touches=1,pivots=[dict(price=low,date='2026-09-21',kind='swing_high',confirmed_at='2026-09-23T20:05:00Z')])
        for low,high in ((98,98.4),(104.65,105))]
    c=dict(atr=1,price_zones=zs,price_as_of='2026-09-25')
    # Only the decision clock, not the plan builder/creation gate, is mocked.
    with patch.object(stock_scanner,'datetime',wraps=datetime) as clock:
        clock.now.return_value=datetime.fromisoformat(AT.replace('Z','+00:00'))
        return stock_scanner._candidate_target_plan(c,'BUY',100,{'min_risk_reward':2})


def record(ticker, plan=None):
    signal=dict(ticker=ticker,company='Synthetic Company',action='BUY',entry=100,
        stop_loss=plan['stop'] if plan else 97,confidence=.91,time_horizon='weeks',reason='synthetic',relevant_news=[])
    if plan: signal['target_plan']=plan
    with patch.object(e,'now_z',return_value=AT):
        return e.record_signal(signal,{}, {}, {}, 'synthetic-image-test')


def leases():
    for role in cloud.ROLE_KEYS:
        lease=cloud.RoleLease(role)
        try:
            try: cloud.RoleLease(role)
            except RuntimeError as exc: assert 'role_already_owned' in str(exc)
            else: raise AssertionError('duplicate_role_acquired')
        finally: lease.close()


def run(mode):
    if mode=='seed':
        migrations.migrate()
        cloud.assert_schema()
        with database.get_db_connection() as c:
            assert c.execute('SELECT max(version) v FROM schema_migrations').fetchone()['v']==5
            c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
        e.initialize_runtime();record('V1TEST');e.process_bar('V1TEST',BAR)
        sys.path.insert(0,'/app/service/server/tests_pg')
        from test_recovery_holds import seed_legacy
        seed_legacy()
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
        save('seed')
    elif mode=='prepare':
        import single_target_activation as gate
        assert cloud.SCHEMA_VERSION==5 and cloud.SUPPORTED_SCHEMAS==(5,6)
        assert not gate.CREATION_CAPABLE
        os.environ['STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED']='true'
        assert not gate.enabled()
        os.environ['STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED']='false'
        from single_target_release import assert_bridge
        assert_bridge(5)
        # The actual role CLI must leave schema 5 unchanged on normal deploy.
        sys.argv=['cloud_runtime.py','migrate'];cloud.main()
        cloud.assert_schema();e.initialize_runtime();unchanged('seed');leases()
        # Exercise schema-5 V1 order insertion where plan_json does not exist.
        record('BRIDGEV1');e.process_bar('BRIDGEV1',BAR)
        save('prepared')
    elif mode=='baseline_return':
        cloud.assert_schema();e.initialize_runtime();unchanged('prepared')
    elif mode=='immediate_failure':
        import single_target_activation as gate
        from single_target_release import assert_bridge
        assert_bridge(6)
        cloud.assert_schema();assert cloud.SCHEMA_VERSION==5 and not gate.CREATION_CAPABLE
        e.initialize_runtime();unchanged('prepared');leases()
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
        with database.get_db_connection() as c:
            assert c.execute('SELECT max(version) v FROM schema_migrations').fetchone()['v']==6
        # Replaying completed bars across failed migration/restart changes nothing.
        e.process_bar('V1TEST',BAR);unchanged('prepared')
    elif mode=='activate':
        import single_target_activation as gate
        cloud.assert_schema();assert cloud.SCHEMA_VERSION==6 and gate.CREATION_CAPABLE
        assert not gate.enabled()
        os.environ['STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED']='true'
        p=v2_plan();assert p['policy_version']=='single_target_v2'
        record('V2POS',p);e.process_bar('V2POS',BAR)
        record('V2HOLD',p)
        now=datetime(2026,9,29,14,tzinfo=timezone.utc)
        with patch.object(e,'datetime',wraps=datetime) as clock, patch.object(e,'_bar_dicts',return_value=[]):
            clock.now.side_effect=lambda tz=None:now.astimezone(tz)
            e.monitor_prices()
        assert len(state()['holds'])==1 and state()['holds'][0]['valid_until']<now.isoformat()
        record('V2PEND',p)
        ROOT.joinpath('plan.json').write_text(json.dumps(p))
        save('active')
    elif mode=='disable':
        import single_target_activation as gate
        assert not gate.enabled();unchanged('active')
        p=json.loads(ROOT.joinpath('plan.json').read_text())
        try:record('DISABLED',p)
        except ValueError as exc: assert str(exc)=='new_single_target_v2_disabled'
        else:raise AssertionError('disabled_created_signal')
        unchanged('active')
        # Pending V2 fills even with the creation flag off; not converted to V1.
        e.process_bar('V2PEND',BAR)
        with database.get_db_connection() as c:
            assert c.execute("SELECT count(*) n FROM scanner_trades WHERE ticker='V2PEND'").fetchone()['n']==1
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
        save('disabled')
    elif mode in ('rollback','restart'):
        import single_target_activation as gate
        from single_target_release import assert_bridge
        assert_bridge(6)
        assert not gate.CREATION_CAPABLE
        cloud.assert_schema();e.initialize_runtime();unchanged('disabled');leases()
        assert record('V2HOLD')['status']=='DUPLICATE_BLOCKED'
        e.process_bar('V2POS',BAR);e.process_bar('V2PEND',BAR);unchanged('disabled')
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
        if mode=='rollback':
            import recovery_state as r
            data=r.export_postgres(os.environ['DATABASE_URL'])
            assert data['version']==data['recovery_format']==3
            assert len(data['hold_coverage']['order_ids'])==1
            assert any(o['status']=='imported' for o in data['tables']['scanner_orders'])
            assert any(t['is_shadow'] for t in data['tables']['scanner_trades'])
            subprocess.run(['age-keygen','-o',str(ROOT/'identity')],capture_output=True,check=True)
            recipient=subprocess.check_output(['age-keygen','-y',str(ROOT/'identity')]).decode().strip()
            encrypted,_=r.encrypted_bytes(data,recipient);(ROOT/'synthetic.age').write_bytes(encrypted)
            assert r.decrypt(ROOT/'synthetic.age',ROOT/'identity')==data
    elif mode=='restore':
        import recovery_state as r
        migrations.migrate(target_version=6);cloud.assert_schema()
        data=r.decrypt(ROOT/'synthetic.age',ROOT/'identity')
        r.restore(data,os.environ['DATABASE_URL'],'synthetic-token-longer-than-32-characters')
        e.initialize_runtime();unchanged('disabled')
        with database.get_db_connection() as c:
            assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        assert record('V2HOLD')['status']=='DUPLICATE_BLOCKED'
        unchanged('disabled')
        try:r.restore(data,os.environ['DATABASE_URL'],'synthetic-token-longer-than-32-characters')
        except ValueError as exc:assert 'already_imported' in str(exc)
        else:raise AssertionError('repeat_restore_accepted')
        unchanged('disabled')
    elif mode=='exit':
        before=state()
        for ticker in ('V1TEST','BRIDGEV1','TEST','V2POS','V2PEND'):
            bar=dict(at='2026-09-28T13:40:00Z',open=106,high=107,low=105,close=106)
            e.process_bar(ticker,bar)
            after=state();e.process_bar(ticker,bar);assert state()==after
        assert state()['holds']==before['holds'] and state()['reservation']==before['reservation']
        assert len(state()['fills'])>len(before['fills'])
        with database.get_db_connection() as c:
            rows=c.execute("SELECT remaining_quantity FROM scanner_trades WHERE ticker IN ('V2POS','V2PEND')").fetchall()
            assert len(rows)==2 and all(r['remaining_quantity']==0 for r in rows)
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
        save('exited')
    elif mode=='forward':
        cloud.assert_schema();e.initialize_runtime();unchanged('exited')
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
    elif mode=='old_refused':
        try:cloud.assert_schema()
        except RuntimeError:pass
        else:raise AssertionError('old_binary_accepted_schema6')
    else:raise ValueError(mode)
    summary={'phase':mode,'result':'PASS','build_sha':os.environ.get('BUILD_SHA')}
    with (ROOT/'results.jsonl').open('a') as out:out.write(json.dumps(summary)+'\n')
    print(json.dumps(summary))


with patch.object(requests.sessions.Session,'request',side_effect=AssertionError('external HTTP forbidden')):
    run(sys.argv[1])
