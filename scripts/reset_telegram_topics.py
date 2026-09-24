"""Delete and recreate the five managed Telegram Forum topics.

This is an explicit maintenance operation: deleting a Forum topic removes its
messages.  It preserves the chat, bot credentials and paper-trading database,
rotates only topic IDs, and prevents queued pre-reset messages from leaking
into the clean topics.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
RECOVERY_FILE_NAME = "telegram-topic-reset-recovery.json"
MAX_TELEGRAM_ATTEMPTS = 3
MAX_RETRY_AFTER_SECONDS = 60.0


def _telegram_call(session: requests.Session, base: str, method: str, data: dict,
                   *, absent_ok: bool = False):
    """Call Telegram with bounded 429 retry and token-free exceptions."""
    for attempt in range(MAX_TELEGRAM_ATTEMPTS):
        try:
            response = session.post(f"{base}/{method}", data=data, timeout=20)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Telegram {method} request failed ({type(exc).__name__})"
            ) from None
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError(
                f"Telegram {method} returned invalid JSON (HTTP {response.status_code})"
            ) from None
        if not isinstance(payload, dict):
            raise RuntimeError(f"Telegram {method} returned an invalid response") from None
        if response.ok and payload.get("ok"):
            return payload.get("result")

        description = str(payload.get("description") or f"HTTP {response.status_code}")
        parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        retry_after = parameters.get("retry_after")
        if response.status_code == 429 and retry_after is not None and attempt + 1 < MAX_TELEGRAM_ATTEMPTS:
            try:
                delay = max(0.0, min(float(retry_after), MAX_RETRY_AFTER_SECONDS))
            except (TypeError, ValueError):
                delay = 1.0
            time.sleep(delay)
            continue
        absent = any(marker in description.lower() for marker in (
            "message thread not found", "topic_id_invalid", "message_thread_id_invalid",
        ))
        if absent_ok and absent:
            return None
        raise RuntimeError(f"Telegram {method} failed: {description}") from None
    raise RuntimeError(f"Telegram {method} failed after retry limit") from None


def _write_recovery_state(path: Path, chat_id: str, old_ids: list[int],
                          updates: dict[str, str], state: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "chat_id": chat_id,
        "old_thread_ids": old_ids,
        "new_thread_ids": {key: updates[key] for key, _, _ in TOPICS},
        "state": state,
    }
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(*, confirm_delete: bool = False) -> int:
    if not confirm_delete:
        print("Refusing destructive Telegram topic reset without --confirm-delete.")
        return 2
    values = dotenv_values(ROOT / ".env")
    token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(values.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("Telegram credentials are missing from the ignored .env.")
        return 2

    session = requests.Session(); session.trust_env = False
    base = f"https://api.telegram.org/bot{token}"

    def call(method: str, data: dict, *, absent_ok: bool = False):
        return _telegram_call(session, base, method, data, absent_ok=absent_ok)

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
    # Create every replacement first. Until routing is persisted, the old
    # topics remain intact and the running service can continue using them.
    updates: dict[str, str] = {"TELEGRAM_CHAT_ID": chat_id}
    for key, name, color in TOPICS:
        topic = call("createForumTopic", {"chat_id": chat_id, "name": name, "icon_color": color})
        updates[key] = str(topic["message_thread_id"])
    # Keep the legacy fallbacks aligned so an old event type cannot target a
    # deleted topic while all current event types use the explicit IDs above.
    updates["TELEGRAM_NEWS_THREAD_ID"] = updates["TELEGRAM_STOCK_NEWS_THREAD_ID"]
    updates["TELEGRAM_TRADING_THREAD_ID"] = updates["TELEGRAM_TRADES_THREAD_ID"]
    recovery_file = ROOT / ".runtime" / RECOVERY_FILE_NAME
    _write_recovery_state(
        recovery_file,
        chat_id,
        old_ids,
        updates,
        "replacement_topics_created_routing_pending",
    )
    _write_env(updates)
    _write_recovery_state(
        recovery_file,
        chat_id,
        old_ids,
        updates,
        "new_routing_persisted_old_topics_pending_deletion",
    )
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
    deletion_errors = []
    for thread_id in old_ids:
        try:
            call("deleteForumTopic", {"chat_id": chat_id, "message_thread_id": thread_id}, absent_ok=True)
        except RuntimeError as exc:
            deletion_errors.append(str(exc))
    if deletion_errors:
        print(
            "Replacement topics are active, but some old topics could not be deleted; "
            f"recovery state remains at {recovery_file}."
        )
        return 5
    recovery_file.unlink(missing_ok=True)
    print(f"Recreated {len(TOPICS)} clean Telegram topics; discarded queued stale messages: {discarded}.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-delete",
        action="store_true",
        help="confirm permanent deletion of messages in the five managed Telegram topics",
    )
    raise SystemExit(main(confirm_delete=parser.parse_args().confirm_delete))
