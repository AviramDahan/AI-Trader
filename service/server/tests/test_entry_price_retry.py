"""Synthetic full application; no external HTTP/AI/Telegram or production DB."""
import copy
import json
import unittest
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import scanner_engine as engine
import entry_price_retry as retry
import test_scanner_engine as fixture
from test_single_target_v2 import zone
import single_breakout_policy as breakout
import single_target_policy as single

FLAGS = dict(STOCK_SCANNER_EXIT_STRATEGY='single', STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED='true',
             STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED='true', STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED='true',
             STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED='true')
STAMP = '2026-10-06T14:00:37Z'


def narrow_plan(created=STAMP, v2=False):
    zones = [zone(99.5, 99.6)]
    if v2:
        return single.build(100, 1, zones + [zone(103.15, 103.3)], '2026-09-25', created)
    return breakout.build(100, 1, zones, '2026-09-25', created, 99.7)


class TestPriceRetryLifecycle(unittest.TestCase):
    setUp = fixture.ScannerEngineTests.setUp
    tearDown = fixture.ScannerEngineTests.tearDown
    signal = fixture.ScannerEngineTests.signal
    candidate = fixture.ScannerEngineTests.candidate
    decision = fixture.ScannerEngineTests.decision
    fetchall = fixture.ScannerEngineTests.fetchall

    def record(self, ticker='TEST', enabled=True, created=STAMP, hours=24, v2=False):
        p = narrow_plan(created, v2)
        s = dict(self.signal(ticker=ticker), signal_id=None, target_plan=p, stop_loss=p['stop'])
        cfg = engine.lifecycle_settings() | {'active_strategy':'single', 'slippage_bps':5, 'signal_validity_hours':hours}
        flags = dict(FLAGS, STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED=str(enabled).lower())
        with patch.dict('os.environ', flags), patch.object(engine, 'now_z', return_value=created), patch.object(engine, 'lifecycle_settings', return_value=cfg):
            result = engine.record_signal(s, self.candidate(ticker), self.decision(), {}, 'synthetic-price-retry')
        return result, p

    def bar(self, minute=5, opening=99.8, low=None):
        return dict(at=f'2026-10-06T14:{minute:02d}:00Z', open=opening, high=max(100.2, opening+.2),
                    low=min(opening-.1, 99.99) if low is None else low, close=opening+.05)

    def process(self, bar, ticker='TEST', observed='2026-10-06T14:30:00Z'):
        with patch.object(engine, 'now_z', return_value=observed):
            engine.process_bar(ticker, bar)

    def order(self):
        return self.fetchall("SELECT * FROM scanner_orders WHERE purpose='entry' ORDER BY id")[0]

    def balance(self):
        return self.fetchall('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')

    def waiting_messages(self):
        return self.fetchall("SELECT * FROM scanner_telegram_outbox WHERE dedupe_key LIKE 'order-status:%:price-wait'")

    def test_bad_price_then_valid_price_fills_once_with_creation_off(self):
        _, p = self.record()
        before = self.balance()
        self.process(self.bar())
        o = self.order();contract = json.loads(o['plan_json'])
        assert o['status']=='pending' and o['filled_quantity']==0 and o['average_fill_price'] is None
        assert contract['last_entry_price_block']['reason']=='fill_stop_distance_invalid'
        assert self.balance()==before and not self.fetchall('SELECT id FROM scanner_trades')
        assert contract['target_plan']==p and contract['entry_price_retry']['version']==retry.VERSION
        assert len(self.waiting_messages())==1
        assert 'ממתין למחיר כניסה תקף' in self.waiting_messages()[0]['message']
        assert 'הפקודה נשארת ממתינה' in self.waiting_messages()[0]['message']
        assert engine.dashboard_payload()['signals'][0]['entry_price_wait']['reason']=='fill_stop_distance_invalid'
        duplicate = self.record()[0]
        assert duplicate['status']=='DUPLICATE_BLOCKED' and self.balance()==before
        with patch.dict('os.environ', STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED='false'):
            engine.initialize_runtime()
            good = self.bar(10, 100.05)
            self.process(good);engine.initialize_runtime();self.process(good)
        assert self.order()['status']=='filled' and len(self.fetchall('SELECT id FROM scanner_fills'))==1
        t=self.fetchall('SELECT * FROM scanner_trades')[0]
        assert not t['is_shadow'] and t['entry_price']==100
        assert [t['original_stop'],t['tp1'],t['tp2'],t['tp3']]==[p['stop'],p['active_target'],None,None]
        assert json.loads(t['settings_json'])['entry_price_retry']==contract['entry_price_retry']
        assert engine.dashboard_payload()['signals'][0]['entry_price_wait'] is None
        self.process(dict(at='2026-10-06T14:15:00Z',open=103,high=103.2,low=102.8,close=103.1))
        engine.initialize_runtime()
        assert self.fetchall('SELECT status,remaining_quantity FROM scanner_trades')==[dict(status='closed',remaining_quantity=0)]
        assert len(self.fetchall('SELECT id FROM scanner_fills'))==2
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_default_off_and_retained_old_order_keep_terminal_behavior(self):
        with patch.dict('os.environ', {}, clear=True):assert not retry.enabled()
        self.record(enabled=False)
        assert 'entry_price_retry' not in json.loads(self.order()['plan_json'])
        with patch.dict('os.environ', FLAGS):
            self.process(self.bar());self.process(self.bar(10,100.05))
        assert self.order()['status']=='invalid'
        assert not self.fetchall('SELECT id FROM scanner_fills') and not self.waiting_messages()

    def test_repeated_rejections_have_one_notice_and_no_account_debit(self):
        self.record();before=self.balance()
        for minute in (5,10,15):
            bar=self.bar(minute);self.process(bar);self.process(bar)
            engine.initialize_runtime()
        assert self.order()['status']=='pending' and self.balance()==before
        assert len(self.waiting_messages())==1 and not self.fetchall('SELECT id FROM scanner_fills')
        assert json.loads(self.order()['plan_json'])['last_entry_price_block']['bar_at'].endswith('14:15:00+00:00')

    def test_normal_first_fill_and_v2_not_only_breakout(self):
        self.record(v2=True);self.process(self.bar(5,100.05))
        assert self.order()['status']=='filled' and not self.waiting_messages()
        assert len(self.fetchall('SELECT id FROM scanner_fills'))==1

    def test_v2_bad_price_then_later_valid_price_keeps_same_plan(self):
        _,p=self.record(v2=True);self.process(self.bar());self.process(self.bar(10,100.05))
        assert self.order()['status']=='filled'
        assert json.loads(self.order()['plan_json'])['target_plan']==p

    def test_complete_expiry_without_fill_is_once_and_does_not_extend(self):
        self.record(created='2026-10-06T14:00:00Z',hours=.25)
        for minute in (0,5,10):self.process(self.bar(minute),observed='2026-10-06T14:15:00Z')
        before=self.balance();engine._expire_recovered_orders('TEST',datetime(2026,10,6,14,15,1,tzinfo=timezone.utc))
        assert self.order()['status']=='expired' and self.order()['valid_until']=='2026-10-06T14:15:00Z'
        self.process(self.bar(15,100.05));engine.initialize_runtime()
        assert self.balance()==before and not self.fetchall('SELECT id FROM scanner_fills')
        assert len(self.fetchall("SELECT id FROM scanner_telegram_outbox WHERE dedupe_key LIKE 'order-status:%:expired'"))==1

    def test_gap_after_price_wait_becomes_uncertain_not_a_later_fill(self):
        self.record();self.process(self.bar());before=self.balance()
        later=self.bar(15,100.05)
        engine._pending_recovery_check('TEST',[later],datetime(2026,10,6,14,20,tzinfo=timezone.utc))
        assert self.order()['status']=='recovery_uncertain'
        self.process(later);engine.initialize_runtime();engine._expire_recovered_orders('TEST',datetime(2026,10,9,tzinfo=timezone.utc))
        assert self.order()['status']=='recovery_uncertain' and self.balance()==before
        assert not self.fetchall('SELECT id FROM scanner_fills')
        assert self.record()[0]['status']=='DUPLICATE_BLOCKED'

    def test_partial_and_extended_candles_do_not_retry_or_fill(self):
        self.record();self.process(self.bar(),observed='2026-10-06T14:07:00Z')
        assert 'last_entry_price_block' not in json.loads(self.order()['plan_json'])
        self.process(dict(self.bar(),execution_session='extended'))
        assert not self.waiting_messages() and not self.fetchall('SELECT id FROM scanner_fills')

    def test_no_limit_touch_does_not_report_a_price_rejection(self):
        self.record()
        self.process(dict(at='2026-10-06T14:05:00Z',open=101,high=102,low=100.5,close=101))
        assert self.order()['status']=='pending' and not self.waiting_messages()
        assert 'last_entry_price_block' not in json.loads(self.order()['plan_json'])
        self.process(self.bar(10,100.05))
        assert len(self.fetchall('SELECT id FROM scanner_fills'))==1

    def test_price_wait_across_weekend_and_holiday_is_not_a_false_gap(self):
        self.market_clock.stop()
        stamp='2026-09-04T19:50:00Z'
        anchor=zone(99.5,99.6)
        anchor['pivots'][0].update(date='2026-09-01',confirmed_at='2026-09-03T20:05:00Z')
        p=breakout.build(100,1,[anchor],'2026-09-03',stamp,99.7)
        signal=dict(self.signal(ticker='TEST'),target_plan=p,stop_loss=p['stop'])
        cfg=engine.lifecycle_settings() | {'active_strategy':'single','slippage_bps':5,'signal_validity_hours':120}
        with patch.dict('os.environ',FLAGS),patch.object(engine,'now_z',return_value=stamp),patch.object(engine,'lifecycle_settings',return_value=cfg):
            engine.record_signal(signal,self.candidate('TEST'),self.decision(),{},'synthetic-weekend')
        first=dict(at='2026-09-04T19:50:00Z',open=99.8,high=100.2,low=99.7,close=99.85)
        self.process(first,observed='2026-09-04T19:55:00Z')
        last=dict(first,at='2026-09-04T19:55:00Z')
        self.process(last,observed='2026-09-04T20:00:00Z')
        tuesday=dict(at='2026-09-08T13:30:00Z',open=100.05,high=100.2,low=99.95,close=100.1)
        engine._pending_recovery_check('TEST',[tuesday],datetime(2026,9,8,13,35,tzinfo=timezone.utc))
        assert self.order()['status']=='pending'
        self.process(tuesday,observed='2026-09-08T13:35:00Z')
        engine.initialize_runtime();self.process(tuesday,observed='2026-09-08T13:35:00Z')
        assert self.order()['status']=='filled' and len(self.fetchall('SELECT id FROM scanner_fills'))==1
        assert len(self.waiting_messages())==1

    def test_corrupt_contract_is_terminal_not_a_price_retry(self):
        self.record()
        with database.get_db_connection() as c:
            contract=json.loads(self.order()['plan_json']);contract['entry_price_retry']['version']='future'
            c.execute('UPDATE scanner_orders SET plan_json=?',(json.dumps(contract),));c.commit()
        self.process(self.bar(5,100.05))
        assert self.order()['status']=='invalid' and not self.waiting_messages()
        assert json.loads(self.order()['plan_json'])['entry_rejection_reason']=='unsupported_entry_price_retry'
        assert not self.fetchall('SELECT id FROM scanner_fills')

    def test_corrupt_signal_levels_remain_terminal(self):
        self.record()
        with database.get_db_connection() as c:c.execute('UPDATE scanner_signals SET original_stop=99');c.commit()
        self.process(self.bar(5,100.05))
        assert self.order()['status']=='invalid' and not self.waiting_messages()
        assert not self.fetchall('SELECT id FROM scanner_fills')

    def test_corrupt_execution_settings_do_not_crash_or_soft_retry(self):
        self.record()
        with database.get_db_connection() as c:
            contract=json.loads(self.order()['plan_json']);contract['execution_settings']=[]
            c.execute('UPDATE scanner_orders SET plan_json=?',(json.dumps(contract),));c.commit()
        self.process(self.bar(5,100.05))
        assert self.order()['status']=='invalid' and not self.waiting_messages()
        assert not self.fetchall('SELECT id FROM scanner_fills')

    def test_valid_retry_does_not_bypass_existing_allocation_guard(self):
        self.record();self.process(self.bar())
        with database.get_db_connection() as c:c.execute('UPDATE scanner_accounts SET cash=0');c.commit()
        self.process(self.bar(10,100.05))
        assert self.order()['status']=='risk_rejected'
        assert not self.fetchall('SELECT id FROM scanner_fills')
        assert engine.dashboard_payload()['signals'][0]['entry_price_wait'] is None

    def test_retry_entry_still_uses_stop_first_in_ambiguous_bar(self):
        self.record();self.process(self.bar())
        bar=dict(at='2026-10-06T14:10:00Z',open=100.05,high=103.5,low=98,close=102)
        self.process(bar);engine.initialize_runtime();self.process(bar)
        assert self.fetchall('SELECT fill_type FROM scanner_fills ORDER BY id')==[dict(fill_type='entry'),dict(fill_type='stop')]
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


