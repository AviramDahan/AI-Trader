"""Topic provisioning tests never call Telegram or modify a real .env."""
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import configure_sec_intelligence_topic as setup  # noqa: E402


def test_sec_topic_created_once_and_only_dedicated_setting_written(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=test\nTELEGRAM_CHAT_ID=-1001\n", encoding="utf-8")
    monkeypatch.setattr(setup, "ENV_FILE", env)
    monkeypatch.setattr(setup.requests, "Session", lambda: SimpleNamespace(trust_env=True))
    calls, writes = [], []

    def fake_request(_session, _base, method, _data):
        calls.append(method)
        result = {"getChat": {"type": "supergroup", "is_forum": True},
                  "getMe": {"id": 5},
                  "getChatMember": {"status": "administrator", "can_manage_topics": True},
                  "createForumTopic": {"message_thread_id": 345}}[method]
        return SimpleNamespace(ok=True), {"ok": True, "result": result}

    monkeypatch.setattr(setup, "_request_json", fake_request)
    monkeypatch.setattr(setup, "_write_env", lambda update: writes.append(update))
    assert setup.main() == 0
    assert calls == ["getChat", "getMe", "getChatMember", "createForumTopic"]
    assert writes == [{"TELEGRAM_SEC_INTELLIGENCE_THREAD_ID": "345"}]


def test_sec_topic_existing_id_is_verified_not_recreated(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=test\nTELEGRAM_CHAT_ID=-1001\n"
                   "TELEGRAM_SEC_INTELLIGENCE_THREAD_ID=345\n", encoding="utf-8")
    monkeypatch.setattr(setup, "ENV_FILE", env)
    monkeypatch.setattr(setup.requests, "Session", lambda: SimpleNamespace(trust_env=True))
    calls = []

    def fake_request(_session, _base, method, _data):
        calls.append(method)
        result = {"getChat": {"type": "supergroup", "is_forum": True},
                  "getMe": {"id": 5},
                  "getChatMember": {"status": "administrator", "can_manage_topics": True},
                  "editForumTopic": True}[method]
        return SimpleNamespace(ok=True), {"ok": True, "result": result}

    monkeypatch.setattr(setup, "_request_json", fake_request)
    monkeypatch.setattr(setup, "_write_env", lambda _update: pytest.fail("unexpected env write"))
    assert setup.main() == 0
    assert calls == ["getChat", "getMe", "getChatMember", "editForumTopic"]
