import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import scanner_engine as engine
import scanner_legacy as legacy


class LegacyAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = database._SQLITE_DB_PATH
        database._SQLITE_DB_PATH = str(Path(self.temp.name) / "isolated.db")
        database.init_database()
        self.at = datetime(2026, 9, 22, 13, 32, tzinfo=timezone.utc)
        conn = database.get_db_connection()
        conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','isolated',99900)")
        conn.execute("""INSERT INTO positions(agent_id,symbol,market,side,quantity,entry_price,current_price,opened_at)
                        VALUES(1,'TEST','us-stock','long',1,100,102,'2026-09-14T13:30:00Z')""")
        conn.execute("""INSERT INTO signals(signal_id,agent_id,message_type,market,signal_type,symbol,side,entry_price,quantity,timestamp,created_at,executed_at)
                        VALUES(11,1,'operation','us-stock','realtime','TEST','buy',100,1,1,'2026-09-14T13:30:00Z','2026-09-14T13:30:00Z')""")
        tracked = dict(ticker="TEST", company="Test Company", action="BUY", paper_execution="long_opened",
                       entry=100, stop_loss=97, take_profit=106.1, paper_quantity=1, signal_id=11, status="OPEN")
        conn.execute("INSERT INTO scanner_legacy_records(source,source_key,payload_json,imported_at) VALUES(?,?,?,?)",
                     ("stock-scanner.json", "tracked:11", json.dumps(tracked), self.at.isoformat()))
        conn.commit(); conn.close()
        engine.initialize_runtime()

    def tearDown(self):
        database._SQLITE_DB_PATH = self.old_db
        self.temp.cleanup()

    def rows(self, query, args=()):
        conn = database.get_db_connection()
        rows = [dict(row) for row in conn.execute(query, args).fetchall()]
        conn.close()
        return rows

    def adopt(self):
        with patch.object(engine, "now_z", return_value=self.at.isoformat()):
            return legacy.adopt_positions()

    def test_adoption_preserves_cash_exact_levels_and_history_without_new_fills_or_alerts(self):
        self.assertTrue(legacy.audit_positions()[0]["eligible"])
        self.assertEqual(len(self.adopt()["adopted"]), 1)
        trade = self.rows("SELECT * FROM scanner_trades")[0]
        self.assertEqual(trade["tp2"], 106.1)  # original, not recalculated 2R=106
        self.assertEqual(trade["opened_at"], "2026-09-14T13:30:00Z")
        self.assertEqual(trade["strategy"], "single")
        self.assertEqual(self.rows("SELECT cash FROM agents")[0]["cash"], 99900)
        self.assertEqual(self.rows("SELECT cash FROM scanner_accounts")[0]["cash"], 100000)
        self.assertFalse(self.rows("SELECT * FROM scanner_fills"))
        self.assertFalse(self.rows("SELECT * FROM scanner_telegram_outbox"))
        self.assertEqual(legacy.audit_positions()[0]["adopted"]["trade_id"], trade["id"])
        self.assertEqual(self.adopt()["adopted"], [])
        self.assertEqual(len(self.rows("SELECT * FROM positions")), 1)

    def test_ambiguous_or_mismatched_evidence_blocks_all_adoption(self):
        conn = database.get_db_connection()
        conn.execute("UPDATE positions SET quantity=2")
        conn.commit(); conn.close()
        self.assertFalse(legacy.audit_positions()[0]["eligible"])
        with self.assertRaises(ValueError):
            self.adopt()
        self.assertFalse(self.rows("SELECT * FROM scanner_trades"))

    def test_forward_gap_stop_updates_original_wallet_only_and_is_restart_safe(self):
        self.adopt()
        old = dict(at="2026-09-15T14:00:00Z", open=110, high=111, low=109, close=110)
        engine.process_bar("TEST", old)
        self.assertFalse(self.rows("SELECT * FROM scanner_fills"))
        bar = dict(at="2026-09-22T13:35:00Z", open=95, high=96, low=94, close=95)
        engine.process_bar("TEST", bar)
        engine.initialize_runtime()
        engine.process_bar("TEST", bar)
        trade = self.rows("SELECT * FROM scanner_trades")[0]
        fill = self.rows("SELECT * FROM scanner_fills")[0]
        self.assertEqual(trade["status"], "closed")
        self.assertEqual(trade["unrealized_pnl"], 0)
        self.assertEqual(self.rows("SELECT quantity FROM positions")[0]["quantity"], 0)
        self.assertAlmostEqual(self.rows("SELECT cash FROM agents")[0]["cash"], 99900+fill["price"]-fill["fee"])
        self.assertEqual(self.rows("SELECT cash FROM scanner_accounts")[0]["cash"], 100000)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_fills")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_telegram_outbox")), 1)
        self.assertEqual(self.rows("SELECT status FROM scanner_news_schedule")[0]["status"], "closed")
        dashboard = engine.dashboard_payload()
        self.assertEqual(dashboard["strategy_comparison"], [])
        self.assertEqual(dashboard["lifecycle_verification"]["stages"]["entry"], 0)
        self.assertTrue(dashboard["lifecycle_verification"]["accounting_ok"])

    def test_adopted_position_blocks_new_duplicate_buy_and_initial_news_is_due(self):
        self.adopt()
        signal = dict(ticker="TEST", company="Test", action="BUY", entry=102, stop_loss=99,
                      confidence=.9, time_horizon="1-4 weeks", reason="test only")
        result = engine.record_signal(signal, {}, {}, {}, "isolated")
        self.assertEqual(result["status"], "DUPLICATE_BLOCKED")
        schedule = self.rows("SELECT * FROM scanner_news_schedule")[0]
        self.assertEqual(schedule["status"], "due")
        self.assertEqual(schedule["next_due_at"], self.at.isoformat())

    def test_original_trading_path_cannot_mutate_adopted_position(self):
        self.adopt()
        from services import _update_position_from_signal
        agent_id = self.rows("SELECT agent_id FROM positions")[0]["agent_id"]
        with self.assertRaisesRegex(ValueError, "scanner lifecycle only"):
            _update_position_from_signal(agent_id, "TEST", "us-stock", "sell", 1, 105, self.at.isoformat())
        self.assertEqual(self.rows("SELECT quantity FROM positions")[0]["quantity"], 1)


if __name__ == "__main__":
    unittest.main()
