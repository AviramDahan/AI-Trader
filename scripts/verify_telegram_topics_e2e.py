"""Live, non-trading E2E verification for the configured Telegram Forum topics.

The script sends one clearly labelled diagnostic message to every configured
topic, verifies Telegram's response, and deletes the diagnostic messages. It
never creates a signal, fill, order, trade, news item, or outbox event.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "service" / "server"
RUNTIME = ROOT / ".runtime"
sys.path.insert(0, str(SERVER))

# The ignored local file is authoritative for this local deployment. This also
# prevents stale inherited Windows variables from targeting an old chat.
LOCAL_VALUES = dotenv_values(ROOT / ".env")
KNOWN_TELEGRAM_KEYS = {
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_NEWS_THREAD_ID",
    "TELEGRAM_TRADING_THREAD_ID", "TELEGRAM_MARKET_NEWS_THREAD_ID",
    "TELEGRAM_STOCK_NEWS_THREAD_ID", "TELEGRAM_SIGNALS_THREAD_ID",
    "TELEGRAM_TRADES_THREAD_ID", "TELEGRAM_PORTFOLIO_THREAD_ID",
}
for key in KNOWN_TELEGRAM_KEYS:
    os.environ.pop(key, None)
for key, value in LOCAL_VALUES.items():
    if value is not None:
        os.environ[key] = str(value)

import database  # noqa: E402
from telegram_status import (  # noqa: E402
    market_news_status_message,
    news_scope_status_message,
    portfolio_status_message,
    refresh_telegram_status_cards,
    signals_status_messages,
)
from telegram_topics import destination_fields, thread_id_for_event  # noqa: E402


TOPICS = (
    ("market_news", "חדשות שוק"),
    ("stock_news", "חדשות מניות"),
    ("signals_status", "סיגנלים"),
    ("entry", "עסקאות דמו"),
    ("portfolio_status", "מצב תיק דמו"),
)


def _sleep_retry_after(retry_after: int) -> None:
    """Honor the full server delay without one blocking sleep longer than 60s."""
    remaining = max(0, int(retry_after)) + 1
    while remaining > 0:
        pause = min(remaining, 60)
        time.sleep(pause)
        remaining -= pause


def _telegram_call(session: requests.Session, base: str, method: str, data: dict) -> dict:
    for attempt in range(3):
        response = session.post(f"{base}/{method}", data=data, timeout=20)
        payload = response.json()
        if response.ok and payload.get("ok"):
            return payload
        retry_after = int((payload.get("parameters") or {}).get("retry_after") or 0)
        if response.status_code == 429 and retry_after > 0 and attempt < 2:
            _sleep_retry_after(retry_after)
            continue
        raise RuntimeError(f"Telegram {method} failed: {payload.get('description') or response.status_code}")
    raise RuntimeError(f"Telegram {method} exhausted retries")


def _refresh_status_with_retry() -> dict[str, str]:
    """Respect Telegram's topic-level flood control during a live E2E run."""
    for attempt in range(2):
        result = refresh_telegram_status_cards()
        if not any(value == "failed" for value in result.values()):
            return result
        if attempt == 0:
            conn = database.get_db_connection()
            errors = [str(row["last_error"] or "") for row in conn.execute(
                "SELECT last_error FROM scanner_telegram_topic_state WHERE last_error IS NOT NULL"
            ).fetchall()]
            conn.close()
            delays = [int(match.group(1)) for error in errors
                      if (match := re.search(r"retry after (\d+)", error, re.IGNORECASE))]
            _sleep_retry_after(max(delays) if delays else 5)
    raise AssertionError(f"Status refresh failed after retry: {result}")


