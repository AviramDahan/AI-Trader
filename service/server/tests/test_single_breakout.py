"""Synthetic decision-time contracts and real isolated application execution."""
import copy
import json
import unittest
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import single_breakout_policy as policy
import entry_window
import scanner_engine as engine
import test_scanner_engine as fixture
from test_single_target_v2 import zone, plan as v2_plan
from test_signal_inputs import db, clock
from test_signal_admission_chain import prepare, rows


FLAGS = dict(STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED='true', STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED='true',
             STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED='true', STOCK_SCANNER_EXIT_STRATEGY='single')


def plan(zones=None, **changes):
    inputs = dict(entry=100, atr=1, zones=zones if zones is not None else [zone(98,98.4)],
                  data_as_of='2026-09-25', decided_at='2026-10-06T14:00:00Z', completed_high=99)
    return policy.build(**(inputs | changes))


def test_single_objective_and_immutable_fill_checks():
    p=plan();saved=copy.deepcopy(p)
    assert p['targets']==[104.5] and p['fractions']==[1] and p['rr']==[2]
    assert policy.validate(p)==p and policy.validate_fill(p,100)==2
    for price in (100.01,99,98.3,95,106):
        with pytest.raises(ValueError):policy.validate_fill(p,price)
    assert p==saved
    with pytest.raises(ValueError):policy.validate(p,action='SELL')
    with pytest.raises(ValueError):policy.validate(p,action='SHORT')


@pytest.mark.parametrize('zones,reason', [
    ([zone(98,98.4),zone(102,103)],'2r'),
    ([zone(98,98.4),zone(110,111)],'requires_no_forward'),
    ([zone(99.9,100.1)],'inside'),([], 'anchor'),([zone(94,95)],'distant')])
def test_no_protected_failure_can_use_fallback(zones,reason):
    with pytest.raises(ValueError,match=reason):plan(zones)


def test_point_in_time_high_and_confirmation_required():
    for high in (None,0,float('nan'),100,101):
        with pytest.raises(ValueError):plan(completed_high=high)
    with pytest.raises(ValueError,match='uncompleted'):plan(data_as_of='2026-10-06')
    zs=[zone(98,98.4)];zs[0]['pivots'][0]['confirmed_at']='2026-10-09T20:05:00Z'
    with pytest.raises(ValueError,match='unconfirmed'):plan(zs)
    p=plan();p['completed_high_sessions']=126
    with pytest.raises(ValueError,match='mismatch'):policy.validate(p)


def test_two_r_cent_ceiling_and_saved_price_boundary():
    from decimal import Decimal
    for entry in (100,100.001,100.007,100.999):
        p=plan(entry=entry)
        assert Decimal(str(p['active_target']))-Decimal(str(entry)) >= 2*(Decimal(str(entry))-Decimal(str(p['stop'])))
        assert policy.validate_fill(p,entry)>=2
        with pytest.raises(ValueError,match='rr'):policy.validate_fill(p,entry+.02)


def test_explicit_window_midbar_exact_boundary_and_expiry():
    for created,start in [('2026-10-06T14:00:37Z','2026-10-06T14:05:00+00:00'),
                          ('2026-10-06T14:00:00Z','2026-10-06T14:00:00+00:00')]:
        w=entry_window.build(created,'2026-10-07T14:00:37Z')
        order=dict(created_at=created,valid_until='2026-10-07T14:00:37Z',plan_json=json.dumps({'entry_execution':w}))
        assert entry_window.eligible_from(order).isoformat()==start
        w['entry_eligible_from']='2026-10-06T13:55:00Z';order['plan_json']=json.dumps({'entry_execution':w})
        with pytest.raises(ValueError,match='mismatch'):entry_window.eligible_from(order)
    with pytest.raises(ValueError,match='empty'):entry_window.build('2026-10-06T14:00:37Z','2026-10-06T14:02:00Z')


@pytest.mark.parametrize('blocked',['off','window_off','hold','confidence','quote','session','resistance','high','budget'])
def test_actual_scanner_gate_failures_preserved(db,clock,monkeypatch,blocked):
    import stock_scanner as scanner
    candidate,review,_=prepare(monkeypatch,clock)
    candidate['price_zones']=[zone(98,98.4)];candidate['recent_high_20d']=99
    for key,value in FLAGS.items():monkeypatch.setenv(key,value)
    if blocked=='off':monkeypatch.delenv('STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED')
    if blocked=='window_off':monkeypatch.delenv('STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED')
    if blocked=='hold':review.return_value['action']='HOLD'
    if blocked=='confidence':review.return_value['confidence']=.79
    if blocked=='quote':monkeypatch.setattr(scanner,'current_intraday_quote',lambda *a:None)
    if blocked=='session':monkeypatch.setattr(scanner,'regular_session_open',lambda:False)
    if blocked=='resistance':candidate['price_zones'].append(zone(102,103))
    if blocked=='high':candidate['recent_high_20d']=100
    if blocked=='budget':monkeypatch.setattr('ai_budget.check',lambda:(_ for _ in ()).throw(ValueError('synthetic_budget_block')))
    scanner.run_scan()
    assert not rows('SELECT id FROM scanner_orders') and not rows('SELECT id FROM scanner_trades')


