import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database
import scanner_engine
import telegram_status


class TelegramStatusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_path = database._SQLITE_DB_PATH
        database._SQLITE_DB_PATH = str(Path(self.directory.name) / "scanner.db")
        database.init_database()
        conn = database.get_db_connection()
        conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','token',100000)")
        conn.commit(); conn.close()
        scanner_engine.initialize_runtime()

    def tearDown(self):
        database._SQLITE_DB_PATH = self.original_path
        self.directory.cleanup()

    def test_cards_show_account_positions_and_independent_news_tickers(self):
        conn = database.get_db_connection(); cur = conn.cursor()
        agent_id = cur.execute("SELECT id FROM agents WHERE name='us-stock-scanner'").fetchone()[0]
        cur.execute("""INSERT INTO scanner_signals(
            external_signal_id,agent_id,scan_id,ticker,company,action,status,planned_entry,actual_entry,
            entry_type,valid_until,original_stop,current_stop,tp1,tp2,tp3,tp1_pct,tp2_pct,tp3_pct,
            rr1,rr2,rr3,weighted_rr,confidence,confidence_basis,time_horizon,reason,reason_he,
            news_json,technical_json,market_context_json,created_at,updated_at)
            VALUES('s1',?,'scan','AAPL','Apple','BUY','ENTERED',100,100,'limit','2099-01-01T00:00:00Z',
                   95,95,105,110,115,.333333,.333333,.333334,1,2,3,2,.9,'{}','1-4 weeks','reason','סיבה',
                   '[]','{}','{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')""", (agent_id,))
        signal_id = cur.lastrowid
        cur.execute("""INSERT INTO scanner_trades(signal_id,order_id,agent_id,ticker,company,side,strategy,is_shadow,status,
            original_quantity,remaining_quantity,entry_price,original_stop,current_stop,original_r,tp1,tp2,tp3,tp1_pct,tp2_pct,tp3_pct,
            settings_json,opened_at,last_price,managed_from)
            VALUES(?,1,?,'AAPL','Apple','long','single',0,'open',1,1,100,95,95,5,105,110,115,.333333,.333333,.333334,
                   '{}','2026-01-01T00:00:00Z',102,'2026-01-01T00:00:00Z')""", (signal_id, agent_id))
        cur.execute("INSERT INTO scanner_quotes(ticker,price,as_of,source) VALUES('AAPL',102,'2026-01-01T00:01:00Z','test')")
        cur.execute("INSERT INTO scanner_news_watchlist(ticker,company,enabled,created_at,updated_at) VALUES('INTC','Intel',1,'2026-01-01','2026-01-01')")
        cur.execute("UPDATE scanner_accounts SET cash=99900 WHERE agent_id=?", (agent_id,))
        conn.commit(); conn.close()

        portfolio = telegram_status.portfolio_status_message()
        news = telegram_status.news_scope_status_message()
        self.assertIn("שווי חשבון מנוהל: $100,002.00", portfolio)
        self.assertIn("AAPL", portfolio)
        self.assertIn("מחיר נוכחי: $102.00 (+2.00%)", portfolio)
        self.assertIn("יעד תפעולי: $110.00", portfolio)
        self.assertIn("INTC (Intel)", news)
        self.assertIn("אינו תלוי בפוזיציות", news)
        self.assertIn("65%", news)

    def test_status_message_is_created_pinned_then_edited(self):
        session = Mock()
        create = Mock(ok=True); create.json.return_value = {"ok": True, "result": {"message_id": 77}}
        pin = Mock(ok=True); pin.json.return_value = {"ok": True, "result": True}
        edit = Mock(ok=True); edit.json.return_value = {"ok": True, "result": {"message_id": 77}}
        repin = Mock(ok=True); repin.json.return_value = {"ok": True, "result": True}
        session.post.side_effect = [create, pin, edit, repin]
        env = {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "-1001", "TELEGRAM_PORTFOLIO_THREAD_ID": "303"}
        with patch.dict(os.environ, env, clear=False), patch.object(telegram_status.requests, "Session", return_value=session):
            self.assertEqual(telegram_status._upsert_pinned_message("portfolio", "portfolio_status", "first"), "created")
            self.assertEqual(telegram_status._upsert_pinned_message("portfolio", "portfolio_status", "second"), "updated")
        calls = [call.args[0].rsplit("/", 1)[-1] for call in session.post.call_args_list]
        self.assertEqual(calls, ["sendMessage", "pinChatMessage", "editMessageText", "pinChatMessage"])
        sent_data = session.post.call_args_list[0].kwargs["data"]
        self.assertEqual(sent_data["message_thread_id"], 303)

    def test_transient_edit_failure_never_creates_a_second_message(self):
        session = Mock()
        create = Mock(ok=True); create.json.return_value = {"ok": True, "result": {"message_id": 77}}
        pin = Mock(ok=True); pin.json.return_value = {"ok": True, "result": True}
        failed_edit = Mock(ok=False, status_code=503)
        failed_edit.json.return_value = {"ok": False, "description": "Temporary upstream failure"}
        session.post.side_effect = [create, pin, failed_edit]
        env = {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "-1001", "TELEGRAM_PORTFOLIO_THREAD_ID": "303"}
        with patch.dict(os.environ, env, clear=False), patch.object(telegram_status.requests, "Session", return_value=session):
            self.assertEqual(telegram_status._upsert_pinned_message("portfolio", "portfolio_status", "first"), "created")
            self.assertEqual(telegram_status._upsert_pinned_message("portfolio", "portfolio_status", "second"), "failed")
        methods = [call.args[0].rsplit("/", 1)[-1] for call in session.post.call_args_list]
        self.assertEqual(methods.count("sendMessage"), 1)
        conn = database.get_db_connection()
        row = conn.execute("SELECT message_id,last_error FROM scanner_telegram_topic_state WHERE state_key='portfolio'").fetchone()
        conn.close()
        self.assertEqual(row["message_id"], 77)
        self.assertIn("Temporary", row["last_error"])

    def test_pin_failure_is_reported_and_existing_message_is_retained(self):
        session = Mock()
        create = Mock(ok=True); create.json.return_value = {"ok": True, "result": {"message_id": 88}}
        failed_pin = Mock(ok=False, status_code=403)
        failed_pin.json.return_value = {"ok": False, "description": "Not enough rights to pin a message"}
        session.post.side_effect = [create, failed_pin]
        env = {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "-1001", "TELEGRAM_PORTFOLIO_THREAD_ID": "303"}
        with patch.dict(os.environ, env, clear=False), patch.object(telegram_status.requests, "Session", return_value=session):
            self.assertEqual(telegram_status._upsert_pinned_message("portfolio", "portfolio_status", "first"), "failed")
        conn = database.get_db_connection()
        row = conn.execute("SELECT message_id,last_success_at,last_error FROM scanner_telegram_topic_state WHERE state_key='portfolio'").fetchone()
        conn.close()
        self.assertEqual(row["message_id"], 88)
        self.assertIsNone(row["last_success_at"])
        self.assertIn("pin:", row["last_error"])


if __name__ == "__main__":
    unittest.main()