def _live_snapshot() -> dict:
    conn = database.get_db_connection(); cur = conn.cursor()
    open_rows = [dict(row) for row in cur.execute(
        """SELECT ticker,company,legacy_position_id FROM scanner_trades
           WHERE status='open' AND is_shadow=0 ORDER BY ticker"""
    ).fetchall()]
    watchlist = [str(row["ticker"]) for row in cur.execute(
        "SELECT ticker FROM scanner_news_watchlist WHERE enabled=1 ORDER BY ticker"
    ).fetchall()]
    outbox_count = int(cur.execute("SELECT COUNT(*) FROM scanner_telegram_outbox").fetchone()[0])
    conn.close()
    return {
        "open_positions": len(open_rows),
        "open_tickers": [row["ticker"] for row in open_rows],
        "managed_positions": sum(row["legacy_position_id"] is None for row in open_rows),
        "legacy_positions": sum(row["legacy_position_id"] is not None for row in open_rows),
        "watchlist": watchlist,
        "outbox_count": outbox_count,
    }


def _protected_state() -> dict[str, dict[str, object]]:
    """Hash trading/news/outbox state; Telegram topic-state is intentionally excluded."""
    tables = (
        "scanner_accounts", "scanner_signals", "scanner_orders", "scanner_trades",
        "scanner_fills", "scanner_news", "scanner_news_watchlist", "scanner_telegram_outbox",
    )
    conn = database.get_db_connection(); cur = conn.cursor()
    state: dict[str, dict[str, object]] = {}
    for table in tables:
        rows = [dict(row) for row in cur.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()]
        encoded = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        state[table] = {"rows": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}
    conn.close()
    return state


