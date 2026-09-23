import os
import sys
import tempfile
import unittest
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database
import scanner_engine


UTC = timezone.utc


class ScannerEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_path = database._SQLITE_DB_PATH
        database._SQLITE_DB_PATH = str(Path(self.directory.name) / "scanner.db")
        database.init_database()
        conn = database.get_db_connection()
        conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','test-token',100000)")
        conn.commit()
        conn.close()
        with patch.dict(os.environ, {"STOCK_SCANNER_EXIT_STRATEGY": "single"}, clear=False):
            scanner_engine.initialize_runtime()

    def tearDown(self):
        database._SQLITE_DB_PATH = self.original_path
        self.directory.cleanup()

    def signal(self, action="BUY", ticker="AAPL"):
        return {
            "signal_id": 99, "ticker": ticker, "company": "Apple", "action": action,
            "entry": 100, "stop_loss": 97 if action == "BUY" else 103,
            "confidence": .91, "time_horizon": "1-4 weeks", "reason": "Aligned evidence.",
            "telegram_reason_he": "הראיות תומכות באות.", "telegram_news_he": ["כותרת עדכנית"],
            "relevant_news": [{"title": "Current headline", "publisher": "Wire",
                                "published_at": scanner_engine.now_z(), "url": "https://example.test/a"}],
        }

    def candidate(self, ticker="AAPL"):
        return {"ticker": ticker, "company": "Apple", "technical_score": 7,
                "combined_rank_score": .92, "atr": 2, "average_dollar_volume": 1e9}

    def decision(self, action="BUY"):
        return {"action": action, "confidence": .91, "news_relevance": .9, "news_sentiment": .4}

    def record(self, action="BUY", ticker="AAPL"):
        return scanner_engine.record_signal(self.signal(action, ticker), self.candidate(ticker),
                                            self.decision(action), {"SPY": "bullish"}, "scan-1")

    def bar(self, offset, open_price, high, low, close):
        at = (datetime.now(UTC) + timedelta(minutes=offset)).isoformat().replace("+00:00", "Z")
        return {"at": at, "open": open_price, "high": high, "low": low, "close": close}

    def fetchall(self, sql, params=()):
        conn = database.get_db_connection()
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        conn.close()
        return rows

    def test_signal_is_pending_until_a_later_verified_bar(self):
        result = self.record()
        self.assertEqual(result["status"], "PENDING_ENTRY")
        pending = scanner_engine.dashboard_payload()["signals"][0]
        self.assertEqual(
            [pending[f"operational_tp{i}_pct"] for i in (1, 2, 3)],
            [0.0, 1.0, 0.0],
        )
        self.assertFalse(self.fetchall("SELECT * FROM scanner_trades"))
        scanner_engine.process_bar("AAPL", self.bar(1, 101, 101.5, 99.5, 100.5))
        trades = self.fetchall("SELECT * FROM scanner_trades ORDER BY is_shadow")
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["status"], "open")
        dashboard_trades = scanner_engine.dashboard_payload()["trades"]
        primary = next(row for row in dashboard_trades if not row["is_shadow"])
        shadow = next(row for row in dashboard_trades if row["is_shadow"])
        self.assertEqual([primary[f"operational_tp{i}_pct"] for i in (1, 2, 3)], [0.0, 1.0, 0.0])
        self.assertEqual(primary["current_price"], 100.5)
        self.assertEqual(primary["price_source"], "Yahoo completed 5m")
        self.assertFalse(primary["price_stale"])
        self.assertAlmostEqual(sum(shadow[f"operational_tp{i}_pct"] for i in (1, 2, 3)), 1.0)
        self.assertEqual(self.fetchall("SELECT status FROM scanner_signals")[0]["status"], "ENTERED")

    def test_structural_targets_survive_fill_and_quote_updates_do_not_change_entry(self):
        from scanner_targets import structure_plan
        zones = [{"low": p, "high": p, "touches": 1, "pivots": []} for p in (98,104,108,112)]
        signal = self.signal()
        signal.update(target_plan=structure_plan("BUY",100,2,zones,2), quote_at=scanner_engine.now_z())
        scanner_engine.record_signal(signal, self.candidate(), self.decision(), {}, "structured")
        initial = scanner_engine.dashboard_payload()["signals"][0]
        self.assertEqual(initial["current_price"], 100)
        self.assertFalse(initial["price_stale"])
        scanner_engine.process_bar("AAPL", self.bar(1,99.5,101,99,100.5))
        for trade in self.fetchall("SELECT * FROM scanner_trades"):
            self.assertEqual([trade[f"tp{i}"] for i in (1,2,3)], [103.7,107.7,111.7])
        updated = scanner_engine.dashboard_payload()["signals"][0]
        self.assertEqual(updated["current_price"], 100.5)
        self.assertEqual(updated["planned_entry"], 100)
        scanner_engine.process_bar("AAPL", self.bar(2,100.5,101.5,100,101))
        conn = database.get_db_connection()
        conn.execute("DELETE FROM scanner_quotes")
        conn.commit(); conn.close()
        bridged = scanner_engine.dashboard_payload()["signals"][0]
        self.assertEqual(bridged["current_price"], 101)
        self.assertEqual(bridged["price_source"], "Yahoo stored completed 5m")

    def test_missing_quote_not_replaced_with_entry_and_old_quote_is_stale(self):
        self.record()
        self.assertIsNone(scanner_engine.dashboard_payload()["signals"][0]["current_price"])
        conn = database.get_db_connection()
        scanner_engine.store_quote(conn.cursor(), "AAPL", 91, "2026-01-02T15:00:00Z", "test")
        scanner_engine.store_quote(conn.cursor(), "AAPL", 88, "2026-01-01T15:00:00Z", "test")
        conn.commit(); conn.close()
        signal = scanner_engine.dashboard_payload()["signals"][0]
        self.assertEqual(signal["current_price"], 91)
        self.assertTrue(signal["price_stale"])

    def test_batched_minute_quote_refresh_updates_display_cache_and_retains_last_on_failure(self):
        self.record()
        index = pd.DatetimeIndex([datetime.now(UTC) - timedelta(minutes=1)])
        frame = pd.DataFrame({"Close": [123.45]}, index=index)
        with patch.object(scanner_engine.yf, "download", return_value=frame):
            result = scanner_engine.refresh_current_quotes()
        self.assertEqual(result["updated"], 1)
        quote = scanner_engine.quotes_payload()["quotes"][0]
        self.assertEqual(quote["ticker"], "AAPL")
        self.assertAlmostEqual(quote["price"], 123.45)
        self.assertIn("1m batch", quote["source"])
        with patch.object(scanner_engine.yf, "download", side_effect=RuntimeError("rate limited")):
            failed = scanner_engine.refresh_current_quotes()
        self.assertEqual(failed["updated"], 0)
        self.assertAlmostEqual(scanner_engine.quotes_payload()["quotes"][0]["price"], 123.45)

    def test_multi_ticker_quote_extraction_fails_closed_for_absent_symbol(self):
        index = pd.DatetimeIndex([datetime.now(UTC) - timedelta(minutes=1)])
        columns = pd.MultiIndex.from_tuples([("AAPL", "Close"), ("MSFT", "Close")])
        frame = pd.DataFrame([[101.0, 202.0]], index=index, columns=columns)
        self.assertEqual(float(scanner_engine._quote_series(frame, "MSFT").iloc[-1]), 202.0)
        self.assertIsNone(scanner_engine._quote_series(frame, "NVDA"))
        field_first = frame.swaplevel(0, 1, axis=1)
        field_first.columns.names = ["Price", "Ticker"]
        low_columns = pd.MultiIndex.from_tuples(
            [("Close", "LOW"), ("Low", "LOW")], names=["Price", "Ticker"]
        )
        low_frame = pd.DataFrame([[77.0, 76.0]], index=index, columns=low_columns)
        self.assertEqual(float(scanner_engine._quote_series(field_first, "MSFT").iloc[-1]), 202.0)
        self.assertEqual(float(scanner_engine._quote_series(low_frame, "LOW").iloc[-1]), 77.0)

    def test_unexpired_signal_without_order_still_gets_monitored_quote(self):
        self.record()
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_orders SET status='risk_rejected'")
        conn.execute("UPDATE scanner_signals SET status='RISK_BLOCKED'")
        conn.commit(); conn.close()
        with patch.object(scanner_engine, "_bar_dicts", return_value=[self.bar(1,100,102,99,101)]):
            self.assertEqual(scanner_engine.monitor_prices()["tickers"], 1)
        self.assertEqual(scanner_engine.dashboard_payload()["signals"][0]["current_price"], 101)
        self.assertFalse(self.fetchall("SELECT * FROM scanner_trades"))

    def test_same_bar_is_idempotent_after_restart(self):
        self.record()
        entry_bar = self.bar(1, 100, 101, 99, 100)
        scanner_engine.process_bar("AAPL", entry_bar)
        scanner_engine.process_bar("AAPL", entry_bar)
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_trades")), 2)
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='entry'")), 2)

    def test_duplicate_entry_is_blocked_and_shadow_does_not_double_account_cash(self):
        first = self.record()
        second = scanner_engine.record_signal(self.signal(), self.candidate(), self.decision(), {}, "scan-2")
        self.assertEqual(first["status"], "PENDING_ENTRY")
        self.assertEqual(second["status"], "DUPLICATE_BLOCKED")
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        account = self.fetchall("SELECT * FROM scanner_accounts")[0]
        primary = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        expected = account["initial_cash"] - primary["entry_price"] * primary["original_quantity"] - primary["fees"]
        self.assertAlmostEqual(account["cash"], expected, places=5)

    def test_staged_targets_quantities_stop_and_weighted_r(self):
        scanner_engine.set_active_strategy("staged")
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        primary = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.process_bar("AAPL", self.bar(2, 101, primary["tp1"] + .1, 100, primary["tp1"]))
        after_tp1 = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        self.assertAlmostEqual(after_tp1["current_stop"], after_tp1["entry_price"], places=6)
        scanner_engine.process_bar("AAPL", self.bar(3, after_tp1["tp2"], after_tp1["tp3"] + .1,
                                                     after_tp1["entry_price"] + .01, after_tp1["tp3"]))
        closed = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        fills = self.fetchall("SELECT * FROM scanner_fills WHERE trade_id=? AND fill_type='tp' ORDER BY target_index", (closed["id"],))
        self.assertEqual([row["target_index"] for row in fills], [1, 2, 3])
        self.assertAlmostEqual(sum(row["quantity"] for row in fills), closed["original_quantity"], places=6)
        self.assertEqual(closed["status"], "closed")
        gross_r = sum(row["gross_pnl"] for row in fills) / (closed["original_r"] * closed["original_quantity"])
        self.assertAlmostEqual(gross_r, 2.0, delta=.02)

    def test_ambiguous_bar_uses_stop_active_at_bar_open(self):
        scanner_engine.set_active_strategy("staged")
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        trade = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.process_bar("AAPL", self.bar(2, 101, trade["tp1"] + .1, 100, trade["tp1"]))
        trade = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.process_bar("AAPL", self.bar(3, trade["entry_price"], trade["tp2"] + .1,
                                                     trade["entry_price"] - .1, trade["tp2"]))
        fills = self.fetchall("SELECT fill_type,target_index FROM scanner_fills WHERE trade_id=? ORDER BY id", (trade["id"],))
        self.assertEqual(fills[-1]["fill_type"], "stop")
        self.assertNotIn(2, [row["target_index"] for row in fills])

    def test_single_target_full_close_reconciles_cash_fees_and_net_outcome(self):
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        trade = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.process_bar("AAPL", self.bar(2, trade["tp2"], trade["tp2"] + .1,
                                                     trade["current_stop"] + .1, trade["tp2"]))
        closed = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        account = self.fetchall("SELECT * FROM scanner_accounts")[0]
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["outcome"], "WIN")
        self.assertAlmostEqual(account["cash"], account["initial_cash"] + closed["realized_pnl"] - closed["fees"], places=5)
        self.assertAlmostEqual(account["realized_pnl"], closed["realized_pnl"], places=5)
        self.assertAlmostEqual(account["fees_paid"], closed["fees"], places=5)

    def test_stop_after_partial_exit_closes_remainder_and_outcome_uses_total_net(self):
        scanner_engine.set_active_strategy("staged")
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        trade = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.process_bar("AAPL", self.bar(2, trade["tp1"], trade["tp1"] + .1,
                                                     trade["current_stop"] + .1, trade["tp1"]))
        partial = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        self.assertGreater(partial["remaining_quantity"], 0)
        self.assertAlmostEqual(partial["current_stop"], partial["entry_price"], places=6)
        scanner_engine.process_bar("AAPL", self.bar(3, partial["current_stop"] - 1,
                                                     partial["current_stop"] - .5,
                                                     partial["current_stop"] - 2,
                                                     partial["current_stop"] - 1))
        closed = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        fills = self.fetchall("SELECT fill_type,quantity FROM scanner_fills WHERE trade_id=? ORDER BY id", (closed["id"],))
        self.assertEqual([row["fill_type"] for row in fills], ["entry", "tp", "stop"])
        self.assertAlmostEqual(sum(row["quantity"] for row in fills if row["fill_type"] != "entry"), closed["original_quantity"], places=6)
        expected = scanner_engine._outcome(closed["realized_pnl"] - closed["fees"], scanner_engine.lifecycle_settings()["breakeven_threshold"])
        self.assertEqual(closed["outcome"], expected)

    def test_partial_trade_keeps_news_active_then_gap_stop_closes_it(self):
        scanner_engine.set_active_strategy("staged")
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        trade = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.process_bar("AAPL", self.bar(2, 101, trade["tp1"] + .1, 100, trade["tp1"]))
        partial = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        self.assertGreater(partial["remaining_quantity"], 0)
        self.assertNotEqual(self.fetchall("SELECT status FROM scanner_news_schedule")[0]["status"], "closed")
        scanner_engine.process_bar("AAPL", self.bar(3, partial["current_stop"] - 2,
                                                     partial["current_stop"] - 1, partial["current_stop"] - 3,
                                                     partial["current_stop"] - 2))
        closed = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(self.fetchall("SELECT status FROM scanner_news_schedule")[0]["status"], "closed")

    def test_sell_without_position_is_bearish_only_and_never_short(self):
        result = self.record("SELL", "MSFT")
        self.assertEqual(result["status"], "BEARISH_ONLY")
        self.assertFalse(self.fetchall("SELECT * FROM scanner_orders WHERE side='sell'"))
        self.assertFalse(self.fetchall("SELECT * FROM scanner_trades WHERE side='short'"))

    def test_signal_expiry_and_stale_recovery_fail_closed(self):
        self.record()
        future = datetime.now(UTC) + timedelta(days=8)
        scanner_engine.process_bar("AAPL", {"at": future.isoformat().replace("+00:00", "Z"),
                                             "open": 105, "high": 106, "low": 104, "close": 105})
        self.assertEqual(self.fetchall("SELECT status FROM scanner_orders")[0]["status"], "expired")
        with self.assertRaises(RuntimeError):
            scanner_engine._bar_dicts("AAPL", datetime.now(UTC) - timedelta(days=61))

    def test_position_news_runs_once_per_ticker_dedupes_and_does_not_change_trade(self):
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        before = self.fetchall("SELECT remaining_quantity,current_stop FROM scanner_trades WHERE is_shadow=0")[0]
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_news_schedule SET next_due_at='2000-01-01T00:00:00Z' WHERE ticker='AAPL'")
        conn.commit(); conn.close()
        item = {"title": "Apple files results", "publisher": "Wire", "url": "https://example.test/results",
                "published_at": scanner_engine.now_z(), "relevance": .95}
        analyzed = [{**item, "related": True, "impact": "mixed", "materiality": "high",
                     "thesis_effect": "unchanged", "summary_he": "פורסמו תוצאות.",
                     "explanation_he": "ההשפעה האפשרית מעורבת וקיימת אי־ודאות."}]
        with patch("stock_scanner.fetch_recent_news", return_value=[item]) as fetch, \
             patch.object(scanner_engine, "analyze_position_news", return_value=analyzed):
            first = scanner_engine.monitor_position_news()
            conn = database.get_db_connection()
            conn.execute("UPDATE scanner_news_schedule SET next_due_at='2000-01-01T00:00:00Z' WHERE ticker='AAPL'")
            conn.commit(); conn.close()
            second = scanner_engine.monitor_position_news()
        after = self.fetchall("SELECT remaining_quantity,current_stop FROM scanner_trades WHERE is_shadow=0")[0]
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(before, after)
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_news WHERE scope='open_position'")), 1)
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_telegram_outbox WHERE event_type='position_news'")), 1)

    def test_position_news_provider_failure_is_not_reported_as_no_news(self):
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 100, 101, 99, 100))
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_news_schedule SET next_due_at='2000-01-01T00:00:00Z' WHERE ticker='AAPL'")
        conn.commit(); conn.close()
        with patch("stock_scanner.fetch_recent_news", side_effect=RuntimeError("provider unavailable")):
            result = scanner_engine.monitor_position_news()
        self.assertTrue(result["errors"])
        schedule = self.fetchall("SELECT * FROM scanner_news_schedule")[0]
        self.assertEqual(schedule["status"], "error")
        self.assertNotEqual(schedule["status"], "no_new")

    def test_telegram_failure_retries_without_blocking_signal(self):
        self.record()
        with patch.dict(os.environ, {"STOCK_SCANNER_TELEGRAM_ENABLED": "true"}, clear=False), \
             patch("stock_scanner.send_telegram", return_value="failed"):
            result = scanner_engine.process_telegram_outbox()
        self.assertGreaterEqual(result["failed"], 1)
        self.assertTrue(self.fetchall("SELECT * FROM scanner_telegram_outbox WHERE status='retry'"))

    def test_entry_photo_queued_once_after_text_and_failure_does_not_repeat_text(self):
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1,100,101,99,100))
        with patch.dict(os.environ, {"STOCK_SCANNER_TELEGRAM_ENABLED":"true", "STOCK_SCANNER_TELEGRAM_ENTRY_ALERTS":"true"}), \
             patch("stock_scanner.send_telegram", return_value="sent") as text_sender, \
             patch("telegram_charts.send_entry_chart", return_value="failed") as photo_sender:
            scanner_engine.process_telegram_outbox()
            text_count = text_sender.call_count
            scanner_engine.process_telegram_outbox()
            self.assertEqual(text_sender.call_count,text_count)
            photo_sender.assert_called_once()
        photos = self.fetchall("SELECT * FROM scanner_telegram_outbox WHERE event_type='entry_chart'")
        self.assertEqual(len(photos),1)
        self.assertEqual(photos[0]["status"],"retry")
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")),1)
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01',attempts=4 WHERE event_type='entry_chart'")
        conn.commit(); conn.close()
        with patch.dict(os.environ, {"STOCK_SCANNER_TELEGRAM_ENABLED":"true", "STOCK_SCANNER_TELEGRAM_ENTRY_ALERTS":"true"}), \
             patch("telegram_charts.send_entry_chart", return_value="failed"):
            scanner_engine.process_telegram_outbox()
        self.assertEqual(self.fetchall("SELECT status FROM scanner_telegram_outbox WHERE event_type='entry_chart'")[0]["status"],"failed")

    def test_monitor_first_order_has_unambiguous_start_and_rejects_prior_bar(self):
        self.record()
        old = self.bar(-10, 100, 101, 99, 100)
        with patch.object(scanner_engine, "_bar_dicts", return_value=[old]):
            result = scanner_engine.monitor_prices()
        self.assertFalse(result["errors"])
        self.assertFalse(self.fetchall("SELECT * FROM scanner_trades"))
        self.assertEqual(self.fetchall("SELECT status FROM scanner_orders")[0]["status"], "pending")

    def test_price_provider_excludes_current_incomplete_candle(self):
        now = datetime.now(UTC)
        start = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
        frame = pd.DataFrame({"Open": [100, 100], "High": [101, 120], "Low": [99, 80], "Close": [100, 90]},
                             index=pd.DatetimeIndex([start-timedelta(minutes=5), start]))
        with patch.object(scanner_engine.yf, "Ticker") as provider:
            provider.return_value.history.return_value = frame
            bars = scanner_engine._bar_dicts("AAPL", start-timedelta(minutes=10))
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 100)

    def test_entry_candle_ambiguity_applies_stop_not_same_candle_profit(self):
        self.record()
        scanner_engine.process_bar("AAPL", self.bar(1, 101, 110, 96, 100))
        trade = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        self.assertEqual(trade["status"], "closed")
        self.assertEqual(trade["outcome"], "LOSS")
        fills = self.fetchall("SELECT fill_type FROM scanner_fills WHERE trade_id=? ORDER BY id", (trade["id"],))
        self.assertEqual([row["fill_type"] for row in fills], ["entry", "stop"])

    def test_live_verification_remains_pending_without_real_native_cycle(self):
        report = scanner_engine.dashboard_payload()["lifecycle_verification"]
        self.assertFalse(report["live_e2e_complete"])
        self.assertTrue(report["accounting_ok"])

    def test_complete_isolated_single_and_shadow_cycle_with_monitor_restart_and_alert_retry(self):
        self.record()
        entry = self.bar(1, 100, 101, 99, 100)
        with patch.object(scanner_engine, "_bar_dicts", return_value=[entry]):
            self.assertFalse(scanner_engine.monitor_prices()["errors"])
        trade = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        tp1 = self.bar(2, trade["tp1"], trade["tp1"]+.1, trade["entry_price"]+.1, trade["tp1"])
        scanner_engine.process_bar("AAPL", tp1)
        shadow = self.fetchall("SELECT * FROM scanner_trades WHERE is_shadow=1")[0]
        self.assertAlmostEqual(shadow["current_stop"], shadow["entry_price"])
        self.assertGreater(shadow["remaining_quantity"], 0)
        scanner_engine.initialize_runtime()
        tp3 = self.bar(3, trade["tp2"], trade["tp3"]+.1, trade["entry_price"]+.1, trade["tp3"])
        with patch.object(scanner_engine, "_bar_dicts", return_value=[tp1, tp3]):
            self.assertFalse(scanner_engine.monitor_prices()["errors"])
        closed = self.fetchall("SELECT * FROM scanner_trades ORDER BY is_shadow")
        self.assertTrue(all(row["status"] == "closed" for row in closed))
        self.assertEqual(len(self.fetchall("SELECT * FROM scanner_fills WHERE fill_type='entry'")), 2)
        with patch.dict(os.environ, {"STOCK_SCANNER_TELEGRAM_ENABLED": "true"}, clear=False), \
             patch("stock_scanner.send_telegram", return_value="failed"):
            self.assertGreater(scanner_engine.process_telegram_outbox()["failed"], 0)
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z' WHERE status='retry'")
        conn.commit(); conn.close()
        with patch.dict(os.environ, {"STOCK_SCANNER_TELEGRAM_ENABLED": "true"}, clear=False), \
             patch("stock_scanner.send_telegram", return_value="sent"):
            self.assertGreater(scanner_engine.process_telegram_outbox()["sent"], 0)
        report = scanner_engine.dashboard_payload()["lifecycle_verification"]
        self.assertTrue(report["accounting_ok"], report)
        self.assertEqual(report["stages"]["entry"], 1)
        self.assertEqual(report["stages"]["closed"], 1)
        self.assertEqual(report["stages"]["telegram_exit"], 1)
        self.assertFalse(report["live_e2e_complete"])  # no stop/six-hour evidence fabricated


if __name__ == "__main__":
    unittest.main()
