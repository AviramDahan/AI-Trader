"""Isolated lifecycle audit regressions; no providers, AI or Telegram calls."""
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import scanner_engine as engine
import test_scanner_engine as base
import test_entry_price_retry as retry_cases
import test_scanner_legacy as legacy_cases


class TestTeamTradingRegressions(unittest.TestCase):
    setUp = base.ScannerEngineTests.setUp
    tearDown = base.ScannerEngineTests.tearDown
    signal = base.ScannerEngineTests.signal
    candidate = base.ScannerEngineTests.candidate
    decision = base.ScannerEngineTests.decision
    fetchall = base.ScannerEngineTests.fetchall
    record_retry = retry_cases.TestPriceRetryLifecycle.record
    retry_bar = retry_cases.TestPriceRetryLifecycle.bar
    balance = retry_cases.TestPriceRetryLifecycle.balance

    def entry_order(self):
        return self.fetchall("SELECT * FROM scanner_orders WHERE purpose='entry' ORDER BY id")[0]

    def close_order(self):
        return self.fetchall("SELECT * FROM scanner_orders WHERE purpose='close_long' ORDER BY id")[0]

    def monitor(self, bars, minute=20):
        observed = datetime(2026, 10, 6, 14, minute, tzinfo=timezone.utc)
        with patch.object(engine, 'datetime', wraps=datetime) as clock, \
                patch.object(engine, '_bar_dicts', return_value=bars), \
                patch.dict('os.environ', STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED='false',
                           STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED='false',
                           STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED='false',
                           STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED='false'):
            clock.now.side_effect = lambda tz=None: observed.astimezone(tz)
            return engine.monitor_prices()

    def assert_same_batch_retry_gap(self, v2):
        self.record_retry(v2=v2)
        before = self.balance()
        engine.initialize_runtime()
        # The rejected touch has NOT been processed in an earlier run. The
        # missing 14:10 candle belongs to this same outage/recovery batch.
        bars = [self.retry_bar(5), self.retry_bar(15, 100.05)]
        self.monitor(bars)
        assert self.entry_order()['status'] == 'recovery_uncertain'
        assert self.balance() == before
        assert not self.fetchall('SELECT id FROM scanner_fills')
        assert self.fetchall("SELECT sum(limit_price*quantity) n FROM scanner_orders WHERE status='recovery_uncertain'")[0]['n'] == 100
        engine.initialize_runtime()
        self.monitor([self.retry_bar(5), self.retry_bar(10, 100.05), bars[-1]])
        assert self.entry_order()['status'] == 'recovery_uncertain'
        assert self.balance() == before
        assert not self.fetchall('SELECT id FROM scanner_fills')
        with patch.object(engine, 'now_z', return_value='2026-10-06T14:20:00Z'):
            duplicate = engine.record_signal(self.signal(ticker='TEST'), {}, {}, {}, 'held-duplicate')
        assert duplicate['status'] == 'DUPLICATE_BLOCKED'
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_same_batch_rejected_price_gap_holds_breakout(self):
        self.assert_same_batch_retry_gap(False)

    def test_same_batch_rejected_price_gap_holds_v2(self):
        self.assert_same_batch_retry_gap(True)

    def test_complete_retry_batch_still_fills_once_with_creation_off_and_restart(self):
        _, plan = self.record_retry()
        bars = [self.retry_bar(5), self.retry_bar(10), self.retry_bar(15, 100.05)]
        self.monitor(bars)
        order = self.entry_order()
        assert order['status'] == 'filled'
        assert len(self.fetchall('SELECT id FROM scanner_fills')) == 1
        trade = self.fetchall('SELECT * FROM scanner_trades')[0]
        assert trade['original_quantity'] == order['filled_quantity'] == order['quantity']
        assert trade['remaining_quantity'] == trade['original_quantity']
        assert [trade['original_stop'], trade['tp1'], trade['tp2'], trade['tp3']] == [plan['stop'], plan['active_target'], None, None]
        assert trade['fees'] == self.fetchall('SELECT fee FROM scanner_fills')[0]['fee']
        before = self.balance()
        engine.initialize_runtime()
        self.monitor(bars)
        assert self.balance() == before
        assert len(self.fetchall('SELECT id FROM scanner_fills')) == 1
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_admissible_first_touch_is_not_held_by_later_gap(self):
        self.record_retry(v2=True)
        self.monitor([self.retry_bar(5, 100.05), self.retry_bar(15, 100.05)])
        assert self.entry_order()['status'] == 'filled'
        assert len(self.fetchall('SELECT id FROM scanner_fills')) == 1
        assert not self.fetchall("SELECT id FROM scanner_orders WHERE status='recovery_uncertain'")
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_admissible_entry_keeps_adverse_same_bar_stop_before_later_gap(self):
        self.record_retry()
        entry = dict(at='2026-10-06T14:05:00Z', open=100.05, high=103.5, low=98, close=102)
        self.monitor([entry, self.retry_bar(15, 100.05)])
        assert self.entry_order()['status'] == 'filled'
        assert [f['fill_type'] for f in self.fetchall('SELECT fill_type FROM scanner_fills ORDER BY id')] == ['entry', 'stop']
        assert self.fetchall('SELECT status,remaining_quantity FROM scanner_trades') == [dict(status='closed', remaining_quantity=0)]
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def plain_record(self, minute, action='BUY', ticker='AAPL'):
        with patch.object(engine, 'now_z', return_value=f'2026-10-06T14:{minute:02d}:00Z'):
            return engine.record_signal(self.signal(action, ticker), self.candidate(ticker), self.decision(action), {}, 'linked-close')

    def plain_bar(self, minute, opening, high, low, close, ticker='AAPL'):
        bar = dict(at=f'2026-10-06T14:{minute:02d}:00Z', open=opening, high=high, low=low, close=close)
        with patch.object(engine, 'now_z', return_value='2026-10-06T14:55:00Z'):
            engine.process_bar(ticker, bar)
        return bar

    def pending_close(self):
        self.plain_record(0)
        self.plain_bar(5, 100, 101, 99, 100)
        original = self.fetchall('SELECT * FROM scanner_trades WHERE is_shadow=0')[0]
        self.plain_record(10, 'SELL')
        assert self.close_order()['client_order_key'] == f"signal:{self.close_order()['signal_id']}:close:{original['id']}"
        return original

    def test_stale_sell_cannot_close_replacement_after_original_stop(self):
        original = self.pending_close()
        self.plain_bar(15, 90, 91, 89, 90)
        replacement = self.plain_record(20)
        assert replacement['status'] == 'PENDING_ENTRY'
        self.plain_bar(25, 99.5, 99.9, 99, 99.5)
        trade = self.fetchall('SELECT * FROM scanner_trades WHERE signal_id=? AND is_shadow=0', (replacement['id'],))[0]
        assert trade['tp2'] > 100.2
        before = self.balance()
        bar = self.plain_bar(30, 99.7, 100.2, 99.5, 100)
        assert self.fetchall('SELECT status FROM scanner_trades WHERE id=?', (trade['id'],))[0]['status'] == 'open'
        assert self.close_order()['status'] == 'invalid'
        assert self.close_order()['filled_quantity'] == 0
        assert self.close_order()['average_fill_price'] is None
        assert self.balance() == before
        assert not self.fetchall("SELECT id FROM scanner_fills WHERE trade_id=? AND fill_type='sell'", (trade['id'],))
        engine.initialize_runtime()
        engine.process_bar('AAPL', bar)
        assert self.balance() == before
        assert self.fetchall('SELECT status FROM scanner_trades WHERE id=?', (original['id'],))[0]['status'] == 'closed'
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_old_sell_touch_without_original_position_is_not_a_fill(self):
        self.pending_close()
        self.plain_bar(15, 90, 91, 89, 90)
        before = self.balance()
        self.plain_bar(20, 100, 101, 99, 100)
        order = self.close_order()
        assert order['status'] == 'invalid'
        assert order['filled_quantity'] == 0 and order['average_fill_price'] is None
        assert self.balance() == before
        assert not self.fetchall("SELECT id FROM scanner_fills WHERE fill_type='sell'")

    def test_genuine_sell_closes_only_original_primary_and_shadow_once(self):
        original = self.pending_close()
        bar = self.plain_bar(15, 102, 103, 101, 102)
        order = self.close_order()
        exits = self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='sell'")
        assert order['status'] == 'filled' and order['filled_quantity'] == original['remaining_quantity']
        assert len(exits) == 2
        assert all(fill['quantity'] == original['remaining_quantity'] and fill['fee'] > 0 and fill['price'] >= order['limit_price'] for fill in exits)
        assert all(t['status'] == 'closed' for t in self.fetchall('SELECT status FROM scanner_trades'))
        before = self.balance()
        engine.initialize_runtime()
        engine.process_bar('AAPL', bar)
        assert self.balance() == before and len(self.fetchall("SELECT id FROM scanner_fills WHERE fill_type='sell'")) == 2
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_partial_original_sell_records_actual_primary_remaining_quantity(self):
        engine.set_active_strategy('staged')
        self.plain_record(0)
        self.plain_bar(5, 100, 101, 99, 100)
        sell = dict(self.signal('SELL'), entry=105, stop_loss=108)
        with patch.object(engine, 'now_z', return_value='2026-10-06T14:07:00Z'):
            engine.record_signal(sell, {}, {}, {}, 'pending-before-partial')
        self.plain_bar(10, 101, 103.5, 100.5, 103)
        original = self.fetchall('SELECT * FROM scanner_trades WHERE is_shadow=0')[0]
        assert original['remaining_quantity'] < original['original_quantity']
        assert self.close_order()['quantity'] > original['remaining_quantity']
        self.plain_bar(20, 105.5, 105.8, 104, 105.5)
        assert self.close_order()['filled_quantity'] == original['remaining_quantity']
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_malformed_missing_or_shadow_anchor_fails_closed(self):
        original = self.pending_close()
        order = self.close_order()
        shadow = self.fetchall('SELECT id FROM scanner_trades WHERE is_shadow=1')[0]['id']
        keys = ['malformed', f"signal:{order['signal_id']+1}:close:{original['id']}",
                f"signal:{order['signal_id']}:close:999999999", f"signal:{order['signal_id']}:close:{shadow}",
                f"signal:{order['signal_id']}:close:9999999999999999999999999999999999"]
        before = self.balance()
        for minute, key in enumerate(keys, 3):
            with self.subTest(key=key):
                with database.get_db_connection() as conn:
                    conn.execute("UPDATE scanner_orders SET client_order_key=?,status='pending' WHERE id=?", (key, order['id']))
                self.plain_bar(minute * 5, 100, 100.2, 99.5, 100)
                assert self.close_order()['status'] == 'invalid'
                assert self.close_order()['filled_quantity'] == 0
                assert self.balance() == before
                assert not self.fetchall("SELECT id FROM scanner_fills WHERE fill_type='sell'")
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


