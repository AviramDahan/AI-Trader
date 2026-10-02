"""Offline regression examples; all writes go to a disposable test database."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import test_scanner_engine as fixtures
import scanner_engine as engine
import database
from pathlib import Path


class TradingCorrectnessTests(unittest.TestCase):
    setUp = fixtures.ScannerEngineTests.setUp
    tearDown = fixtures.ScannerEngineTests.tearDown
    record = fixtures.ScannerEngineTests.record
    signal = fixtures.ScannerEngineTests.signal
    candidate = fixtures.ScannerEngineTests.candidate
    decision = fixtures.ScannerEngineTests.decision
    fetchall = fixtures.ScannerEngineTests.fetchall
    bar = fixtures.ScannerEngineTests.bar

    def pending_window(self):
        self.record()
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET created_at='2026-09-28T13:30:00Z',valid_until='2026-09-28T13:45:00Z'")
            c.execute("UPDATE scanner_signals SET created_at='2026-09-28T13:30:00Z',valid_until='2026-09-28T13:45:00Z'")

    def replay(self, bars, now='2026-09-28T14:00:00+00:00'):
        observed = datetime.fromisoformat(now)
        with patch.object(engine, 'datetime', wraps=datetime) as clock, patch.object(engine, '_bar_dicts', return_value=bars):
            clock.now.side_effect = lambda tz=None: observed.astimezone(tz)
            return engine.monitor_prices()

    def bars(self, touch=True):
        return [dict(at=f'2026-09-28T13:{minute}:00Z', open=101, high=102,
                     low=99 if touch else 101, close=101) for minute in ('30','35','40')]

    def test_recover_legal_fill_before_expiry_after_outage(self):
        self.pending_window()
        self.replay(list(reversed(self.bars())))
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'], 'filled')
        count = len(self.fetchall('SELECT * FROM scanner_fills'))
        self.replay(self.bars())
        self.assertEqual(len(self.fetchall('SELECT * FROM scanner_fills')), count)

    def test_sell_limit_floor_before_fees_and_restart(self):
        self.record()
        engine.process_bar('AAPL', self.bar(1,100,101,99,100))
        self.record(action='SELL')
        bar = self.bar(2,100,101,99,100)
        engine.process_bar('AAPL', bar)
        fills = self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='sell'")
        self.assertTrue(fills)
        self.assertTrue(all(f['price'] >= 100 for f in fills))
        self.assertTrue(all(f['fee'] > 0 for f in fills))
        engine.process_bar('AAPL', bar)
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='sell'")),len(fills))

    def test_drawdown_unavailable_without_equity_history(self):
        self.record()
        engine.process_bar('AAPL', self.bar(1,100,101,99,100))
        for row in engine.dashboard_payload()['strategy_comparison']:
            self.assertIsNone(row['current_drawdown'])
            self.assertIsNone(row['maximum_drawdown'])
            self.assertIsNone(row['drawdown_available_since'])
            self.assertEqual(row['drawdown_status'], 'UNAVAILABLE_NO_EQUITY_HISTORY')

    def test_before_expiry_recovery(self):
        self.pending_window()
        self.replay(self.bars()[:1], '2026-09-28T13:36:00+00:00')
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'filled')

    def test_no_touch_expires_only_after_recovery(self):
        self.pending_window()
        self.replay(self.bars(touch=False))
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'expired')
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))

    def test_missing_bars_explicit_uncertainty_not_fill(self):
        self.pending_window()
        self.replay(self.bars()[1:])
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'recovery_uncertain')
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.replay(self.bars())
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.assertEqual(self.record()['status'],'DUPLICATE_BLOCKED')

    def test_empty_data_explicit_uncertainty(self):
        self.pending_window()
        self.replay([])
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'recovery_uncertain')

    def test_fetch_failure_keeps_pending_and_reports_error(self):
        self.pending_window()
        with patch.object(engine,'_bar_dicts',side_effect=TimeoutError):
            result=engine.monitor_prices()
        self.assertIn('AAPL:TimeoutError',result['errors'])
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'pending')
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))

    def test_gap_after_proven_entry_does_not_erase_entry_evidence(self):
        self.pending_window()
        self.replay(self.bars()[:1])
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'filled')

    def test_candle_ending_exactly_at_expiry_is_eligible(self):
        self.pending_window()
        bars=self.bars(False);bars[-1]['low']=99
        self.replay(bars,'2026-09-28T13:45:00+00:00')
        fills=self.fetchall("SELECT bar_at FROM scanner_fills WHERE fill_type='entry'")
        self.assertEqual(len(fills),2)
        self.assertTrue(all(f['bar_at']=='2026-09-28T13:40:00Z' for f in fills))

    def test_incomplete_candle_not_consumed(self):
        self.pending_window()
        self.replay(self.bars()[:1], '2026-09-28T13:34:59+00:00')
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.assertFalse(self.fetchall('SELECT * FROM scanner_price_cursors'))
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'pending')

    def test_expiry_boundary_crossing_candle_cannot_fill(self):
        self.pending_window()
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET valid_until='2026-09-28T13:42:00Z'")
        bars=self.bars(False)
        bars[-1]['low']=99
        self.replay(bars)
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'recovery_uncertain')

    def test_creation_boundary_crossing_candle_cannot_fill(self):
        self.pending_window()
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET created_at='2026-09-28T13:32:00Z'")
        bars=self.bars(False)
        bars[0]['low']=99
        self.replay(bars)
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'recovery_uncertain')

    def test_terminal_order_never_revived(self):
        self.pending_window()
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET status='expired'")
        self.replay(self.bars())
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))

    def test_sell_gap_above_limit_retains_slippage(self):
        self.record()
        engine.process_bar('AAPL',self.bar(1,100,101,99,100))
        self.record(action='SELL')
        engine.process_bar('AAPL',self.bar(2,102,103,101,102))
        fills=self.fetchall("SELECT price FROM scanner_fills WHERE fill_type='sell'")
        self.assertTrue(fills)
        for f in fills:self.assertAlmostEqual(f['price'],102*(1-engine.lifecycle_settings()['slippage_bps']/10000))

    def test_sell_without_touch_stays_pending(self):
        self.record()
        engine.process_bar('AAPL',self.bar(1,100,101,99,100))
        self.record(action='SELL')
        engine.process_bar('AAPL',self.bar(2,99,99.5,98,99))
        self.assertFalse(self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='sell'"))
        self.assertEqual(self.fetchall("SELECT status FROM scanner_orders WHERE purpose='close_long'")[0]['status'],'pending')

    def test_stop_gap_has_no_limit_floor(self):
        self.record()
        engine.process_bar('AAPL',self.bar(1,100,101,99,100))
        engine.process_bar('AAPL',self.bar(2,90,91,89,90))
        fills=self.fetchall("SELECT price FROM scanner_fills WHERE fill_type='stop'")
        self.assertTrue(fills)
        self.assertTrue(all(f['price']<90 for f in fills))

    def test_buy_limit_never_above_limit(self):
        self.record()
        engine.process_bar('AAPL',self.bar(1,101,102,99,100))
        self.assertTrue(all(f['price']<=100 for f in self.fetchall("SELECT price FROM scanner_fills WHERE fill_type='entry'")))

    def rollback_paths(self, compatible=False):
        # Exact function snapshots from 10bd6ea, checked against git before PR.
        # Shared dependencies use identical production helpers; no external calls.
        namespace = dict(vars(engine))
        for name in ('record_signal','monitor_prices','process_bar','initialize_runtime'):
            source=(Path(__file__).parent/'fixtures'/f'rollback_10bd6ea_{name}.txt').read_text()
            if compatible and name=='record_signal':
                self.assertEqual(source.count("o.status='pending'"),2)
                source=source.replace("o.status='pending'", "o.status IN ('pending','recovery_uncertain')")
            exec(compile(source, f'rollback_10bd6ea_{name}', 'exec'), namespace)
        return namespace

    def test_old_rollback_is_unsafe_duplicate_entry_reproduced(self):
        self.pending_window(); self.replay([])
        cash=self.fetchall('SELECT cash FROM scanner_accounts')[0]['cash']
        old=self.rollback_paths()
        old['initialize_runtime']()
        result=old['record_signal'](self.signal(),self.candidate(),self.decision(),{},'rollback-test')
        self.assertEqual(result['status'],'PENDING_ENTRY')  # proves unsafe, NOT expected safety
        self.assertEqual(self.fetchall('SELECT cash FROM scanner_accounts')[0]['cash'],cash)
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))

    def test_old_rollback_loses_cash_reservation_reproduced(self):
        self.pending_window(); self.replay([])
        notional=self.fetchall('SELECT limit_price*quantity n FROM scanner_orders')[0]['n']
        with database.get_db_connection() as c:
            c.execute('UPDATE scanner_accounts SET cash=?',(notional+1,))
        old=self.rollback_paths()
        result=old['record_signal'](self.signal(ticker='MSFT'),self.candidate('MSFT'),self.decision(),{},'rollback-test')
        self.assertEqual(result['status'],'PENDING_ENTRY')  # ignores existing reservation

    def test_compatible_rollback_retains_holds_across_restart_and_monitor(self):
        self.pending_window(); self.replay([])
        before=self.fetchall('SELECT * FROM scanner_accounts')
        compatible=self.rollback_paths(compatible=True)
        compatible['initialize_runtime']()
        compatible['_bar_dicts']=lambda *args: self.bars()
        compatible['monitor_prices']()
        result=compatible['record_signal'](self.signal(),self.candidate(),self.decision(),{},'rollback-test')
        self.assertEqual(result['status'],'DUPLICATE_BLOCKED')
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.assertEqual(self.fetchall('SELECT cash,fees_paid FROM scanner_accounts')[0],
                         {k:before[0][k] for k in ('cash','fees_paid')})
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'recovery_uncertain')
        engine.initialize_runtime(); self.replay(self.bars())
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        holds=engine.dashboard_payload()['recovery_holds']
        self.assertEqual(len(holds['orders']),1)
        self.assertGreater(holds['reserved_entry_notional'],0)

    def test_compatible_rollback_preserves_cash_and_exposure_admission(self):
        self.pending_window(); self.replay([])
        notional=self.fetchall('SELECT limit_price*quantity n FROM scanner_orders')[0]['n']
        compatible=self.rollback_paths(compatible=True)
        with database.get_db_connection() as c:
            c.execute('UPDATE scanner_accounts SET cash=?',(notional+1,))
        self.assertEqual(compatible['record_signal'](self.signal(ticker='MSFT'),self.candidate('MSFT'),self.decision(),{},'cash')['status'],'RISK_BLOCKED')
        with database.get_db_connection() as c:
            c.execute('UPDATE scanner_accounts SET cash=100000')
        cfg=engine.lifecycle_settings() | {'max_total_exposure':notional*1.5}
        compatible['lifecycle_settings']=lambda:cfg
        self.assertEqual(compatible['record_signal'](self.signal(ticker='MSFT'),self.candidate('MSFT'),self.decision(),{},'exposure')['status'],'RISK_BLOCKED')

    def test_uncertain_order_does_not_stop_existing_position_exit(self):
        self.record(ticker='MSFT')
        engine.process_bar('MSFT',self.bar(1,100,101,99,100))
        self.pending_window(); self.replay([])
        engine.process_bar('MSFT',self.bar(2,90,91,89,90))
        self.assertTrue(self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='stop'"))
        self.assertTrue(engine.dashboard_payload()['lifecycle_verification']['accounting_ok'])
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_orders WHERE status='recovery_uncertain'")),1)

    def test_recovered_fill_replaces_reservation_once_with_cash_debit(self):
        self.pending_window()
        self.replay(self.bars()[:1],'2026-09-28T13:36:00+00:00')
        first=self.fetchall('SELECT cash,fees_paid FROM scanner_accounts')
        engine.initialize_runtime();self.replay(self.bars()[:1],'2026-09-28T13:36:00+00:00')
        self.assertEqual(self.fetchall('SELECT cash,fees_paid FROM scanner_accounts'),first)
        self.assertFalse(self.fetchall("SELECT * FROM scanner_orders WHERE status IN ('pending','recovery_uncertain')"))
        self.assertTrue(engine.dashboard_payload()['lifecycle_verification']['accounting_ok'])

    def test_closed_sessions_are_not_missing_candles(self):
        # Undo fixture calendar mock: exercise actual weekend/full holiday/overnight rules.
        self.market_clock.stop()
        self.record()
        windows=[('2026-09-04T20:00:00Z','2026-09-08T13:35:00Z'), # Labor Day + weekend
                 ('2026-09-28T20:00:00Z','2026-09-29T13:35:00Z')]
        for start,end in windows:
            with self.subTest(start=start):
                with database.get_db_connection() as c:
                    c.execute("UPDATE scanner_orders SET status='pending',created_at=?,valid_until=?",(start,end))
                at=(datetime.fromisoformat(end.replace('Z','+00:00'))-timedelta(minutes=5)).isoformat()
                engine._pending_recovery_check('AAPL',[dict(at=at,open=101,high=102,low=101,close=101)],datetime.fromisoformat(end.replace('Z','+00:00')))
                self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'pending')

    def test_timeout_retry_retains_hold_then_single_fill(self):
        self.pending_window()
        before=self.fetchall('SELECT cash,fees_paid FROM scanner_accounts')
        with patch.object(engine,'_bar_dicts',side_effect=TimeoutError):engine.monitor_prices()
        self.assertEqual(self.record()['status'],'DUPLICATE_BLOCKED')
        self.assertEqual(self.fetchall('SELECT cash,fees_paid FROM scanner_accounts'),before)
        self.replay(self.bars());self.replay(self.bars())
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='entry' AND trade_id IN (SELECT id FROM scanner_trades WHERE is_shadow=0)")),1)

    def test_boundary_without_touch_can_advance_to_full_candle(self):
        self.pending_window()
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET created_at='2026-09-28T13:32:00Z'")
        bars=self.bars(False);bars[1]['low']=99
        self.replay(bars)
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'filled')

    def test_readonly_chain_separates_imports_and_new_native_closure(self):
        from trading_chain_evidence import chain_evidence
        self.record();engine.process_bar('AAPL',self.bar(1,100,101,99,100))
        engine.process_bar('AAPL',self.bar(2,90,91,89,90))
        before=self.fetchall('SELECT * FROM scanner_fills')
        with database.get_db_connection() as c:
            fresh=chain_evidence(c,(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
            imported=chain_evidence(c,(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        self.assertEqual(fresh['new_native_closed_chain'],'OBSERVED_LINKED_RECORDS')
        self.assertEqual(sum(r['closed_chain_evidence'] for r in fresh['chains']),1)
        self.assertEqual(imported['new_native_closed_chain'],'WAITING_FOR_NATURAL_EVENT')
        self.assertEqual(self.fetchall('SELECT * FROM scanner_fills'),before)

    def test_drawdown_frontend_has_no_numeric_or_ranking_consumer(self):
        source=(Path(__file__).resolve().parents[2]/'frontend/src/ScannerDashboard.tsx').read_text(encoding='utf-8')
        self.assertIn('drawdown are unavailable',source)
        self.assertNotIn('row.current_drawdown',source)
        self.assertNotIn('row.maximum_drawdown',source)
        self.assertNotIn('strategy_comparison || []).sort',source)
