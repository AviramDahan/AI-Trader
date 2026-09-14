"""Verify the local Telegram destination and refresh the private credential backup.

The bot token is read only from the ignored root .env and is never printed.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone

import requests
from dotenv import dotenv_values

from bootstrap_private_setup import (
    ENCRYPTED_FILE,
    ENV_FILE,
    PRIVATE_FILE,
    _protect_for_current_windows_user,
    _restrict_permissions,
)


def _is_ignored(path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", str(path)],
        cwd=ENV_FILE.parent,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _telegram_call(token: str, method: str, data: dict | None = None) -> dict:
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.post(
            f"https://api.telegram.org/bot{token}/{method}",
            data=data or {},
            timeout=15,
        )
        payload = response.json()
        return payload if isinstance(payload, dict) else {"ok": False, "description": "Invalid response"}
    except Exception:
        # Exception text may contain the credential-bearing request URL.
        return {"ok": False, "description": "Telegram request failed"}


def main() -> None:
    if not all(_is_ignored(path) for path in (ENV_FILE, PRIVATE_FILE, ENCRYPTED_FILE)):
        raise RuntimeError("Private Telegram files are not all ignored by Git")

    values = dotenv_values(ENV_FILE)
    token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(values.get("TELEGRAM_CHAT_ID") or "").strip()
    enabled = all(str(values.get(key) or "").lower() == "true" for key in (
        "STOCK_SCANNER_TELEGRAM_ENABLED",
        "STOCK_SCANNER_TELEGRAM_ENTRY_ALERTS",
        "STOCK_SCANNER_TELEGRAM_LEVEL_ALERTS",
    ))
    if not token or not chat_id or not enabled:
        raise RuntimeError("Telegram environment is incomplete")

    bot = _telegram_call(token, "getMe")
    chat = _telegram_call(token, "getChat", {"chat_id": chat_id})
    test = _telegram_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": (
            "AI-Trader Telegram configuration test — PAPER TRADING ONLY. "
            "No trading signal was generated. "
            f"Verified {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}."
        ),
        "disable_web_page_preview": "true",
    })

    bot_result = bot.get("result") if isinstance(bot.get("result"), dict) else {}
    chat_result = chat.get("result") if isinstance(chat.get("result"), dict) else {}
    message_result = test.get("result") if isinstance(test.get("result"), dict) else {}
    username = str(bot_result.get("username") or "Telegram bot")
    chat_name = str(chat_result.get("title") or chat_result.get("username") or "configured group")

    original = PRIVATE_FILE.read_text(encoding="utf-8")
    begin, end = "--- BEGIN TELEGRAM ALERTS ---", "--- END TELEGRAM ALERTS ---"
    if begin in original and end in original:
        prefix, remainder = original.split(begin, 1)
        _, suffix = remainder.split(end, 1)
        original = prefix.rstrip() + suffix
    section = [
        begin,
        "Service: Telegram Bot alerts",
        "Purpose: AI-Trader PAPER signal and Entry/TP/SL notifications",
        "Website: https://telegram.org/",
        "Account email: N/A",
        f"Username: @{username}",
        "Password: N/A",
        f"API key: {token}",
        f"API secret/token: {token}",
        f"Account/project ID: {chat_id}",
        "Free plan/tier: Telegram Bot API / free",
        "Environment variable name: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, STOCK_SCANNER_TELEGRAM_ENABLED, STOCK_SCANNER_TELEGRAM_ENTRY_ALERTS, STOCK_SCANNER_TELEGRAM_LEVEL_ALERTS",
        "Where the secret is stored: Local ignored .env; this private backup; DPAPI-encrypted local backup",
        f"Date created: {date.today().isoformat()}",
        "Where it is used: Local stock scanner Telegram notification sender",
        f"Notes: Target group: {chat_name}; safe setup test message ID: {message_result.get('message_id', 'not delivered')}",
        end,
    ]
    PRIVATE_FILE.write_text(original.rstrip() + "\n\n" + "\n".join(section) + "\n", encoding="utf-8")
    for path in (ENV_FILE, PRIVATE_FILE):
        _restrict_permissions(path)
    encrypted = _protect_for_current_windows_user(PRIVATE_FILE.read_bytes())
    if encrypted:
        ENCRYPTED_FILE.write_bytes(encrypted)
        _restrict_permissions(ENCRYPTED_FILE)

    result = {
        "configured": enabled and bool(bot.get("ok")) and bool(chat.get("ok")),
        "test_delivered": bool(test.get("ok")),
        "error": "" if test.get("ok") else str(test.get("description") or "Telegram test failed"),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
