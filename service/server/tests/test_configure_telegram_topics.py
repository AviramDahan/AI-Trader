import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "configure_telegram_topics.py"
SPEC = importlib.util.spec_from_file_location("configure_telegram_topics", SCRIPT)
topics_setup = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(topics_setup)


def response(result):
    value = Mock(ok=True)
    value.json.return_value = {"ok": True, "result": result}
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
             "TELEGRAM_NEWS_THREAD_ID": "101", "TELEGRAM_TRADING_THREAD_ID": "202"},
            {"getChat": {"type": "supergroup", "is_forum": True},
             "getMe": {"id": 7},
             "getChatMember": {"status": "administrator", "can_manage_topics": True}},
        )
        self.assertEqual(code, 0)
        self.assertFalse(any(call.args[0].endswith("/createForumTopic") for call in session.post.call_args_list))


if __name__ == "__main__":
    unittest.main()
