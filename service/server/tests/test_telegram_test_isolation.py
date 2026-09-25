import os

import pytest
import requests


def test_local_telegram_credentials_are_not_inherited():
    assert not os.getenv("TELEGRAM_BOT_TOKEN")
    assert not os.getenv("TELEGRAM_CHAT_ID")


def test_live_telegram_is_blocked_even_if_credentials_are_reloaded(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-test-token")
    with pytest.raises(RuntimeError, match="blocked in unit tests"):
        requests.post("https://api.telegram.org/botdummy-test-token/sendMessage", data={"text": "must not send"})
