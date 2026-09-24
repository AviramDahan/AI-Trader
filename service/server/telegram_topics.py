"""Server-only routing for Telegram forum topics."""

from __future__ import annotations

import os


MARKET_NEWS_EVENT_TYPES = {"market_news"}
STOCK_NEWS_EVENT_TYPES = {
    "position_news", "watchlist_news", "watchlist_news_correction", "stock_news", "correction", "news_status",
}
SIGNAL_EVENT_TYPES = {"new_signal", "signals_status"}
TRADE_EVENT_TYPES = {"entry", "entry_chart", "tp", "stop", "sell", "stop_change"}
PORTFOLIO_EVENT_TYPES = {"portfolio_status"}


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
