"""Delete and recreate the five managed Telegram Forum topics.

This is an explicit maintenance operation: deleting a Forum topic removes its
messages.  It preserves the chat, bot credentials and paper-trading database,
rotates only topic IDs, and prevents queued pre-reset messages from leaking
into the clean topics.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "service" / "server"
sys.path.insert(0, str(SERVER))

import database  # noqa: E402
from configure_telegram_topics import _record_backup, _write_env  # noqa: E402


TOPICS = (
    ("TELEGRAM_MARKET_NEWS_THREAD_ID", "📰 חדשות שוק", 16478047),
    ("TELEGRAM_STOCK_NEWS_THREAD_ID", "🏢 חדשות מניות", 7322096),
    ("TELEGRAM_SIGNALS_THREAD_ID", "📡 סיגנלים", 9367192),
    ("TELEGRAM_TRADES_THREAD_ID", "🔔 עסקאות דמו", 16766590),
    ("TELEGRAM_PORTFOLIO_THREAD_ID", "💼 מצב תיק דמו", 16766590),
)


def main() -> int:
    values = dotenv_values(ROOT / ".env")
    token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(values.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("Telegram credentials are missing from the ignored .env.")
        return 2

    session = requests.Session(); session.trust_env = False
    base = f"https://api.telegram.org/bot{token}"

    def call(method: str, data: dict, *, absent_ok: bool = False):
        response = session.post(f"{base}/{method}", data=data, timeout=20)
        payload = response.json()
        if response.ok and payload.get("ok"):
            return payload.get("result")
        description = str(payload.get("description") or f"HTTP {response.status_code}")
        absent = any(marker in description.lower() for marker in (
            "message thread not found", "topic_id_invalid", "message_thread_id_invalid",
        ))
        if absent_ok and absent:
            return None
        raise RuntimeError(f"Telegram {method} failed: {description}")

    me = call("getMe", {})
    chat = call("getChat", {"chat_id": chat_id})
    member = call("getChatMember", {"chat_id": chat_id, "user_id": me["id"]})
    if chat.get("type") != "supergroup" or not chat.get("is_forum"):
        raise RuntimeError("Configured Telegram chat is not a Forum supergroup")
    if member.get("status") not in {"administrator", "creator"} or not member.get("can_manage_topics", False):
        raise RuntimeError("Telegram bot cannot manage Forum topics")

    old_ids = []
    for key, _, _ in TOPICS:
        raw = str(values.get(key) or "").strip()
        if raw.isdigit() and int(raw) not in old_ids:
            old_ids.append(int(raw))
    for thread_id in old_ids:
        call("deleteForumTopic", {"chat_id": chat_id, "message_thread_id": thread_id}, absent_ok=True)

    updates: dict[str, str] = {"TELEGRAM_CHAT_ID": chat_id}
    for key, name, color in TOPICS:
        topic = call("createForumTopic", {"chat_id": chat_id, "name": name, "icon_color": color})
        updates[key] = str(topic["message_thread_id"])
    # Keep the legacy fallbacks aligned so an old event type cannot target a
    # deleted topic while all current event types use the explicit IDs above.
    updates["TELEGRAM_NEWS_THREAD_ID"] = updates["TELEGRAM_STOCK_NEWS_THREAD_ID"]
    updates["TELEGRAM_TRADING_THREAD_ID"] = updates["TELEGRAM_TRADES_THREAD_ID"]
    _write_env(updates)
    _record_backup(
        chat_id,
        updates["TELEGRAM_MARKET_NEWS_THREAD_ID"],
        updates["TELEGRAM_STOCK_NEWS_THREAD_ID"],
        updates["TELEGRAM_SIGNALS_THREAD_ID"],
        updates["TELEGRAM_TRADES_THREAD_ID"],
        updates["TELEGRAM_PORTFOLIO_THREAD_ID"],
    )

    database.init_database()
    conn = database.get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM scanner_telegram_topic_state")
    cur.execute("""UPDATE scanner_telegram_outbox
                   SET status='disabled',last_error='user_requested_topic_reset'
                   WHERE status IN ('pending','retry')""")
    discarded = cur.rowcount
    conn.commit(); conn.close()
    try:
        os.chmod(ROOT / ".env", 0o600)
    except OSError:
        pass
    print(f"Recreated {len(TOPICS)} clean Telegram topics; discarded queued stale messages: {discarded}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
