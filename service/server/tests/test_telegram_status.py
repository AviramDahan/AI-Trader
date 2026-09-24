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

    def _seed_open_trade(self, *, ticker="AAPL", company="Apple", order_id=1,
                         external_signal_id="s1", strategy="single"):
        conn = database.get_db_connection(); cur = conn.cursor()
        agent_id = cur.execute("SELECT id FROM agents WHERE name='us-stock-scanner'").fetchone()[0]
        cur.execute("""INSERT INTO scanner_signals(
            external_signal_id,agent_id,scan_id,ticker,company,action,status,planned_entry,actual_entry,
            entry_type,valid_until,original_stop,current_stop,tp1,tp2,tp3,tp1_pct,tp2_pct,tp3_pct,
            rr1,rr2,rr3,weighted_rr,confidence,confidence_basis,time_horizon,reason,reason_he,
            news_json,technical_json,market_context_json,created_at,updated_at)
            VALUES(?,?,'scan',?,?,'BUY','ENTERED',100,100,'limit','2099-01-01T00:00:00Z',
                   95,95,105,110,115,.333333,.333333,.333334,1,2,3,2,.9,'{}','1-4 weeks','reason','סיבה',
                   '[]','{}','{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')""",
                    (external_signal_id, agent_id, ticker, company))
        signal_id = cur.lastrowid
        cur.execute("""INSERT INTO scanner_trades(signal_id,order_id,agent_id,ticker,company,side,strategy,is_shadow,status,
            original_quantity,remaining_quantity,entry_price,original_stop,current_stop,original_r,tp1,tp2,tp3,tp1_pct,tp2_pct,tp3_pct,
            settings_json,opened_at,last_price,managed_from)
            VALUES(?,?,?, ?,?,'long',?,0,'open',1,1,100,95,95,5,105,110,115,.333333,.333333,.333334,
                   '{}','2026-01-01T00:00:00Z',102,'2026-01-01T00:00:00Z')""",
                    (signal_id, order_id, agent_id, ticker, company, strategy))
        trade_id = cur.lastrowid
        cur.execute("INSERT OR REPLACE INTO scanner_quotes(ticker,price,as_of,source) VALUES(?,102,'2026-01-01T00:01:00Z','test')",
                    (ticker,))
        conn.commit(); conn.close()
        return trade_id

    def test_cards_show_account_positions_and_independent_news_tickers(self):
        self._seed_open_trade()
        conn = database.get_db_connection(); cur = conn.cursor()
        agent_id = cur.execute("SELECT id FROM agents WHERE name='us-stock-scanner'").fetchone()[0]
        cur.execute("INSERT INTO scanner_news_watchlist(ticker,company,enabled,created_at,updated_at) VALUES('INTC','Intel',1,'2026-01-01','2026-01-01')")
        cur.execute("UPDATE scanner_accounts SET cash=99900 WHERE agent_id=?", (agent_id,))
        conn.commit(); conn.close()

        portfolio = telegram_status.portfolio_status_message()
        news = telegram_status.news_scope_status_message()
        self.assertIn("תיק דמו ראשי — סיגנלים פעילים", portfolio)
        self.assertIn("סה״כ פוזיציות בתיק הראשי: 1", portfolio)
        self.assertIn("שווי חשבון מנוהל: $100,002.00", portfolio)
        self.assertIn("AAPL", portfolio)
        self.assertIn("מחיר נוכחי: $102.00 (+2.00%)", portfolio)
        self.assertIn("יעד תפעולי: $110.00", portfolio)
        self.assertIn("INTC (Intel)", news)
        self.assertIn("אינו מוגבל לפוזיציות", news)
        self.assertIn("65%", news)
        self.assertIn("אין מכסה לפי מניה", news)
        signals = telegram_status.signals_status_message()
        self.assertIn("סיגנלים פעילים — המשתמש הראשי והיחיד", signals)
        self.assertIn("סה״כ פוזיציות פתוחות:", signals)
        self.assertIn("AAPL", signals)
        self.assertIn("Apple", signals)
        self.assertIn("$102.00", signals)
        self.assertIn("יעד:", signals)
        self.assertIn("טווח זמן:", signals)
        self.assertNotIn("אופק:", signals)
        self.assertIn("\u200f", signals)
        self.assertIn("\u2066", signals)

    def test_market_news_card_documents_official_sources_without_a_hard_cap(self):
        message = telegram_status.market_news_status_message()
        self.assertIn("Federal Reserve", message)
        self.assertIn("BLS", message)
        self.assertIn("אין מכסה קשיחה", message)

    def test_signals_status_uses_next_unfilled_staged_target(self):
        trade_id = self._seed_open_trade(strategy="staged")
        conn = database.get_db_connection(); cur = conn.cursor()
        cur.execute("""INSERT INTO scanner_fills(
            trade_id,event_key,fill_type,target_index,price,quantity,gross_pnl,fee,slippage,bar_at,created_at)
            VALUES(?,'tp1-test','tp',1,105,.33,1.65,0,0,'2026-01-02T00:00:00Z','2026-01-02T00:00:00Z')""",
                    (trade_id,))
        conn.commit(); conn.close()
        message = telegram_status.signals_status_message()
        self.assertIn("$110.00", message)
        self.assertNotIn("יעד: \u2066$105.00", message)

    def test_signals_status_paginates_without_dropping_open_positions(self):
        conn = database.get_db_connection(); cur = conn.cursor()
        agent_id = cur.execute("SELECT id FROM agents WHERE name='us-stock-scanner'").fetchone()[0]
        for index in range(1, 31):
            ticker = f"T{index:03d}"
            cur.execute("""INSERT INTO scanner_signals(
                external_signal_id,agent_id,scan_id,ticker,company,action,status,planned_entry,actual_entry,
                entry_type,valid_until,original_stop,current_stop,tp1,tp2,tp3,tp1_pct,tp2_pct,tp3_pct,
                rr1,rr2,rr3,weighted_rr,confidence,confidence_basis,time_horizon,reason,reason_he,
                news_json,technical_json,market_context_json,created_at,updated_at)
                VALUES(?,?,'scan',?,?,'BUY','ENTERED',100,100,'limit','2099-01-01T00:00:00Z',
                       95,95,105,110,115,.333333,.333333,.333334,1,2,3,2,.9,'{}','1-4 weeks','reason','סיבה',
                       '[]','{}','{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')""",
                        (f"s{index}", agent_id, ticker, f"Company {index}"))
            signal_id = cur.lastrowid
            cur.execute("""INSERT INTO scanner_trades(signal_id,order_id,agent_id,ticker,company,side,strategy,is_shadow,status,
                original_quantity,remaining_quantity,entry_price,original_stop,current_stop,original_r,tp1,tp2,tp3,tp1_pct,tp2_pct,tp3_pct,
                settings_json,opened_at,last_price,managed_from)
                VALUES(?,?,?, ?,?,'long','single',0,'open',1,1,100,95,95,5,105,110,115,.333333,.333333,.333334,
                       '{}','2026-01-01T00:00:00Z',102,'2026-01-01T00:00:00Z')""",
                        (signal_id, index, agent_id, ticker, f"Company {index}"))
        conn.commit(); conn.close()
        pages = telegram_status.signals_status_messages()
        combined = "\n".join(pages)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 4096 for page in pages))
        self.assertIn("סה״כ פוזיציות פתוחות:", pages[0])
        for index in range(1, 31):
            self.assertIn(f"T{index:03d}", combined)

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

    def test_periodic_status_refresh_never_posts_explanatory_news_cards(self):
        with patch.object(telegram_status, "_upsert_pinned_message", return_value="updated") as upsert, \
                patch.object(telegram_status, "_remove_stale_signal_pages", return_value={}):
            result = telegram_status.refresh_telegram_status_cards()
        events = [call.args[1] for call in upsert.call_args_list]
        self.assertEqual(events, ["portfolio_status", "signals_status"])
        self.assertEqual(result, {"portfolio": "updated", "signals_status": "updated"})

    def test_stale_overflow_signal_page_is_unpinned_deleted_and_forgotten(self):
        conn = database.get_db_connection()
        conn.execute("""INSERT INTO scanner_telegram_topic_state(
            state_key,chat_id,thread_id,message_id,content_hash,last_attempt_at,last_success_at,last_error)
            VALUES('signals_status:2','-1001',303,88,'hash','2026-01-01','2026-01-01',NULL)""")
        conn.commit(); conn.close()
        session = Mock()
        unpin = Mock(ok=True); unpin.json.return_value = {"ok": True, "result": True}
        delete = Mock(ok=True); delete.json.return_value = {"ok": True, "result": True}
        session.post.side_effect = [unpin, delete]
        env = {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "-1001"}
        with patch.dict(os.environ, env, clear=False), patch.object(telegram_status.requests, "Session", return_value=session):
            result = telegram_status._remove_stale_signal_pages(1)
        self.assertEqual(result, {"signals_status:2": "deleted"})
        methods = [call.args[0].rsplit("/", 1)[-1] for call in session.post.call_args_list]
        self.assertEqual(methods, ["unpinChatMessage", "deleteMessage"])
        conn = database.get_db_connection()
        row = conn.execute("SELECT 1 FROM scanner_telegram_topic_state WHERE state_key='signals_status:2'").fetchone()
        conn.close()
        self.assertIsNone(row)

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
