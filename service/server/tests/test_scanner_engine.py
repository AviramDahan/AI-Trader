import os
import sys
import tempfile
import unittest
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
        self.assertFalse(self.fetchall("SELECT * FROM scanner_trades"))
        scanner_engine.process_bar("AAPL", self.bar(1, 101, 101.5, 99.5, 100.5))
        trades = self.fetchall("SELECT * FROM scanner_trades ORDER BY is_shadow")
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["status"], "open")
        self.assertEqual(self.fetchall("SELECT status FROM scanner_signals")[0]["status"], "ENTERED")

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


if __name__ == "__main__":
    unittest.main()