def test_actual_scanner_new_policy_reaches_pending_fill_exit(db,clock,monkeypatch):
    import stock_scanner as scanner
    candidate,review,_=prepare(monkeypatch,clock)
    candidate['price_zones']=[zone(98,98.4)];candidate['recent_high_20d']=99
    clock.instant=datetime(2026,10,6,14,0,37,tzinfo=timezone.utc)
    for key,value in FLAGS.items():monkeypatch.setenv(key,value)
    result=scanner.run_scan()
    assert result['signals_published']==review.call_count==1
    contract=json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    assert contract['target_plan']['policy_version']==policy.VERSION
    assert contract['entry_execution']['entry_eligible_from']=='2026-10-06T14:05:00+00:00'
    assert not rows('SELECT id FROM scanner_fills')
    monkeypatch.setenv('STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED','false')
    monkeypatch.setenv('STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED','false')
    clock.instant=datetime(2026,10,6,14,10,tzinfo=timezone.utc)
    engine.process_bar('TEST',dict(at='2026-10-06T14:00:00Z',open=100,high=101,low=99.8,close=100))
    assert not rows('SELECT id FROM scanner_fills')
    bar=dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)
    engine.process_bar('TEST',bar)
    assert len(rows('SELECT id FROM scanner_trades'))==1
    clock.instant=datetime(2026,10,6,14,15,tzinfo=timezone.utc)
    exit_bar=dict(at='2026-10-06T14:10:00Z',open=104.5,high=105,low=104,close=104.5)
    engine.process_bar('TEST',exit_bar);engine.initialize_runtime();engine.process_bar('TEST',exit_bar)
    assert len(rows('SELECT id FROM scanner_fills'))==2
    assert rows('SELECT remaining_quantity,status,is_shadow FROM scanner_trades')==[dict(remaining_quantity=0,status='closed',is_shadow=0)]
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


