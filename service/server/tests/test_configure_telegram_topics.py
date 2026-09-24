import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "configure_telegram_topics.py"
SPEC = importlib.util.spec_from_file_location("configure_telegram_topics", SCRIPT)
topics_setup = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(topics_setup)


def response(result):
    is_error = isinstance(result, dict) and "__error__" in result
    value = Mock(ok=not is_error)
    value.json.return_value = ({"ok": False, "description": result["__error__"]}
                               if is_error else {"ok": True, "result": result})
    return value


class ConfigureTelegramTopicsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.env = self.root / ".env"
        self.credentials = self.root / "PRIVATE_SETUP_CREDENTIALS.txt"

    def tearDown(self):
        self.directory.cleanup()

    def run_with(self, values, results):
        self.env.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
        session = Mock()
        session.post.side_effect = lambda url, **kwargs: response(results[url.rsplit("/", 1)[-1]])
        with patch.object(topics_setup, "ENV_FILE", self.env), \
             patch.object(topics_setup, "CREDENTIALS_FILE", self.credentials), \
             patch.object(topics_setup.requests, "Session", return_value=session):
            code = topics_setup.main()
        return code, session

    def test_non_forum_fails_closed_without_creating_topics(self):
        code, session = self.run_with(
            {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "-1"},
            {"getChat": {"type": "group", "is_forum": False}, "getUpdates": []},
        )
        self.assertEqual(code, 3)
        self.assertFalse(any(call.args[0].endswith("/createForumTopic") for call in session.post.call_args_list))

    def test_existing_thread_ids_are_idempotent(self):
        code, session = self.run_with(
            {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "-1001",
             "TELEGRAM_NEWS_THREAD_ID": "101", "TELEGRAM_TRADING_THREAD_ID": "202",
             "TELEGRAM_MARKET_NEWS_THREAD_ID": "111", "TELEGRAM_STOCK_NEWS_THREAD_ID": "112",
             "TELEGRAM_SIGNALS_THREAD_ID": "211", "TELEGRAM_TRADES_THREAD_ID": "212",
             "TELEGRAM_PORTFOLIO_THREAD_ID": "303"},
            {"getChat": {"type": "supergroup", "is_forum": True},
             "getMe": {"id": 7},
             "getChatMember": {"status": "administrator", "can_manage_topics": True},
             "editForumTopic": True},
        )
        self.assertEqual(code, 0)
        self.assertFalse(any(call.args[0].endswith("/createForumTopic") for call in session.post.call_args_list))

    def test_already_named_topics_are_idempotent(self):
        code, session = self.run_with(
            {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "-1001",
             "TELEGRAM_MARKET_NEWS_THREAD_ID": "111", "TELEGRAM_STOCK_NEWS_THREAD_ID": "112",
             "TELEGRAM_SIGNALS_THREAD_ID": "211", "TELEGRAM_TRADES_THREAD_ID": "212",
             "TELEGRAM_PORTFOLIO_THREAD_ID": "303"},
            {"getChat": {"type": "supergroup", "is_forum": True}, "getMe": {"id": 7},
             "getChatMember": {"status": "administrator", "can_manage_topics": True},
             "editForumTopic": {"__error__": "Bad Request: TOPIC_NOT_MODIFIED"}},
        )
        self.assertEqual(code, 0)
        self.assertFalse(any(call.args[0].endswith("/createForumTopic") for call in session.post.call_args_list))

    def test_write_env_removes_secret_temporary_file_after_success(self):
        self.env.write_text("TELEGRAM_BOT_TOKEN=secret\nUNCHANGED=yes\n", encoding="utf-8")
        temporary = self.env.with_name(f"{self.env.name}.topics.tmp")
        real_chmod = os.chmod
        with patch.object(topics_setup, "ENV_FILE", self.env), \
             patch.object(topics_setup.os, "chmod", wraps=real_chmod) as chmod:
            topics_setup._write_env({"TELEGRAM_CHAT_ID": "-1001"})
        self.assertIn("TELEGRAM_BOT_TOKEN=secret", self.env.read_text(encoding="utf-8"))
        self.assertFalse(temporary.exists())
        mode = topics_setup.stat.S_IRUSR | topics_setup.stat.S_IWUSR
        chmod.assert_any_call(temporary, mode)
        chmod.assert_any_call(self.env, mode)

    def test_write_env_cleans_secret_temporary_file_when_replace_fails(self):
        original = "TELEGRAM_BOT_TOKEN=secret\n"
        self.env.write_text(original, encoding="utf-8")
        temporary = self.env.with_name(f"{self.env.name}.topics.tmp")
        with patch.object(topics_setup, "ENV_FILE", self.env), \
             patch.object(topics_setup.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                topics_setup._write_env({"TELEGRAM_CHAT_ID": "-1001"})
        self.assertEqual(self.env.read_text(encoding="utf-8"), original)
        self.assertFalse(temporary.exists())

    def test_network_error_does_not_expose_bot_token(self):
        session = Mock()
        session.post.side_effect = requests.Timeout(
            "request failed for https://api.telegram.org/botSUPER-SECRET/getChat"
        )
        with self.assertRaises(RuntimeError) as caught:
            topics_setup._request_json(
                session, "https://api.telegram.org/botSUPER-SECRET", "getChat", {}
            )
        self.assertNotIn("SUPER-SECRET", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_invalid_json_is_reported_without_response_body(self):
        session = Mock()
        response_value = Mock(ok=False, status_code=502)
        response_value.json.side_effect = ValueError("body contained SUPER-SECRET")
        session.post.return_value = response_value
        with self.assertRaises(RuntimeError) as caught:
            topics_setup._request_json(
                session, "https://api.telegram.org/botSUPER-SECRET", "getChat", {}
            )
        self.assertEqual(
            str(caught.exception), "Telegram getChat returned invalid JSON (HTTP 502)"
        )


if __name__ == "__main__":
    unittest.main()