@pytest.mark.parametrize('damage',['unknown','expiry','window','null','extra','negative','fake_reason','future','partial','missing_contract'])
def test_retry_contract_and_observation_validation_is_fail_closed(damage):
    import entry_window
    p=narrow_plan();until='2026-10-07T14:00:37Z'
    window=entry_window.build(STAMP,until)
    contract=dict(target_plan=p,execution_settings={'active_strategy':'single'},entry_execution=window,
                  entry_price_retry=retry.build(STAMP,until,p,window))
    order=dict(purpose='entry',side='buy',order_type='limit',limit_price=100,created_at=STAMP,
               updated_at='2026-10-06T14:30:00Z',valid_until=until,status='pending')
    contract=retry.observe(order,contract,99.8499,'2026-10-06T14:05:00Z','2026-10-06T14:10:00Z','fill_stop_distance_invalid')
    if damage=='unknown':contract['entry_price_retry']['version']='unknown'
    if damage=='expiry':contract['entry_price_retry']['valid_until']='2026-10-08T14:00:37Z'
    if damage=='window':contract['entry_execution']['entry_eligible_from']='2026-10-06T13:55:00Z'
    if damage=='null':contract['entry_price_retry']=None
    if damage=='extra':contract['last_entry_price_block']['secret']='synthetic-untrusted-extra'
    if damage=='negative':contract['last_entry_price_block']['price']=-1
    if damage=='fake_reason':contract['last_entry_price_block']['reason']='fill_rr_below_2'
    if damage=='future':contract['last_entry_price_block']['observed_at']='2026-10-09T14:00:00Z'
    if damage=='partial':contract['last_entry_price_block']['bar_at']='2026-10-06T14:06:00Z'
    if damage=='missing_contract':contract.pop('entry_price_retry')
    order['plan_json']=json.dumps(contract)
    with pytest.raises(ValueError):retry.validate_order(order)
    assert retry.public_wait(order) is None


