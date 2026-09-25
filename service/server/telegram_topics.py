"""Server-only routing for Telegram forum topics."""

from __future__ import annotations

import os
from urllib.parse import urlsplit


MARKET_NEWS_EVENT_TYPES = {"market_news"}
STOCK_NEWS_EVENT_TYPES = {
    "position_news", "watchlist_news", "watchlist_news_correction", "stock_news", "correction", "news_status",
}
SIGNAL_EVENT_TYPES = {"new_signal", "signals_status"}
TRADE_EVENT_TYPES = {"entry", "entry_chart", "tp", "stop", "sell", "stop_change"}
PORTFOLIO_EVENT_TYPES = {"portfolio_status"}


def with_news_community_link(message: str, event_type: str | None) -> str:
    """Append the server-configured join link to all news, never trade alerts."""
    if event_type not in MARKET_NEWS_EVENT_TYPES | STOCK_NEWS_EVENT_TYPES:
        return message
    link = os.getenv("TELEGRAM_COMMUNITY_URL", "").strip()
    parsed = urlsplit(link)
    if (len(link) > 512 or parsed.scheme != "https" or parsed.netloc != "t.me" or
            not parsed.path.strip('/') or parsed.path.startswith('/c/') or
            any(char.isspace() for char in link)):
        return message
    footer = "📣 להצטרפות לקהילת AI-Trader:\n" + link
    if message.endswith(footer):
        return message
    # Telegram measures the 4096-character limit in UTF-16 units.
    suffix = "\n\n" + footer
    budget = 4096 - len(suffix.encode('utf-16-le')) // 2
    body = message.encode('utf-16-le')[:budget * 2].decode('utf-16-le', errors='ignore').rstrip()
    return body + suffix


def thread_id_for_event(event_type: str | None) -> int | None:
    if not event_type:
        return None
    if event_type in MARKET_NEWS_EVENT_TYPES:
        names = ("TELEGRAM_MARKET_NEWS_THREAD_ID", "TELEGRAM_NEWS_THREAD_ID")
    elif event_type in STOCK_NEWS_EVENT_TYPES:
        names = ("TELEGRAM_STOCK_NEWS_THREAD_ID", "TELEGRAM_NEWS_THREAD_ID")
    elif event_type in SIGNAL_EVENT_TYPES:
        names = ("TELEGRAM_SIGNALS_THREAD_ID", "TELEGRAM_TRADING_THREAD_ID")
    elif event_type in TRADE_EVENT_TYPES:
        names = ("TELEGRAM_TRADES_THREAD_ID", "TELEGRAM_TRADING_THREAD_ID")
    elif event_type in PORTFOLIO_EVENT_TYPES:
        names = ("TELEGRAM_PORTFOLIO_THREAD_ID",)
    else:
        names = ("TELEGRAM_TRADING_THREAD_ID",)
    for name in names:
        value = os.getenv(name, "").strip()
        try:
            thread_id = int(value)
            if thread_id > 0:
                return thread_id
        except (TypeError, ValueError):
            continue
    return None


def destination_fields(chat_id: str, event_type: str | None) -> dict[str, str | int]:
    fields: dict[str, str | int] = {"chat_id": chat_id}
    thread_id = thread_id_for_event(event_type)
    if thread_id is not None:
        fields["message_thread_id"] = thread_id
    return fields