class TestTeamLegacyCloseRegressions(unittest.TestCase):
    setUp = legacy_cases.LegacyAdoptionTests.setUp
    tearDown = legacy_cases.LegacyAdoptionTests.tearDown
    rows = legacy_cases.LegacyAdoptionTests.rows

    def adopt(self):
        if not database.using_postgres():
            return legacy_cases.LegacyAdoptionTests.adopt(self)
        original_insert = legacy_cases.legacy._insert

        def retained_fixture_insert(cur, table, values):
            # Match the existing test_recovery_holds retained-state seed seam:
            # the historical adopter expects lastrowid for a position_id-keyed
            # table. Only seed that return value; exit execution is unmocked.
            if table == 'scanner_legacy_adoptions':
                keys = list(values)
                cur.execute(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",
                            tuple(values[key] for key in keys))
                return values['position_id']
            return original_insert(cur, table, values)

        with patch.object(legacy_cases.legacy, '_insert', side_effect=retained_fixture_insert):
            return legacy_cases.LegacyAdoptionTests.adopt(self)

    def test_retained_legacy_close_anchor_uses_original_wallet_once(self):
        self.adopt()
        original = self.rows('SELECT * FROM scanner_trades')[0]
        account = self.rows('SELECT cash,fees_paid FROM scanner_accounts')
        wallet = self.rows('SELECT cash FROM agents')[0]['cash']
        signal = dict(ticker='TEST', company='Synthetic', action='SELL', entry=100, stop_loss=103,
                      confidence=.9, time_horizon='1-4 weeks', reason='Synthetic retained exit')
        with patch.object(engine, 'now_z', return_value=self.at.isoformat()):
            engine.record_signal(signal, {}, {}, {}, 'retained-linked-close')
        order = self.rows("SELECT * FROM scanner_orders WHERE purpose='close_long'")[0]
        assert order['client_order_key'] == f"signal:{order['signal_id']}:close:{original['id']}"
        bar = dict(at='2026-09-22T13:35:00Z', open=102, high=103, low=101, close=102)
        engine.process_bar('TEST', bar)
        fill = self.rows("SELECT * FROM scanner_fills WHERE fill_type='sell'")[0]
        assert self.rows('SELECT quantity FROM positions')[0]['quantity'] == 0
        assert self.rows('SELECT cash FROM agents')[0]['cash'] == wallet + fill['price'] * fill['quantity'] - fill['fee']
        assert self.rows('SELECT cash,fees_paid FROM scanner_accounts') == account
        engine.initialize_runtime()
        engine.process_bar('TEST', bar)
        assert len(self.rows('SELECT id FROM scanner_fills')) == 1
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
