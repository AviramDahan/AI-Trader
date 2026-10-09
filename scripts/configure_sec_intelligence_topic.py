"""Provision only the dedicated SEC Forum topic after an approved release.

No public message is sent. This script does not activate SEC intelligence.
"""
from __future__ import annotations

import requests
from dotenv import dotenv_values

from configure_telegram_topics import ENV_FILE, _request_json, _write_env


TOPIC_NAME = "📑 דיווחי SEC מהותיים"
THREAD_ENV = "TELEGRAM_SEC_INTELLIGENCE_THREAD_ID"


def main() -> int:
    values = dotenv_values(ENV_FILE)
    token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(values.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("BLOCKED: configured Telegram credentials are required.")
        return 2
    session = requests.Session()
    session.trust_env = False
    base = f"https://api.telegram.org/bot{token}"

    def call(method: str, data: dict | None = None):
        response, payload = _request_json(session, base, method, data)
        if response.ok and payload.get("ok"):
            return payload["result"]
        description = str(payload.get("description") or method)
        if method == "editForumTopic" and "not modified" in description.lower().replace("_", " "):
            return True
        raise RuntimeError(f"Telegram {method} failed: {description}")

    try:
        chat = call("getChat", {"chat_id": chat_id})
        if chat.get("type") != "supergroup" or not chat.get("is_forum"):
            print("BLOCKED: the configured Telegram group is not a Forum supergroup.")
            return 3
        me = call("getMe")
        member = call("getChatMember", {"chat_id": chat_id, "user_id": me["id"]})
        if member.get("status") not in {"administrator", "creator"} or not member.get("can_manage_topics"):
            print("BLOCKED: the bot needs Manage Topics permission.")
            return 4
        existing = str(values.get(THREAD_ENV) or "").strip()
        if existing.isdigit() and int(existing) > 0:
            call("editForumTopic", {"chat_id": chat_id, "message_thread_id": existing,
                                    "name": TOPIC_NAME})
            print("Existing SEC Forum topic verified; no duplicate created.")
            return 0
        topic = call("createForumTopic", {"chat_id": chat_id, "name": TOPIC_NAME,
                                          "icon_color": 7322096})
        thread = int(topic["message_thread_id"])
        if thread <= 0:
            raise ValueError("invalid_thread_id")
        _write_env({THREAD_ENV: str(thread)})
        print("SEC Forum topic created and configured; coordinated restart is required later.")
        return 0
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        print(f"BLOCKED: SEC Forum topic setup failed ({type(exc).__name__}).")
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