class TestBreakoutLifecycle(unittest.TestCase):
    setUp=fixture.ScannerEngineTests.setUp
    tearDown=fixture.ScannerEngineTests.tearDown
    signal=fixture.ScannerEngineTests.signal
    candidate=fixture.ScannerEngineTests.candidate
    decision=fixture.ScannerEngineTests.decision
    fetchall=fixture.ScannerEngineTests.fetchall

    def record(self,ticker='AAPL',p=None,validity=24,stamp='2026-10-06T14:00:37Z'):
        p=p or plan()
        s=dict(self.signal(ticker=ticker),signal_id=None,target_plan=p,stop_loss=p['stop'])
        cfg=engine.lifecycle_settings() | {'signal_validity_hours':validity}
        with patch.dict('os.environ',FLAGS),patch.object(engine,'now_z',return_value=stamp),patch.object(engine,'lifecycle_settings',return_value=cfg):
            return engine.record_signal(s,self.candidate(),self.decision(),{},'synthetic-breakout')

    def monitor(self,bars):
        observed=datetime(2026,10,6,14,10,tzinfo=timezone.utc)
        with patch.object(engine,'datetime',wraps=datetime) as clock,patch.object(engine,'now_z',return_value=observed.isoformat()),patch.object(engine,'_bar_dicts',return_value=bars):
            clock.now.side_effect=lambda tz=None:observed.astimezone(tz)
            return engine.monitor_prices()

    def test_midbar_touch_does_not_hold_fullbar_entry_restart(self):
        self.record()
        bars=[dict(at='2026-10-06T14:00:00Z',open=100,high=101,low=99.8,close=100),
              dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)]
        with patch.dict('os.environ',STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED='false',STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED='false'):
            assert not self.monitor(bars)['errors']
            assert self.fetchall('SELECT status FROM scanner_orders')==[{'status':'filled'}]
            assert len(self.fetchall('SELECT id FROM scanner_fills'))==1
            engine.initialize_runtime();self.monitor(bars)
            assert len(self.fetchall('SELECT id FROM scanner_fills'))==1
        payload=engine.dashboard_payload()
        assert payload['signals'][0]['policy_version']==policy.VERSION
        assert payload['trades'][0]['operational_tp1_pct']==1
        assert payload['lifecycle_verification']['accounting_ok']

    def test_missing_eligible_bar_still_holds_without_debit(self):
        self.record()
        before=self.fetchall('SELECT cash,fees_paid FROM scanner_accounts')
        self.monitor([dict(at='2026-10-06T14:00:00Z',open=100,high=101,low=99.8,close=100)])
        assert self.fetchall('SELECT status FROM scanner_orders')==[{'status':'recovery_uncertain'}]
        assert not self.fetchall('SELECT id FROM scanner_fills')
        assert self.fetchall('SELECT cash,fees_paid FROM scanner_accounts')==before
        engine.initialize_runtime();self.monitor([])
        assert self.fetchall('SELECT status FROM scanner_orders')==[{'status':'recovery_uncertain'}]

    def test_intrabar_expiry_never_gets_optimistic_fill(self):
        self.record(validity=.12)
        self.monitor([dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)])
        assert self.fetchall('SELECT status FROM scanner_orders')==[{'status':'recovery_uncertain'}]
        assert not self.fetchall('SELECT id FROM scanner_fills')

    def test_v2_with_new_window_keeps_its_levels(self):
        self.record(p=v2_plan())
        self.monitor([dict(at='2026-10-06T14:00:00Z',open=100,high=101,low=99.8,close=100),
                      dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)])
        t=self.fetchall('SELECT tp1,tp2,tp3 FROM scanner_trades')[0]
        assert t==dict(tp1=104.5,tp2=None,tp3=None)

    def test_same_entry_bar_never_assumes_profit_and_stop_gap_not_guaranteed(self):
        self.record()
        engine.process_bar('AAPL',dict(at='2026-10-06T14:05:00Z',open=100,high=106,low=99.8,close=105))
        assert self.fetchall('SELECT status FROM scanner_trades')==[{'status':'open'}]
        engine.process_bar('AAPL',dict(at='2026-10-06T14:10:00Z',open=95,high=96,low=94,close=95))
        exits=self.fetchall("SELECT price,fill_type FROM scanner_fills WHERE fill_type='stop'")
        assert len(exits)==1 and exits[0]['price']<95
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_adverse_stop_wins_over_unknown_same_bar_target(self):
        self.record()
        bar=dict(at='2026-10-06T14:05:00Z',open=100,high=106,low=96,close=105)
        engine.process_bar('AAPL',bar);engine.initialize_runtime();engine.process_bar('AAPL',bar)
        assert len(self.fetchall('SELECT id FROM scanner_fills'))==2
        assert self.fetchall("SELECT fill_type FROM scanner_fills ORDER BY id")==[{'fill_type':'entry'},{'fill_type':'stop'}]

    def test_incomplete_bar_and_invalid_window_cannot_execute(self):
        self.record()
        bar=dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)
        with patch.object(engine,'now_z',return_value='2026-10-06T14:07:00Z'):
            engine.process_bar('AAPL',bar)
        assert not self.fetchall('SELECT id FROM scanner_fills')
        import database
        with database.get_db_connection() as c:
            contract=json.loads(c.execute('SELECT plan_json FROM scanner_orders').fetchone()['plan_json'])
            contract['entry_execution']['version']='future_unknown'
            c.execute('UPDATE scanner_orders SET plan_json=?',(json.dumps(contract),))
        self.monitor([bar])
        assert self.fetchall('SELECT status FROM scanner_orders')==[{'status':'recovery_uncertain'}]
        assert not self.fetchall('SELECT id FROM scanner_fills')

    def test_new_window_skips_weekend_holiday_and_overnight_without_false_gap(self):
        self.market_clock.stop()
        # Creation just before the close; eligibility starts at the close. The
        # next complete session is Tuesday after Labor Day and the weekend.
        stamp='2026-09-04T19:55:37Z'
        anchor=zone(98,98.4)
        anchor['pivots'][0].update(date='2026-09-01',confirmed_at='2026-09-03T20:05:00Z')
        p=plan(data_as_of='2026-09-03',decided_at=stamp,
               zones=[anchor])
        self.record(p=p,validity=120,stamp=stamp)
        observed=datetime(2026,9,8,13,35,tzinfo=timezone.utc)
        bar=dict(at='2026-09-08T13:30:00Z',open=100,high=101,low=99.8,close=100)
        engine._pending_recovery_check('AAPL',[bar],observed)
        assert self.fetchall('SELECT status FROM scanner_orders')==[{'status':'pending'}]
        with patch.object(engine,'now_z',return_value=observed.isoformat()):
            engine.process_bar('AAPL',bar);engine.initialize_runtime();engine.process_bar('AAPL',bar)
        assert len(self.fetchall('SELECT id FROM scanner_fills'))==1
        assert self.fetchall('SELECT status FROM scanner_orders')==[{'status':'filled'}]
