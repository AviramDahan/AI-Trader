"""Deterministic research evidence, no external data, AI or messaging."""
import copy
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import scanner_engine
import signal_research as research

NOW = datetime(2026, 10, 7, 16, tzinfo=timezone.utc)


def synthetic_trade(**changes):
    return dict(id=1, signal_id=1, ticker='TEST', side='long', strategy='staged', is_shadow=0,
        status='open', entry_price=100, original_quantity=10, remaining_quantity=5, original_r=5,
        original_stop=95, current_stop=100, settings_json='{}', realized_pnl=50, fees=2,
        opened_at='2026-10-07T14:00:00Z', closed_at=None, last_price=104,
        last_bar_at='2026-10-07T14:10:00Z', legacy_position_id=None, **changes)


def synthetic_fills():
    return [dict(fill_type='entry', price=100, quantity=10, fee=1, gross_pnl=0, bar_at='2026-10-07T14:00:00Z'),
            dict(fill_type='tp', price=110, quantity=5, fee=1, gross_pnl=50, bar_at='2026-10-07T14:05:00Z')]


def seed_journal(conn):
    """Three repeated checks, two exact price geometries, zero invented fills."""
    for scan, stamp, price in [('s1','2026-10-07T05:00:00Z',100), ('s2','2026-10-07T14:00:00Z',100), ('s3','2026-10-07T14:05:00Z',101)]:
        data = dict(phase='pre_ai', outcome='NOT_EVALUATED', action='BUY', policy_version='single_target_v2',
                    quote=dict(price=price,as_of=stamp), observed_at=stamp,
                    source_inputs=dict(atr=1,data_as_of='2026-10-06',zones=[]))
        for stage, status, reason, metrics in [('technical','candidate',None,dict(technical_direction='BUY',api_key='SECRET')),
                ('final','rejected','pre_no_fresh_quote',{}), ('target_check','observed','pre_no_fresh_quote',data)]:
            conn.execute('''INSERT INTO scanner_candidates(scan_id,ticker,company,stage,status,reason,metrics_json,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',(scan,'TEST','Synthetic',stage,status,reason,json.dumps(metrics),stamp))
        conn.execute('''INSERT INTO scanner_final_ai_telemetry(review_id,scan_id,ticker,rank,provider,model,latency,
            retry_count,result,reject_reason,ai_call_saved,attempts_json,updated_at)
            VALUES(?,?,?,1,'test','test',0,0,'early_skip','pre_no_fresh_quote',1,'[]',?)''', (scan,scan,'TEST',stamp))
    conn.commit()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database,'DATABASE_URL','')
    monkeypatch.setattr(database,'_SQLITE_DB_PATH',str(tmp_path/'test.db'))
    database.init_database()
    with database.get_db_connection() as c:
        c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
        seed_journal(c)


def test_partial_fees_weighting_and_timestamp_are_not_full_position_return():
    t, f = synthetic_trade(), synthetic_fills()
    before = copy.deepcopy((t,f))
    o = research.outcome(t,f,NOW)
    assert o['realized_net_pct']==pytest.approx(4.8) and o['realized_net_r']==pytest.approx(.96)
    assert o['open_gross_pct']==pytest.approx(2) and o['open_gross_r']==pytest.approx(.4)
    assert o['marked_net_pct']==pytest.approx(6.8) and o['remaining_pct']==50
    assert o['closed_net_pct'] is None and o['mfe_pct'] is None
    assert o['mark_at']=='2026-10-07T14:15:00+00:00'
    assert (t,f)==before


def test_closed_zero_is_valid_but_missing_and_legacy_are_not_zero():
    t = synthetic_trade();t.update(status='closed',remaining_quantity=0,realized_pnl=2,
        closed_at='2026-10-07T15:00:00Z')
    f=synthetic_fills();f[1].update(quantity=10,gross_pnl=2,price=100.2)
    o=research.outcome(t,f)
    assert o['closed_net_pct']==0 and o['closed_net_r']==0 and o['holding_hours']==1
    for damage in ('legacy','missing_entry','quantity','fees'):
        damaged=copy.deepcopy(t);ff=copy.deepcopy(f)
        if damage=='legacy':damaged['legacy_position_id']=99
        elif damage=='missing_entry':ff=ff[1:]
        elif damage=='quantity':ff[1]['quantity']=9
        else:damaged['fees']=3
        assert research.outcome(damaged,ff)['closed_net_pct'] is None


def test_short_open_mark_has_correct_sign_and_never_uses_entry_as_quote():
    t=synthetic_trade();t.update(side='short',last_price=96)
    assert research.outcome(t,synthetic_fills(),NOW)['open_gross_pct']==2
    for mark in (None,'2026-10-07T13:55:00Z'):
        t['last_bar_at']=mark
        assert research.outcome(t,synthetic_fills(),NOW)['open_gross_pct'] is None
    t['last_bar_at']='2026-10-07T15:59:00Z'
    assert research.outcome(t,synthetic_fills(),NOW)['open_gross_pct'] is None


def test_invalid_money_or_quantity_never_yields_nan_or_infinite_metrics():
    for field in ('price','quantity','fee','gross_pnl'):
        fills=synthetic_fills();fills[0][field]=float('nan')
        r=research.outcome(synthetic_trade(),fills,NOW)
        assert r['realized_net_pct'] is None
        json.dumps(r,allow_nan=False)


def test_concurrent_refreshes_are_coalesced_and_failure_closes_connection(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import Mock
    research._CACHE.clear()
    clock=[100.]
    monkeypatch.setattr(research,'monotonic',lambda:clock[0])
    conn=Mock()
    monkeypatch.setattr(research,'get_db_connection',lambda:conn)
    monkeypatch.setattr(research,'using_postgres',lambda:True)
    read=Mock(return_value={'generated_at':'synthetic'})
    monkeypatch.setattr(research,'report',read)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:research.payload(48), range(4)))
        assert all(r==results[0] for r in results)
        read.assert_called_once_with(conn,48)
        conn.execute.assert_any_call('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        assert conn.close.call_count==1
        clock[0]+=61
        read.side_effect=RuntimeError('synthetic timeout')
        with pytest.raises(RuntimeError):research.payload(48)
        assert conn.close.call_count==2
    finally:
        research._CACHE.clear()


def test_journal_repeats_sessions_missing_stages_and_allowlist(db):
    with database.get_db_connection() as c:
        c.execute('PRAGMA query_only=ON')
        r=research.report(c,48,NOW)
        assert r['counts']['candidate_observations']==3
        assert r['counts']['unique_tickers']==1
        assert r['counts']['exact_reference_configurations']==2
        assert r['counts']['target_checked']==0 and r['counts']['ai_attempt_records']==0
        assert r['quote_context']=={'outside_regular_session':1,'regular_session':2}
        assert r['execution']['fill_rate'] is None and not r['outcomes']
        assert 'SECRET' not in json.dumps(r)
        assert all(not x['signals'] and not x['orders'] for x in r['records'])
        for table in ('scanner_signals','scanner_orders','scanner_fills','scanner_telegram_outbox'):
            assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0


def test_retained_target_requirements_public_readback_never_exports_private_source(db):
    with database.get_db_connection() as c:
        data=dict(phase='pre_ai',outcome='REJECT',rejection_reason='entry_not_above_completed_high',
            minimum_rr=2,observed_at='2026-10-07T14:00:00Z',quote=dict(price=100),
            source_inputs=dict(atr=1,data_as_of='2026-10-06',zones=[],completed_high=101.5,
                completed_high_sessions=20,private_prompt='DO-NOT-EXPOSE'))
        c.execute("UPDATE scanner_candidates SET metrics_json=? WHERE stage='target_check'",(json.dumps(data),))
        c.commit()
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY' if database.using_postgres() else 'PRAGMA query_only=ON')
        r=research.report(c,48,NOW)
        check=r['records'][0]['target_checks'][0]
        assert check['minimum_rr']==2
        assert check['source_inputs']['completed_high']==101.5
        assert check['source_inputs']['completed_high_sessions']==20
        assert 'DO-NOT-EXPOSE' not in json.dumps(r) and 'private_prompt' not in json.dumps(r)
        for table in ('scanner_signals','scanner_orders','scanner_fills','scanner_telegram_outbox'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0


def test_clipping_is_explicit_and_bad_json_never_fabricates_evidence(db,monkeypatch):
    monkeypatch.setattr(research,'ROW_LIMIT',2)
    with database.get_db_connection() as c:
        c.execute("UPDATE scanner_candidates SET metrics_json='broken' WHERE stage='target_check'")
        c.commit()
        r=research.report(c,48,NOW)
        assert 'target_check' in r['clipped'] and 'technical_details' in r['clipped'] and 'reviews' in r['clipped']
        assert r['counts']['candidate_observations']==3
        assert r['counts']['exact_reference_configurations']==0


def test_api_window_validation_and_reads_only(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes_scanner import register_scanner_routes
    app=FastAPI();register_scanner_routes(app)
    client=TestClient(app)
    with patch.object(research,'payload',return_value={'counts':{'entries':0}}) as p:
        assert client.get('/api/scanner/research?hours=48').json()['counts']['entries']==0
        p.assert_called_once_with(48)
        for hours in (0,25,100000):assert client.get(f'/api/scanner/research?hours={hours}').status_code==422


def test_real_entry_exit_readback_restart_and_no_report_mutations(db):
    with patch('telegram_status.refresh_telegram_status_cards'), patch.object(scanner_engine,'now_z',return_value='2026-10-07T13:30:00Z'):
        scanner_engine.initialize_runtime()
        scanner_engine.record_signal(dict(ticker='AAPL',company='Synthetic',action='BUY',entry=100,
            stop_loss=97,confidence=.9,time_horizon='days',reason='synthetic',relevant_news=[]),{},{},{},'s-entry')
    bar=dict(at='2026-10-07T13:35:00Z',open=100,high=101,low=99,close=100)
    scanner_engine.process_bar('AAPL',bar)
    scanner_engine.process_bar('AAPL',dict(bar,at='2026-10-07T13:40:00Z',open=96,high=96,low=95,close=95.5))
    with database.get_db_connection() as c:
        before={table:[dict(r) for r in c.execute('SELECT * FROM '+table)] for table in
                ('scanner_accounts','scanner_orders','scanner_trades','scanner_fills','scanner_telegram_outbox')}
        r=research.report(c,48,NOW)
        assert len(r['outcomes'])==2 and {o['cohort'] for o in r['outcomes']}=={'Native','Shadow'}
        assert all(o['closed_net_pct']<0 for o in r['outcomes'])
        assert len(r['outcome_groups'])==2
        again=research.report(c,48,NOW)
        assert r==again
        after={table:[dict(row) for row in c.execute('SELECT * FROM '+table)] for table in before}
        assert before==after


def test_exact_entry_rejection_is_linked_and_allowlisted_without_plan_leak(db):
    with patch('telegram_status.refresh_telegram_status_cards'), patch.object(scanner_engine,'now_z',return_value='2026-10-07T14:00:00Z'):
        scanner_engine.initialize_runtime()
        scanner_engine.record_signal(dict(ticker='TEST',company='Synthetic',action='BUY',entry=100,
            stop_loss=97,confidence=.9,time_horizon='days',reason='synthetic',relevant_news=[]),{},{},{},'s2')
    with database.get_db_connection() as c:
        c.execute("UPDATE scanner_signals SET status='ENTRY_POLICY_REJECTED'")
        c.execute("UPDATE scanner_orders SET status='invalid',plan_json=?", (json.dumps(dict(
            entry_rejection_reason='fill_rr_below_2',private='DO-NOT-EXPOSE',execution_settings=dict(secret='DO-NOT-EXPOSE'))),))
        c.commit()
        if database.using_postgres():
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        else:
            c.execute('PRAGMA query_only=ON')
        result=research.report(c,48,NOW)
        case=next(r for r in result['records'] if r['scan_id']=='s2')
        assert case['signals'][0]['entry_rejection_reason']=='fill_rr_below_2'
        assert case['orders'][0]['entry_rejection_reason']=='fill_rr_below_2'
        assert case['orders'][0]['signal_id']==case['signals'][0]['id']
        assert 'DO-NOT-EXPOSE' not in json.dumps(result) and 'plan_json' not in json.dumps(result)


def test_price_wait_readback_is_derived_same_chain_and_read_only(db):
    from test_entry_price_retry import narrow_plan,FLAGS
    import entry_price_retry
    stamp='2026-10-07T14:00:00Z'
    p=narrow_plan(stamp)
    with patch('telegram_status.refresh_telegram_status_cards'),patch.dict('os.environ',FLAGS),patch.object(scanner_engine,'now_z',return_value=stamp):
        scanner_engine.initialize_runtime()
        scanner_engine.record_signal(dict(ticker='TEST',company='Synthetic',action='BUY',entry=100,
            stop_loss=p['stop'],target_plan=p,confidence=.9,time_horizon='days',reason='synthetic',relevant_news=[]),{},{},{},'s2')
    with patch.object(scanner_engine,'now_z',return_value='2026-10-07T14:10:00Z'):
        scanner_engine.process_bar('TEST',dict(at='2026-10-07T14:05:00Z',open=99.8,high=100.2,low=99.7,close=99.85))
    with database.get_db_connection() as c:
        o=c.execute("SELECT * FROM scanner_orders WHERE purpose='entry'").fetchone()
        contract=json.loads(o['plan_json']);contract['execution_settings']['private_prompt']='DO-NOT-EXPOSE'
        c.execute('UPDATE scanner_orders SET plan_json=? WHERE id=?',(json.dumps(contract),o['id']));c.commit()
        before=[dict(r) for r in c.execute('SELECT * FROM scanner_orders')]
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY' if database.using_postgres() else 'PRAGMA query_only=ON')
        result=research.report(c,48,NOW)
        case=next(r for r in result['records'] if r['scan_id']=='s2')
        wait=case['orders'][0]['entry_price_wait']
        assert wait['version']==entry_price_retry.VERSION and wait['reason']=='fill_stop_distance_invalid'
        assert case['signals'][0]['entry_price_wait']==wait
        assert case['signals'][0]['status']=='PENDING_ENTRY' and not result['outcomes']
        assert set(wait)=={'version','reason','price','bar_at','observed_at'}
        assert 'DO-NOT-EXPOSE' not in json.dumps(result) and 'plan_json' not in json.dumps(result)
        assert before==[dict(r) for r in c.execute('SELECT * FROM scanner_orders')]
