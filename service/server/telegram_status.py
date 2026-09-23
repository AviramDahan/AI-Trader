"""Pinned, server-maintained Telegram status cards for the paper scanner."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from database import get_db_connection
from telegram_topics import destination_fields, thread_id_for_event


UTC = timezone.utc
ISRAEL = ZoneInfo("Asia/Jerusalem")
LIFECYCLE_EVENTS = {"entry", "tp", "stop", "sell", "stop_change"}


def _now_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _pct(value: float) -> str:
    return f"{value:+.2f}%"


def _next_target(trade: dict, hit_indexes: set[int]) -> tuple[str, float]:
    if trade["strategy"] == "single":
        return "יעד תפעולי", float(trade["tp2"])
    for index in (1, 2, 3):
        if index not in hit_indexes:
            return f"TP{index}", float(trade[f"tp{index}"])
    return "היעד האחרון", float(trade["tp3"])


def portfolio_status_message() -> str:
    """Build a concise, auditable mark-to-market view of the paper account."""
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT id FROM agents WHERE name='us-stock-scanner'")
    agent = cur.fetchone()
    if not agent:
        conn.close()
        raise RuntimeError("scanner identity missing")
    agent_id = int(agent["id"])
    cur.execute("SELECT * FROM scanner_accounts WHERE agent_id=?", (agent_id,))
    account = dict(cur.fetchone())
    cur.execute("""SELECT * FROM scanner_trades
                   WHERE agent_id=? AND status='open' AND is_shadow=0 ORDER BY ticker""", (agent_id,))
    trades = [dict(row) for row in cur.fetchall()]
    quotes: dict[str, dict] = {}
    if trades:
        tickers = sorted({row["ticker"] for row in trades})
        placeholders = ",".join("?" for _ in tickers)
        cur.execute(f"SELECT ticker,price,as_of FROM scanner_quotes WHERE ticker IN ({placeholders})", tuple(tickers))
        quotes = {row["ticker"]: dict(row) for row in cur.fetchall()}
    for trade in trades:
        cur.execute("SELECT target_index FROM scanner_fills WHERE trade_id=? AND fill_type='tp'", (trade["id"],))
        trade["hit_indexes"] = {int(row["target_index"]) for row in cur.fetchall() if row["target_index"] is not None}
    conn.close()

    managed = [row for row in trades if row.get("legacy_position_id") is None]
    legacy = [row for row in trades if row.get("legacy_position_id") is not None]
    managed_value = sum(float(row["remaining_quantity"]) * float(quotes.get(row["ticker"], {}).get("price") or row["last_price"] or row["entry_price"])
                        for row in managed)
    equity = float(account["cash"]) + managed_value
    net = equity - float(account["initial_cash"])
    unrealized = sum(
        (float(quotes.get(row["ticker"], {}).get("price") or row["last_price"] or row["entry_price"])
         - float(row["entry_price"])) * float(row["remaining_quantity"])
        for row in managed
    )
    exposure = managed_value
    updated = datetime.now(ISRAEL).strftime("%d/%m/%Y %H:%M:%S")

    blocks = [
        "💼 מצב תיק דמו — AI-Trader",
        "⚠️ מסחר מדומה בלבד. אין כאן פקודות ברוקר או כסף אמיתי.",
        "\n".join((
            f"שווי חשבון מנוהל: {_money(equity)}",
            f"מזומן זמין: {_money(float(account['cash']))}",
            f"חשיפה פתוחה: {_money(exposure)}",
            f"רווח/הפסד כולל נטו: {_money(net)}",
            f"רווח/הפסד ממומש ברוטו: {_money(float(account.get('realized_pnl') or 0))}",
            f"רווח/הפסד לא ממומש: {_money(unrealized)}",
            f"עמלות שנרשמו: {_money(float(account.get('fees_paid') or 0))}",
        )),
        f"פוזיציות מנוהלות: {len(managed)} | פוזיציות Legacy מנוטרות בנפרד: {len(legacy)}",
    ]
    def position_lines(rows: list[dict]) -> list[str]:
        lines: list[str] = []
        for trade in rows:
            quote = quotes.get(trade["ticker"], {})
            current = float(quote.get("price") or trade.get("last_price") or trade["entry_price"])
            change = (current / float(trade["entry_price"]) - 1) * 100
            target_name, target = _next_target(trade, trade["hit_indexes"])
            lines.append(
                f"{trade['ticker']}\n"
                f"כמות: {float(trade['remaining_quantity']):.6g} | כניסה: ${float(trade['entry_price']):.2f}\n"
                f"מחיר נוכחי: ${current:.2f} ({_pct(change)})\n"
                f"סטופ: ${float(trade['current_stop']):.2f} | {target_name}: ${target:.2f}"
            )
        return lines

    managed_lines = position_lines(managed)
    blocks.append("פוזיציות מנוהלות בחשבון:\n\n" + ("\n\n".join(managed_lines) if managed_lines else "אין פוזיציות מנוהלות פתוחות."))
    if legacy:
        legacy_lines = position_lines(legacy)
        blocks.append("פוזיציות Legacy — מנוטרות אך אינן נכללות בשווי החשבון המנוהל:\n\n" + "\n\n".join(legacy_lines))
    blocks.append(f"עודכן: {updated} (שעון ישראל)\nהמחירים מגיעים מ־Yahoo ועשויים להיות מושהים.")
    return "\n\n".join(blocks)[:4096]


def news_scope_status_message() -> str:
    """Explain exactly which verified stock tickers can produce Telegram news."""
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT ticker,company FROM scanner_news_watchlist WHERE enabled=1 ORDER BY ticker")
    watched = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT DISTINCT ticker,company FROM scanner_trades WHERE status='open' AND is_shadow=0 ORDER BY ticker")
    positions = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT value_json FROM scanner_settings WHERE key='active_exit_strategy'")
    conn.close()
    try:
        minimum = float(os.getenv("STOCK_SCANNER_NEWS_ALERT_MIN_RELEVANCE", ".65"))
    except ValueError:
        minimum = .65
    watched_text = ", ".join(f"{row['ticker']} ({row['company']})" if row["company"] != row["ticker"] else row["ticker"] for row in watched) or "הרשימה ריקה"
    positions_text = ", ".join(row["ticker"] for row in positions) or "אין"
    updated = datetime.now(ISRAEL).strftime("%d/%m/%Y %H:%M:%S")
    return "\n\n".join((
        "📰 חדשות חשובות — היקף המעקב",
        "המעקב העצמאי אינו תלוי בפוזיציות. אפשר להוסיף או להסיר מניות ברשימת המעקב בדשבורד.",
        f"מניות במעקב חדשות עצמאי:\n{watched_text}",
        f"פוזיציות שמנוטרות בנוסף:\n{positions_text}",
        ("Telegram מקבל ידיעה רק כאשר הטיקר אומת מול המקור, הרלוונטיות היא לפחות "
         f"{minimum:.0%}, והמהותיות בינונית או גבוהה. ידיעה כללית או שיוך לא ודאי לא יישלחו."),
        "בכל התראה יוצגו הסימול, שם החברה, המפרסם, זמן הפרסום, הקישור והפרדה בין עובדות המקור לפרשנות AI.",
        f"עודכן: {updated} (שעון ישראל)",
    ))[:4096]


def _call(session: requests.Session, base: str, method: str, data: dict) -> tuple[bool, dict, str]:
    try:
        response = session.post(f"{base}/{method}", data=data, timeout=20)
        payload = response.json()
        if response.ok and payload.get("ok"):
            return True, payload, ""
        description = str(payload.get("description") or f"HTTP {response.status_code}")
        if "message is not modified" in description.lower():
            return True, payload, ""
        return False, payload, description[:300]
    except Exception as exc:
        return False, {}, type(exc).__name__


def _upsert_pinned_message(state_key: str, event_type: str, text: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    thread_id = thread_id_for_event(event_type)
    stamp = _now_z()
    if not token or not chat_id or not thread_id:
        return "missing_configuration"
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM scanner_telegram_topic_state WHERE state_key=?", (state_key,))
    prior = cur.fetchone()
    prior = dict(prior) if prior else None
    message_id = int(prior["message_id"]) if prior and prior.get("message_id") else None
    conn.close()
    session = requests.Session(); session.trust_env = False
    base = f"https://api.telegram.org/bot{token}"
    fields = destination_fields(chat_id, event_type)
    error = ""
    allow_recreate = message_id is None
    if message_id:
        ok, _, error = _call(session, base, "editMessageText", {**fields, "message_id": message_id,
                                                                  "text": text,
                                                                  "disable_web_page_preview": True})
        if ok:
            result = "updated"
        else:
            missing = any(marker in error.lower() for marker in (
                "message to edit not found", "message_id_invalid", "message identifier is not specified",
            ))
            if missing:
                message_id = None
                allow_recreate = True
            else:
                result = "failed"
    if not message_id and allow_recreate:
        ok, payload, error = _call(session, base, "sendMessage", {**fields, "text": text,
                                                                    "disable_web_page_preview": True})
        if ok:
            message_id = int(payload["result"]["message_id"])
            result = "created"
        else:
            result = "failed"
    if result in {"created", "updated"} and message_id:
        pinned, _, pin_error = _call(session, base, "pinChatMessage", {
            "chat_id": chat_id, "message_id": message_id, "disable_notification": True,
        })
        if not pinned:
            result, error = "failed", f"pin:{pin_error}"[:300]
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""INSERT INTO scanner_telegram_topic_state
        (state_key,chat_id,thread_id,message_id,content_hash,last_attempt_at,last_success_at,last_error)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(state_key) DO UPDATE SET chat_id=excluded.chat_id,thread_id=excluded.thread_id,
        message_id=COALESCE(excluded.message_id,scanner_telegram_topic_state.message_id),
        content_hash=excluded.content_hash,last_attempt_at=excluded.last_attempt_at,
        last_success_at=CASE WHEN excluded.last_error IS NULL THEN excluded.last_success_at ELSE scanner_telegram_topic_state.last_success_at END,
        last_error=excluded.last_error""",
        (state_key, chat_id, thread_id, message_id, content_hash, stamp, stamp if result != "failed" else None,
         None if result != "failed" else error))
    conn.commit(); conn.close()
    return result


def refresh_telegram_status_cards() -> dict[str, str]:
    enabled = os.getenv("STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"portfolio": "disabled", "news_scope": "disabled"}
    return {
        "portfolio": _upsert_pinned_message("portfolio", "portfolio_status", portfolio_status_message()),
        "news_scope": _upsert_pinned_message("news_scope", "news_status", news_scope_status_message()),
    }
