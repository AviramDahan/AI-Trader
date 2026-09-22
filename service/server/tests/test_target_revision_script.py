import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "service" / "server"))
sys.path.insert(0, str(ROOT / "scripts"))

import database
import revise_open_position_targets as revisions
import scanner_engine


class TargetRevisionScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_path = database._SQLITE_DB_PATH
        database._SQLITE_DB_PATH = str(Path(self.directory.name) / "scanner.db")
        database.init_database()
        conn = database.get_db_connection()
        conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','test-token',100000)")
        conn.commit(); conn.close()
        with patch.dict(os.environ, {"STOCK_SCANNER_EXIT_STRATEGY": "single"}, clear=False):
            scanner_engine.initialize_runtime()

    def tearDown(self):
        database._SQLITE_DB_PATH = self.original_path
        self.directory.cleanup()

    def _bar(self):
        stamp = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        return {"at": stamp, "open": 99.5, "high": 101, "low": 99, "close": 100.5}

    def test_apply_is_audited_preserves_accounting_and_is_idempotent(self):
        signal = {
            "signal_id": 1, "ticker": "AAPL", "company": "Apple", "action": "BUY",
            "entry": 100, "stop_loss": 97, "confidence": .9, "time_horizon": "1-4 weeks",
            "reason": "test", "relevant_news": [],
        }
        scanner_engine.record_signal(
            signal,
            {"ticker": "AAPL", "company": "Apple", "technical_score": 7, "combined_rank_score": .9},
            {"news_relevance": .9, "news_sentiment": .2},
            {},
            "scan",
        )
        scanner_engine.process_bar("AAPL", self._bar())
        conn = database.get_db_connection()
        before = dict(conn.execute("SELECT * FROM scanner_trades WHERE is_shadow=0").fetchone())
        before_fill_count = conn.execute("SELECT COUNT(*) FROM scanner_fills").fetchone()[0]
        before_outbox_count = conn.execute("SELECT COUNT(*) FROM scanner_telegram_outbox").fetchone()[0]
        groups = revisions._load_open_groups(conn)
        conn.close()
        entry, stop = float(before["entry_price"]), float(before["original_stop"])
        targets = [round(entry + 4, 2), round(entry + 8, 2), round(entry + 12, 2)]
        rr = [(value - entry) / (entry - stop) for value in targets]
        plan = {
            "method": "daily_resistance_and_measured_move_v1",
            "entry": entry, "stop": stop, "current_reference": entry,
            "data_as_of": "2026-09-22", "atr": 2.0, "targets": targets,
            "rr": rr, "weighted_rr": sum(rr) / 3,
            "fractions": [.333333, .333333, .333334], "objectives": [],
        }
        signal_id = next(iter(groups))
        fake_backup = Path(self.directory.name) / "backup.db"
        with patch.object(revisions, "_backup_sqlite", return_value=fake_backup):
            self.assertEqual(revisions._apply(groups, {signal_id: plan}, "test"), 2)
            conn = database.get_db_connection()
            after = dict(conn.execute("SELECT * FROM scanner_trades WHERE is_shadow=0").fetchone())
            self.assertEqual([after[f"tp{i}"] for i in (1, 2, 3)], targets)
            for field in ("entry_price", "original_stop", "current_stop", "original_r",
                          "original_quantity", "remaining_quantity", "realized_pnl", "fees"):
                self.assertEqual(after[field], before[field], field)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scanner_fills").fetchone()[0], before_fill_count)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scanner_telegram_outbox").fetchone()[0], before_outbox_count)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scanner_target_revisions").fetchone()[0], 2)
            groups_after = revisions._load_open_groups(conn)
            conn.close()
            self.assertEqual(revisions._apply(groups_after, {signal_id: plan}, "test"), 0)
            conn = database.get_db_connection()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scanner_target_revisions").fetchone()[0], 2)
            conn.close()


if __name__ == "__main__":
    unittest.main()