from test_signal_inputs import db,clock


@pytest.mark.parametrize('blocked',['off','window_off','hold','confidence','quote','session','resistance','high','budget'])
def test_creation_enabled_preserves_real_scanner_gates(db,clock,monkeypatch,blocked):
    from test_single_breakout import test_actual_scanner_gate_failures_preserved
    monkeypatch.setenv('STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED','true')
    test_actual_scanner_gate_failures_preserved(db,clock,monkeypatch,blocked)


def test_actual_scan_order_bad_then_good_price_uses_existing_lifecycle(db,clock,monkeypatch):
    from test_signal_admission_chain import prepare,rows
    import stock_scanner as scanner
    candidate,review,_=prepare(monkeypatch,clock)
    candidate['price_zones']=[zone(98,98.4)];candidate['recent_high_20d']=99
    clock.instant=datetime(2026,10,6,14,0,37,tzinfo=timezone.utc)
    for key,value in FLAGS.items():monkeypatch.setenv(key,value)
    result=scanner.run_scan()
    assert result['signals_published']==review.call_count==1
    contract=json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    assert contract['entry_price_retry']['version']==retry.VERSION
    clock.instant=datetime(2026,10,6,14,10,tzinfo=timezone.utc)
    engine.process_bar('TEST',dict(at='2026-10-06T14:05:00Z',open=99,high=100.2,low=98.9,close=99.5))
    assert rows('SELECT status FROM scanner_orders')==[dict(status='pending')]
    assert not rows('SELECT id FROM scanner_fills')
    monkeypatch.setenv('STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED','false')
    clock.instant=datetime(2026,10,6,14,15,tzinfo=timezone.utc)
    good=dict(at='2026-10-06T14:10:00Z',open=100.05,high=101,low=99.8,close=100)
    engine.process_bar('TEST',good);engine.initialize_runtime();engine.process_bar('TEST',good)
    assert rows('SELECT status FROM scanner_orders')==[dict(status='filled')]
    assert len(rows('SELECT id FROM scanner_trades'))==len(rows('SELECT id FROM scanner_fills'))==1
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
