import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


ROOT = Path(__file__).resolve().parents[3]
CONFIGURE_SCRIPT = ROOT / "scripts" / "configure_telegram_topics.py"
RESET_SCRIPT = ROOT / "scripts" / "reset_telegram_topics.py"

configure_spec = importlib.util.spec_from_file_location("configure_telegram_topics", CONFIGURE_SCRIPT)
configure_topics = importlib.util.module_from_spec(configure_spec)
assert configure_spec and configure_spec.loader
configure_spec.loader.exec_module(configure_topics)

fake_database = types.ModuleType("database")
fake_database.init_database = Mock()
fake_database.get_db_connection = Mock()
previous_database = sys.modules.get("database")
previous_configure = sys.modules.get("configure_telegram_topics")
sys.modules["database"] = fake_database
sys.modules["configure_telegram_topics"] = configure_topics
try:
    reset_spec = importlib.util.spec_from_file_location("reset_telegram_topics", RESET_SCRIPT)
    reset_topics = importlib.util.module_from_spec(reset_spec)
    assert reset_spec and reset_spec.loader
    reset_spec.loader.exec_module(reset_topics)
finally:
    if previous_database is None:
        sys.modules.pop("database", None)
    else:
        sys.modules["database"] = previous_database
    if previous_configure is None:
        sys.modules.pop("configure_telegram_topics", None)
    else:
        sys.modules["configure_telegram_topics"] = previous_configure


def telegram_response(result=None, *, status_code=200, error=None, retry_after=None):
    response = Mock(ok=error is None, status_code=status_code)
    if error is None:
        response.json.return_value = {"ok": True, "result": result}
    else:
        payload = {"ok": False, "description": error}
        if retry_after is not None:
            payload["parameters"] = {"retry_after": retry_after}
        response.json.return_value = payload
    return response


class ResetTelegramTopicsTests(unittest.TestCase):
    def test_confirmation_is_required_before_reading_credentials_or_calling_telegram(self):
        with patch.object(reset_topics.requests, "Session") as session_factory:
            self.assertEqual(reset_topics.main(), 2)
        session_factory.assert_not_called()

    def test_rate_limit_retries_with_bounded_retry_after(self):
        session = Mock()
        session.post.side_effect = [
            telegram_response(status_code=429, error="Too Many Requests", retry_after=999),
            telegram_response({"id": 7}),
        ]
        with patch.object(reset_topics.time, "sleep") as sleep:
            result = reset_topics._telegram_call(
                session, "https://api.telegram.org/botSECRET", "getMe", {}
            )
        self.assertEqual(result, {"id": 7})
        sleep.assert_called_once_with(reset_topics.MAX_RETRY_AFTER_SECONDS)
        self.assertEqual(session.post.call_count, 2)

    def test_network_error_does_not_expose_bot_token(self):
        session = Mock()
        session.post.side_effect = requests.ConnectionError(
            "failed https://api.telegram.org/botSUPER-SECRET/getMe"
        )
        with self.assertRaises(RuntimeError) as caught:
            reset_topics._telegram_call(
                session, "https://api.telegram.org/botSUPER-SECRET", "getMe", {}
            )
        self.assertNotIn("SUPER-SECRET", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_replacements_are_created_and_persisted_before_old_topics_are_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "TELEGRAM_BOT_TOKEN=secret\n"
                "TELEGRAM_CHAT_ID=-1001\n"
                "TELEGRAM_MARKET_NEWS_THREAD_ID=11\n"
                "TELEGRAM_STOCK_NEWS_THREAD_ID=12\n"
                "TELEGRAM_SIGNALS_THREAD_ID=13\n"
                "TELEGRAM_TRADES_THREAD_ID=14\n"
                "TELEGRAM_PORTFOLIO_THREAD_ID=15\n",
                encoding="utf-8",
            )
            events = []
            next_topic = iter(range(101, 106))
            session = Mock()

            def post(url, **_kwargs):
                method = url.rsplit("/", 1)[-1]
                events.append(method)
                if method == "getMe":
                    return telegram_response({"id": 7})
                if method == "getChat":
                    return telegram_response({"type": "supergroup", "is_forum": True})
                if method == "getChatMember":
                    return telegram_response({"status": "administrator", "can_manage_topics": True})
                if method == "createForumTopic":
                    return telegram_response({"message_thread_id": next(next_topic)})
                if method == "deleteForumTopic":
                    return telegram_response(True)
                raise AssertionError(method)

            session.post.side_effect = post
            cursor = Mock(rowcount=0)
            connection = Mock()
            connection.cursor.return_value = cursor

            def persist(_updates):
                events.append("persist-routing")

            with patch.object(reset_topics, "ROOT", root), \
                 patch.object(reset_topics.requests, "Session", return_value=session), \
                 patch.object(reset_topics, "_write_env", side_effect=persist), \
                 patch.object(reset_topics, "_record_backup"), \
                 patch.object(reset_topics.database, "init_database"), \
                 patch.object(reset_topics.database, "get_db_connection", return_value=connection):
                code = reset_topics.main(confirm_delete=True)

            self.assertEqual(code, 0)
            create_positions = [i for i, event in enumerate(events) if event == "createForumTopic"]
            delete_positions = [i for i, event in enumerate(events) if event == "deleteForumTopic"]
            persisted = events.index("persist-routing")
            self.assertEqual(len(create_positions), 5)
            self.assertEqual(len(delete_positions), 5)
            self.assertLess(max(create_positions), persisted)
            self.assertLess(persisted, min(delete_positions))
            self.assertFalse((root / ".runtime" / reset_topics.RECOVERY_FILE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
