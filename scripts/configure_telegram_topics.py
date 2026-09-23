"""Create and persist separate Telegram Forum topics after the group owner enables Topics."""

from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
CREDENTIALS_FILE = ROOT / "PRIVATE_SETUP_CREDENTIALS.txt"


def _write_env(updates: dict[str, str]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    pending = dict(updates)
    output = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in pending:
            output.append(f"{key}={pending.pop(key)}")
        else:
            output.append(line)
    if pending and output and output[-1]:
        output.append("")
    output.extend(f"{key}={value}" for key, value in pending.items())
    temporary = ENV_FILE.with_suffix(".topics.tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    temporary.replace(ENV_FILE)


def _record_backup(chat_id: str, news_thread: str, trading_thread: str, portfolio_thread: str) -> None:
    if not CREDENTIALS_FILE.exists():
        return
    begin, end = "--- BEGIN TELEGRAM TOPICS ---", "--- END TELEGRAM TOPICS ---"
    block = "\n".join([
        begin,
        "Service: Telegram Forum topics",
        "Purpose: Separate AI-Trader news from paper-trading lifecycle alerts",
        "Website: https://web.telegram.org/",
        "Account email: N/A",
        "Username: Existing configured bot",
        "Password: N/A",
        "API key: Stored separately as TELEGRAM_BOT_TOKEN; value intentionally not duplicated here",
        "API secret/token: Stored in ignored .env",
        f"Account/project ID: chat={chat_id}; news_thread={news_thread}; trading_thread={trading_thread}; portfolio_thread={portfolio_thread}",
        "Free plan/tier: Telegram Bot API",
        "Environment variable name: TELEGRAM_CHAT_ID, TELEGRAM_NEWS_THREAD_ID, TELEGRAM_TRADING_THREAD_ID, TELEGRAM_PORTFOLIO_THREAD_ID",
        "Where the secret is stored: Project-root ignored .env",
        f"Date created: {datetime.now(timezone.utc).date().isoformat()}",
        "Where it is used: Server-side Telegram message and entry-chart delivery",
        "Notes: News routes to חדשות; signals, entries, TP/SL and SELL route to סיגנלים ועסקאות דמו; the edited paper-account card routes to מצב תיק דמו.",
        end,
    ])
    text = CREDENTIALS_FILE.read_text(encoding="utf-8")
    start, finish = text.find(begin), text.find(end)
    if start >= 0 and finish >= start:
        text = text[:start] + block + text[finish + len(end):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    CREDENTIALS_FILE.write_text(text, encoding="utf-8")
    try:
        os.chmod(CREDENTIALS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def main() -> int:
    values = dotenv_values(ENV_FILE)
    token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(values.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("Telegram credentials are missing from the ignored .env.")
        return 2
    session = requests.Session()
    session.trust_env = False
    base = f"https://api.telegram.org/bot{token}"

    def call(method: str, data: dict | None = None) -> dict:
        response = session.post(f"{base}/{method}", data=data or {}, timeout=20)
        payload = response.json()
        if response.ok and payload.get("ok"):
            return payload["result"]
        raise RuntimeError(str(payload.get("description") or method))

    try:
        chat = call("getChat", {"chat_id": chat_id})
    except RuntimeError as exc:
        # Telegram can return the replacement ID after a basic group is upgraded.
        response = session.post(f"{base}/getChat", data={"chat_id": chat_id}, timeout=20).json()
        migrated = response.get("parameters", {}).get("migrate_to_chat_id")
        if not migrated:
            print(f"Could not read the configured Telegram chat: {exc}")
            return 2
        chat_id = str(migrated)
        _write_env({"TELEGRAM_CHAT_ID": chat_id})
        chat = call("getChat", {"chat_id": chat_id})
    if chat.get("type") != "supergroup" or not chat.get("is_forum"):
        # A successful getChat on the old basic group may coexist briefly with
        # the service migration update. Resolve the new Bot API chat ID without
        # asking the user to copy internal identifiers.
        updates = call("getUpdates", {"limit": 100, "timeout": 0})
        migrated = next((item.get("message", {}).get("migrate_to_chat_id") for item in reversed(updates)
                         if str(item.get("message", {}).get("chat", {}).get("id")) == chat_id
                         and item.get("message", {}).get("migrate_to_chat_id")), None)
        if migrated:
            chat_id = str(migrated)
            _write_env({"TELEGRAM_CHAT_ID": chat_id})
            chat = call("getChat", {"chat_id": chat_id})
    if chat.get("type") != "supergroup" or not chat.get("is_forum"):
        print("BLOCKED: enable Topics in the Telegram group first; it must become a forum supergroup.")
        return 3
    me = call("getMe")
    member = call("getChatMember", {"chat_id": chat_id, "user_id": me["id"]})
    if member.get("status") not in {"administrator", "creator"} or not member.get("can_manage_topics", False):
        print("BLOCKED: promote the bot and grant Manage Topics, then run this script again.")
        return 4

    news_thread = str(values.get("TELEGRAM_NEWS_THREAD_ID") or "").strip()
    trading_thread = str(values.get("TELEGRAM_TRADING_THREAD_ID") or "").strip()
    portfolio_thread = str(values.get("TELEGRAM_PORTFOLIO_THREAD_ID") or "").strip()
    updates = {"TELEGRAM_CHAT_ID": chat_id}
    if not news_thread.isdigit():
        topic = call("createForumTopic", {"chat_id": chat_id, "name": "📰 חדשות", "icon_color": 7322096})
        news_thread = str(topic["message_thread_id"])
        updates["TELEGRAM_NEWS_THREAD_ID"] = news_thread
        _write_env(updates)
    if not trading_thread.isdigit():
        topic = call("createForumTopic", {"chat_id": chat_id, "name": "📈 סיגנלים ועסקאות דמו", "icon_color": 9367192})
        trading_thread = str(topic["message_thread_id"])
        updates["TELEGRAM_TRADING_THREAD_ID"] = trading_thread
        _write_env(updates)
    if not portfolio_thread.isdigit():
        topic = call("createForumTopic", {"chat_id": chat_id, "name": "💼 מצב תיק דמו", "icon_color": 16766590})
        portfolio_thread = str(topic["message_thread_id"])
        updates["TELEGRAM_PORTFOLIO_THREAD_ID"] = portfolio_thread
    _write_env(updates)
    _record_backup(chat_id, news_thread, trading_thread, portfolio_thread)
    print("Telegram topic routing configured in the ignored .env. Restart AI-Trader to activate it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
