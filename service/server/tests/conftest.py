"""Unit tests must never contact the live Telegram bot, even with a local .env."""
from urllib.parse import urlsplit

import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_telegram(monkeypatch):
    # config.py may have loaded the developer's .env during module collection.
    # Tests that exercise routing install their own dummy values and mocks.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED", "false")
    original = requests.sessions.Session.request

    def guarded_request(session, method, url, *args, **kwargs):
        if urlsplit(str(url)).hostname == "api.telegram.org":
            raise RuntimeError("Live Telegram network access is blocked in unit tests")
        return original(session, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", guarded_request)