def _write_artifact(payload: dict) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    target = RUNTIME / "telegram-e2e-latest.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def _diagnostics(snapshot: dict, marker: str) -> dict[str, str]:
    tickers = ", ".join(snapshot["open_tickers"]) or "אין"
    watched = ", ".join(snapshot["watchlist"]) or "הרשימה ריקה"
    return {
        "market_news": (
            f"🧪 {marker} — בדיקת E2E בלבד\n\n"
            "טופיק: חדשות שוק\n"
            "ניתוב: תקין אם הודעה זו מופיעה כאן בלבד.\n"
            "סינון פעיל: מקורות רשמיים, מהותיות גבוהה ורלוונטיות של 80% לפחות.\n\n"
            "זו אינה ידיעה, המלצה או סיגנל מסחר."
        ),
        "stock_news": (
            f"🧪 {marker} — בדיקת E2E בלבד\n\n"
            "טופיק: חדשות מניות\n"
            f"רשימת מעקב פעילה: {watched}\n"
            f"פוזיציות פתוחות למעקב חדשות: {tickers}\n\n"
            "לא נוצרה ידיעה, עסקה או התראה מהותית."
        ),
        "signals_status": (
            f"🧪 {marker} — בדיקת E2E בלבד\n\n"
            "טופיק: סיגנלים\n"
            f"פוזיציות ראשיות פתוחות במסד: {snapshot['open_positions']}\n"
            f"סימולים: {tickers}\n\n"
            "זו בדיקת ניתוב בלבד; לא נוצר סיגנל חדש."
        ),
        "entry": (
            f"🧪 {marker} — בדיקת E2E בלבד\n\n"
            "טופיק: עסקאות דמו\n"
            f"פוזיציות מנוהלות: {snapshot['managed_positions']} | Legacy: {snapshot['legacy_positions']}\n"
            "התראות כניסה, TP, שינוי סטופ ויציאה מנותבות לכאן.\n\n"
            "לא בוצעה כניסה, מכירה או פעולת מסחר במסגרת הבדיקה."
        ),
        "portfolio_status": (
            f"🧪 {marker} — בדיקת E2E בלבד\n\n"
            "טופיק: מצב תיק דמו\n"
            f"פוזיציות ראשיות פתוחות: {snapshot['open_positions']}\n"
            f"סימולים: {tickers}\n\n"
            "הבדיקה לא שינתה מזומן, פוזיציות או תוצאות."
        ),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram credentials are missing from the ignored .env")

    database.init_database()
    before = _live_snapshot()
    signal_pages = signals_status_messages()
    signal_count = sum(page.count("סימול:") for page in signal_pages)
    if signal_count != before["open_positions"]:
        raise AssertionError(f"Signals card count {signal_count} != database {before['open_positions']}")
    if before["open_positions"] and any("אין כרגע פוזיציות פתוחות" in page for page in signal_pages):
        raise AssertionError("Signals card falsely reports no open positions")
    # Validate all real card generators before touching Telegram.
    real_cards = {
        "market_news": market_news_status_message(),
        "stock_news": news_scope_status_message(),
        "signals_status": "\n".join(signal_pages),
        "portfolio_status": portfolio_status_message(),
    }
    if not all(real_cards.values()):
        raise AssertionError("One or more real status cards are empty")

    routes = {event: thread_id_for_event(event) for event, _ in TOPICS}
    if any(not value for value in routes.values()) or len(set(routes.values())) != len(TOPICS):
        raise AssertionError(f"Telegram topic routing is incomplete or not unique: {routes}")

    # Refresh real cards before the diagnostic burst so the E2E run does not
    # immediately compete with itself for Telegram's per-chat rate limit.
    status_refresh = _refresh_status_with_retry()
    protected_before = _protected_state()
    marker = "AI-Trader-E2E-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    diagnostics = _diagnostics(before, marker)
    session = requests.Session(); session.trust_env = False
    base = f"https://api.telegram.org/bot{token}"
    sent: list[dict] = []
    results: list[dict] = []
    delivery_error: Exception | None = None
    cleanup_errors: list[dict] = []
    try:
        me = _telegram_call(session, base, "getMe", {})["result"]
        chat = _telegram_call(session, base, "getChat", {"chat_id": chat_id})["result"]
        member = _telegram_call(session, base, "getChatMember", {
            "chat_id": chat_id, "user_id": me["id"],
        })["result"]
        if not chat.get("is_forum"):
            raise AssertionError("Configured Telegram chat is not a Forum")
        if member.get("status") not in {"administrator", "creator"}:
            raise AssertionError("Telegram bot is not an administrator")

        for event_type, label in TOPICS:
            text = diagnostics[event_type]
            payload = _telegram_call(session, base, "sendMessage", {
                **destination_fields(chat_id, event_type),
                "text": text,
                "disable_notification": True,
                "disable_web_page_preview": True,
            })["result"]
            sent.append(payload)
            observed_thread = int(payload.get("message_thread_id") or 0)
            content_ok = payload.get("text") == text and marker in str(payload.get("text") or "")
            route_ok = observed_thread == int(routes[event_type]) and bool(payload.get("is_topic_message"))
            results.append({
                "topic": label,
                "event_type": event_type,
                "expected_thread": int(routes[event_type]),
                "observed_thread": observed_thread,
                "route_ok": route_ok,
                "content_ok": content_ok,
                "message_id": int(payload["message_id"]),
            })
            if not route_ok or not content_ok:
                raise AssertionError(f"Telegram E2E mismatch for {label}")
    except Exception as exc:
        delivery_error = exc
    finally:
        for payload in sent:
            try:
                deleted = _telegram_call(session, base, "deleteMessage", {
                    "chat_id": chat_id, "message_id": payload["message_id"],
                })
                for result in results:
                    if result["message_id"] == int(payload["message_id"]):
                        result["deleted"] = bool(deleted.get("ok"))
            except Exception as exc:
                cleanup_errors.append({"message_id": int(payload["message_id"]), "error": type(exc).__name__})

    if delivery_error:
        raise delivery_error
    if cleanup_errors:
        raise AssertionError(f"Telegram diagnostic cleanup failed: {cleanup_errors}")

    after = _live_snapshot()
    protected_after = _protected_state()
    if protected_before != protected_after:
        changed = sorted(table for table in protected_before if protected_before[table] != protected_after[table])
        raise AssertionError(f"Telegram E2E changed protected database tables: {changed}")
    if before["open_positions"] != after["open_positions"] or before["open_tickers"] != after["open_tickers"]:
        raise AssertionError("Open-position snapshot changed during Telegram E2E")

    report = {
        "ok": True,
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "forum": True,
        "bot_admin": True,
        "open_positions": before["open_positions"],
        "signals_card_positions": signal_count,
        "topics": results,
        "status_refresh": status_refresh,
        "protected_tables": protected_after,
        "protected_database_unchanged": True,
        "telegram_topic_state_updated_as_expected": True,
        "diagnostics_cleaned": True,
    }
    _write_artifact(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
