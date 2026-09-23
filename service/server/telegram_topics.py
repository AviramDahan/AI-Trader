"""Server-only routing for Telegram forum topics."""

from __future__ import annotations

import os


NEWS_EVENT_TYPES = {
    "position_news", "watchlist_news", "watchlist_news_correction", "correction", "news_status",
}
PORTFOLIO_EVENT_TYPES = {"portfolio_status"}


def thread_id_for_event(event_type: str | None) -> int | None:
    if not event_type:
        return None
    if event_type in NEWS_EVENT_TYPES:
        name = "TELEGRAM_NEWS_THREAD_ID"
    elif event_type in PORTFOLIO_EVENT_TYPES:
        name = "TELEGRAM_PORTFOLIO_THREAD_ID"
    else:
        name = "TELEGRAM_TRADING_THREAD_ID"
    value = os.getenv(name, "").strip()
    try:
        thread_id = int(value)
        return thread_id if thread_id > 0 else None
    except (TypeError, ValueError):
        return None


def destination_fields(chat_id: str, event_type: str | None) -> dict[str, str | int]:
    fields: dict[str, str | int] = {"chat_id": chat_id}
    thread_id = thread_id_for_event(event_type)
    if thread_id is not None:
        fields["message_thread_id"] = thread_id
    return fields
