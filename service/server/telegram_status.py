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
SCANNER_KEY = "us-stock-scanner"
SCANNER_DISPLAY_NAME_HE = "סיגנלים פעילים"


def _now_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _pct(value: float) -> str:
    return f"{value:+.2f}%"


def _account_pct(value: float) -> str:
    if value != 0 and abs(value) < .0001:
        return ('שלילית' if value < 0 else 'חיובית') + ' — פחות מ־0.0001%'
    return f"{value:+.4f}%"


def _ltr(value: object) -> str:
    """Keep Latin symbols/numbers stable inside Telegram Hebrew RTL text."""
    return f"\u2066{value}\u2069"


def _rtl(value: str) -> str:
    return "\u200f" + value


def _scanner_agent_id(cur) -> int:
    cur.execute("SELECT id FROM agents WHERE name=?", (SCANNER_KEY,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError("scanner identity missing")
    return int(row["id"])


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
    agent_id = _scanner_agent_id(cur)
    cur.execute("SELECT * FROM scanner_accounts WHERE agent_id=?", (agent_id,))
    account = dict(cur.fetchone())
    cur.execute("""SELECT ticker,realized_pnl,fees,entry_price,original_quantity,outcome FROM scanner_trades
        WHERE agent_id=? AND status='closed' AND is_shadow=0 AND legacy_position_id IS NULL
        ORDER BY closed_at DESC,id DESC LIMIT 3""", (agent_id,))
    recent_closed = [dict(row) for row in cur.fetchall()]
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
    updated = datetime.now(ISRAEL).strftime("%d/%m/%Y %H:%M:%S")

    blocks = [
        f"💼 תיק דמו ראשי — {SCANNER_DISPLAY_NAME_HE}",
        "⚠️ מסחר מדומה בלבד. אין כאן פקודות ברוקר או כסף אמיתי.",
        f"תשואת החשבון המאומת נטו: {_ltr(_account_pct(net / float(account['initial_cash']) * 100)) if float(account['initial_cash']) > 0 else 'לא זמינה'}",
        "כוללת רווח/הפסד סגור ופתוח ועמלות, ביחס לכל ההון ההתחלתי — כולל המזומן.",
        f"סה״כ פוזיציות בתיק הראשי: {len(trades)} | מאומתות חשבונאית: {len(managed)} | Legacy: {len(legacy)}",
    ]
    def position_lines(rows: list[dict], start: int = 1) -> list[str]:
        lines: list[str] = []
        for number, trade in enumerate(rows, start):
            quote = quotes.get(trade["ticker"], {})
            current = float(quote.get("price") or trade.get("last_price") or trade["entry_price"])
            change = (current / float(trade["entry_price"]) - 1) * 100
            target_name, target = _next_target(trade, trade["hit_indexes"])
            target_change = (target / float(trade['entry_price']) - 1) * 100
            stop_change = (float(trade['current_stop']) / float(trade['entry_price']) - 1) * 100
            lines.append(
                f"{number}. {trade['ticker']}\n"
                f"שינוי מהכניסה: {_ltr(_pct(change))}\n"
                f"סטופ: {_ltr(_pct(stop_change))} | {target_name}: {_ltr(_pct(target_change))}\n"
                "היעד והסטופ באחוזים ביחס למחיר הכניסה."
            )
        return lines

    managed_lines = position_lines(managed)
    blocks.append("פוזיציות מאומתות בתיק הראשי:\n\n" + ("\n\n".join(managed_lines) if managed_lines else "אין פוזיציות מאומתות פתוחות."))
    if legacy:
        legacy_lines = position_lines(legacy, len(managed) + 1)
        blocks.append("פוזיציות Legacy — מנוטרות, אך אינן נכללות בתשואה המאומתת:\n\n" + "\n\n".join(legacy_lines))
    if recent_closed:
        closed_lines = []
        for trade in recent_closed:
            cost = float(trade['entry_price']) * float(trade['original_quantity'])
            percent = (float(trade['realized_pnl']) - float(trade['fees'])) / cost * 100 if cost > 0 else None
            closed_lines.append(f"{trade['ticker']}: {_ltr(_pct(percent)) if percent is not None else 'לא זמין'}")
        blocks.append('עסקאות מאומתות שנסגרו לאחרונה — נטו ביחס לעלות הכניסה:\n' + '\n'.join(closed_lines))
    blocks.append(f"עודכן: {updated} (שעון ישראל)\nהמחירים מגיעים מ־Yahoo ועשויים להיות מושהים.")
    return "\n\n".join(blocks)[:4096]


def news_scope_status_message() -> str:
    """Explain the independent, anti-spam stock-news coverage."""
    conn = get_db_connection(); cur = conn.cursor()
    agent_id = _scanner_agent_id(cur)
    cur.execute("SELECT ticker,company FROM scanner_news_watchlist WHERE enabled=1 ORDER BY ticker")
    watched = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT DISTINCT ticker,company FROM scanner_trades WHERE agent_id=? AND status='open' AND is_shadow=0 ORDER BY ticker", (agent_id,))
    positions = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT DISTINCT ticker FROM scanner_signals WHERE agent_id=? AND status IN ('ACTIVE','PENDING_ENTRY','ENTERED') ORDER BY ticker", (agent_id,))
    active_signals = [str(row["ticker"]) for row in cur.fetchall()]
    cur.execute("SELECT COUNT(DISTINCT ticker) count FROM scanner_candidates WHERE status='candidate'")
    candidate_count = int(cur.fetchone()["count"])
    conn.close()
    try:
        minimum = float(os.getenv("STOCK_SCANNER_NEWS_ALERT_MIN_RELEVANCE", ".65"))
    except ValueError:
        minimum = .65
    watched_text = ", ".join(f"{row['ticker']} ({row['company']})" if row["company"] != row["ticker"] else row["ticker"] for row in watched) or "הרשימה ריקה"
    positions_text = ", ".join(row["ticker"] for row in positions) or "אין"
    signals_text = ", ".join(active_signals) or "אין"
    try:
        broad_minimum = max(.80, min(1.0, float(os.getenv("STOCK_SCANNER_TELEGRAM_BROAD_NEWS_MIN_RELEVANCE", ".80"))))
    except ValueError:
        broad_minimum = .80
    updated = datetime.now(ISRAEL).strftime("%d/%m/%Y %H:%M:%S")
    return "\n\n".join((
        "🏢 חדשות מניות — היקף המעקב",
        "הטופיק אינו מוגבל לפוזיציות. הוא מכסה רשימת מעקב, סיגנלים פעילים ומועמדים מתחלפים מהסורק.",
        f"רשימת מעקב קבועה:\n{watched_text}",
        f"פוזיציות פתוחות:\n{positions_text}",
        f"סיגנלים פעילים:\n{signals_text}",
        f"מועמדי סורק זמינים למעקב מתחלף: {candidate_count}",
        ("ללא ספאם: חדשות watchlist/פוזיציות דורשות רלוונטיות של לפחות "
         f"{minimum:.0%}; חדשות משאר מועמדי הסורק דורשות מהותיות גבוהה וסף מחמיר של {broad_minimum:.0%}. "
         "אין מכסה לפי מניה: כל אירוע חדש ומהותי נשלח, ואותו אירוע/גרסה לא נשלחים פעמיים."),
        "בכל התראה יוצגו הסימול, שם החברה, המפרסם, זמן הפרסום, הקישור והפרדה בין עובדות המקור לפרשנות AI.",
        f"עודכן: {updated} (שעון ישראל)",
    ))[:4096]


def market_news_status_message() -> str:
    try:
        relevance = max(.80, min(1.0, float(os.getenv("STOCK_SCANNER_TELEGRAM_BROAD_NEWS_MIN_RELEVANCE", ".80"))))
    except ValueError:
        relevance = .80
    updated = datetime.now(ISRAEL).strftime("%d/%m/%Y %H:%M:%S")
    return "\n\n".join((
        "📰 חדשות שוק — סינון מחמיר",
        "כאן נשלחים רק אירועי מאקרו מהותיים ממקורות רשמיים כגון Federal Reserve ו־BLS.",
        (f"מניעת ספאם: מהותיות גבוהה, רלוונטיות של לפחות {relevance:.0%}, מקור רשמי ומניעת כפילות. "
         "אין מכסה קשיחה שעלולה להסתיר אירוע חשוב מאוחר יותר."),
        "חדשות שוק אחרות נשארות בדשבורד ואינן נשלחות אוטומטית ל־Telegram.",
        "המידע אינו סיגנל מסחר ואינו יוצר עסקה.",
        f"עודכן: {updated} (שעון ישראל)",
    ))


def signals_status_messages() -> list[str]:
    """List every open primary paper position, paginating before Telegram's limit."""
    conn = get_db_connection(); cur = conn.cursor()
    agent_id = _scanner_agent_id(cur)
    cur.execute("""SELECT t.*,s.confidence,s.time_horizon
        FROM scanner_trades t JOIN scanner_signals s ON s.id=t.signal_id
        WHERE t.agent_id=? AND t.status='open' AND t.is_shadow=0 ORDER BY t.opened_at DESC,t.ticker""", (agent_id,))
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
    lines: list[str] = []
    horizon_he = {
        "intraday": "תוך־יומי",
        "1-5 days": "1–5 ימים",
        "1-5 trading days": "1–5 ימי מסחר",
        "1-4 weeks": "1–4 שבועות",
        "1-3 months": "1–3 חודשים",
    }
    for trade in trades:
        current = float(quotes.get(trade["ticker"], {}).get("price") or trade.get("last_price") or trade["entry_price"])
        _, target = _next_target(trade, trade.get("hit_indexes", set()))
        legacy = " (Legacy)" if trade.get("legacy_position_id") is not None else ""
        confidence = float(trade.get("confidence") or 0)
        raw_horizon = str(trade.get("time_horizon") or "לא זמין")
        horizon = horizon_he.get(raw_horizon.lower(), raw_horizon)
        entry_text = f"${float(trade['entry_price']):.2f}"
        current_text = f"${current:.2f}"
        stop_text = f"${float(trade['current_stop']):.2f}"
        target_text = f"${target:.2f}"
        confidence_text = f"{confidence:.0%}"
        lines.append(
            "\n".join((
                _rtl(f"סימול: {_ltr(trade['ticker'])}{legacy}"),
                _rtl(f"חברה: {_ltr(trade['company'])}"),
                _rtl("פעולה: קנייה"),
                _rtl(f"כניסה: {_ltr(entry_text)}"),
                _rtl(f"מחיר נוכחי: {_ltr(current_text)}"),
                _rtl(f"סטופ: {_ltr(stop_text)}"),
                _rtl(f"יעד: {_ltr(target_text)}"),
                _rtl(f"רמת ביטחון: {_ltr(confidence_text)}"),
                _rtl(f"טווח זמן: {horizon}"),
            ))
        )
    updated = datetime.now(ISRAEL).strftime("%d/%m/%Y %H:%M:%S")
    if not lines:
        lines = [_rtl("אין כרגע פוזיציות פתוחות.")]
    # Reserve ample room for the repeated heading/footer. A single position
    # block is bounded by database field lengths and remains far below 3200.
    chunks: list[list[str]] = []
    separator = "\n\n" + "─" * 18 + "\n\n"
    current: list[str] = []
    for line in lines:
        projected = len(separator.join(current + [line]))
        if current and projected > 3200:
            chunks.append(current)
            current = [line]
        else:
            current.append(line)
    chunks.append(current)
    pages: list[str] = []
    page_count = len(chunks)
    for index, chunk in enumerate(chunks, 1):
        page_label = _rtl(f"עמוד {_ltr(index)} מתוך {_ltr(page_count)}") if page_count > 1 else ""
        message = "\n\n".join(value for value in (
            _rtl(f"📡 {SCANNER_DISPLAY_NAME_HE} — המשתמש הראשי והיחיד"),
            page_label,
            _rtl("⚠️ מסחר מדומה בלבד. זו תמונת מצב, לא המלצה או פקודת מסחר."),
            _rtl(f"סה״כ פוזיציות פתוחות: {_ltr(len(trades))}"),
            separator.join(chunk),
            _rtl(f"עודכן: {_ltr(updated)} (שעון ישראל)"),
        ) if value)
        if len(message) > 4096:
            raise ValueError("A single Telegram signal-status page exceeds 4096 characters")
        pages.append(message)
    return pages


def signals_status_message() -> str:
    """Compatibility accessor for the first status page."""
    return signals_status_messages()[0]


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
    """Create one status card and edit it in place without repeated pin events.

    Telegram emits a visible service message every time ``pinChatMessage`` is
    called, even with notifications disabled.  The status topics are already
    dedicated to these cards, so pinning adds clutter and repeated pinning on
    every refresh looks like duplicate alerts.  Keep the historical function
    name for compatibility, but deliberately never pin the card.
    """
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


def _remove_stale_signal_pages(active_page_count: int) -> dict[str, str]:
    """Delete overflow status pages that are no longer part of the live snapshot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return {}
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""SELECT state_key,message_id FROM scanner_telegram_topic_state
                   WHERE state_key LIKE 'signals_status:%' ORDER BY state_key""")
    stale: list[dict] = []
    for row in cur.fetchall():
        try:
            page_number = int(str(row["state_key"]).rsplit(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if page_number > active_page_count and row["message_id"]:
            stale.append(dict(row))
    conn.close()
    if not stale:
        return {}

    session = requests.Session(); session.trust_env = False
    base = f"https://api.telegram.org/bot{token}"
    results: dict[str, str] = {}
    for row in stale:
        state_key, message_id = str(row["state_key"]), int(row["message_id"])
        # Unpin is best effort: deletion is the authoritative stale-page cleanup.
        _call(session, base, "unpinChatMessage", {"chat_id": chat_id, "message_id": message_id})
        deleted, _, error = _call(session, base, "deleteMessage", {
            "chat_id": chat_id, "message_id": message_id,
        })
        already_absent = any(marker in error.lower() for marker in (
            "message to delete not found", "message_id_invalid", "message identifier is not specified",
        ))
        conn = get_db_connection(); cur = conn.cursor()
        if deleted or already_absent:
            cur.execute("DELETE FROM scanner_telegram_topic_state WHERE state_key=?", (state_key,))
            results[state_key] = "deleted"
        else:
            cur.execute("""UPDATE scanner_telegram_topic_state
                           SET last_attempt_at=?,last_error=? WHERE state_key=?""",
                        (_now_z(), f"delete:{error}"[:300], state_key))
            results[state_key] = "failed"
        conn.commit(); conn.close()
    return results


def refresh_telegram_status_cards() -> dict[str, str]:
    enabled = os.getenv("STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"portfolio": "disabled", "signals_status": "disabled"}
    # News topics contain real deduplicated alerts only.  Explanatory cards
    # used to be refreshed here and were perceived as repeated news.  Keep
    # the two live operational snapshots in their dedicated topics instead.
    result = {
        "portfolio": _upsert_pinned_message("portfolio", "portfolio_status", portfolio_status_message()),
    }
    signal_pages = signals_status_messages()
    for index, page in enumerate(signal_pages, 1):
        key = "signals_status" if index == 1 else f"signals_status:{index}"
        result[key] = _upsert_pinned_message(key, "signals_status", page)
    result.update(_remove_stale_signal_pages(len(signal_pages)))
    return result
