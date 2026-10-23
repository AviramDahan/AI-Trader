"""Server-only routing for Telegram forum topics."""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit


MARKET_NEWS_EVENT_TYPES = {"market_news"}
SEC_INTELLIGENCE_EVENT_TYPES = {"sec_intelligence"}
PERSONAL_NEWS_EVENT_TYPES = {"position_news", "watchlist_news", "watchlist_news_correction"}
STOCK_NEWS_EVENT_TYPES = {
    "position_news", "watchlist_news", "watchlist_news_correction", "stock_news", "correction", "news_status",
}
SIGNAL_EVENT_TYPES = {"new_signal", "signals_status"}
TRADE_EVENT_TYPES = {"entry", "entry_chart", "tp", "stop", "sell", "stop_change"}
PORTFOLIO_EVENT_TYPES = {"portfolio_status"}


def with_news_community_link(message: str, event_type: str | None) -> str:
    """Append the server-configured join link to all news, never trade alerts."""
    if event_type not in MARKET_NEWS_EVENT_TYPES | STOCK_NEWS_EVENT_TYPES | SEC_INTELLIGENCE_EVENT_TYPES:
        return message
    link = os.getenv("TELEGRAM_COMMUNITY_URL", "").strip()
    # Presentation only: stored evidence/URLs and all eligibility stay intact.
    # Apply at send-time too, so already-queued news follows the same preference.
    from news_source_links import SOURCE_LINE, safe_source_url
    def public_link(match):
        url = match.group(0)
        if url == link or urlsplit(url).hostname in {'creativecommons.org', 'www.creativecommons.org'}:
            return url  # Community invitation and license notices are not news sources.
        return ''
    lines, sources = [], []
    for line in message.splitlines():
        source = SOURCE_LINE.fullmatch(line)
        if source:
            safe = safe_source_url(source[1])
            if safe and not sources:
                sources.append('מקור: ' + safe)
            continue
        cleaned = re.sub(r'https?://[^\s<>]+', public_link, line)
        if cleaned != line:
            cleaned = cleaned.rstrip(' :')
            if cleaned in {'מקור', 'Source'}:
                cleaned = ''
        lines.append(cleaned)
    from news_presentation import hide_relay_branding
    message = hide_relay_branding('\n'.join(lines))
    message = re.sub(r'\n{3,}', '\n\n', message).strip()
    parsed = urlsplit(link)
    valid = not (len(link) > 512 or parsed.scheme != "https" or parsed.netloc != "t.me" or
            not parsed.path.strip('/') or parsed.path.startswith('/c/') or
            any(char.isspace() for char in link))
    footer = "📣 להצטרפות לקהילת AI-Trader:\n" + link
    if valid and message.endswith(footer):
        message = message[:-len(footer)].rstrip()
    tails = sources + ([footer] if valid else [])
    if not tails:
        return message
    suffix = '\n\n' + '\n\n'.join(tails)
    # Budget AFTER bidi isolates, not before: mixed Hebrew/Latin expands on
    # the actual wire. Preserve both source and CTA even for a long invite URL.
    from telegram_presentation import telegram_text, utf16_length
    if utf16_length(telegram_text(message + suffix, limit=100_000)) > 4096:
        budget = 4096 - utf16_length(telegram_text(suffix, limit=100_000))
        message = telegram_text(message, limit=budget).rstrip()
    return message + suffix


def thread_id_for_event(event_type: str | None) -> int | None:
    if event_type == 'community_discussion':
        return None  # General: omit message_thread_id, never trading fallback.
    if not event_type:
        return None
    if event_type in MARKET_NEWS_EVENT_TYPES or event_type == 'trump_truth_post':
        names = ("TELEGRAM_MARKET_NEWS_THREAD_ID", "TELEGRAM_NEWS_THREAD_ID")
    elif event_type in SEC_INTELLIGENCE_EVENT_TYPES:
        # Never fall back to General or another public topic for SEC research.
        names = ("TELEGRAM_SEC_INTELLIGENCE_THREAD_ID",)
    elif event_type in PERSONAL_NEWS_EVENT_TYPES:
        names = ("TELEGRAM_PERSONAL_NEWS_THREAD_ID", "TELEGRAM_STOCK_NEWS_THREAD_ID", "TELEGRAM_NEWS_THREAD_ID")
    elif event_type in STOCK_NEWS_EVENT_TYPES:
        names = ("TELEGRAM_STOCK_NEWS_THREAD_ID", "TELEGRAM_NEWS_THREAD_ID")
    elif event_type in SIGNAL_EVENT_TYPES:
        names = ("TELEGRAM_SIGNALS_THREAD_ID", "TELEGRAM_TRADING_THREAD_ID")
    elif event_type in TRADE_EVENT_TYPES:
        names = ("TELEGRAM_AGENT_ACTIONS_THREAD_ID", "TELEGRAM_SIGNALS_THREAD_ID", "TELEGRAM_TRADES_THREAD_ID", "TELEGRAM_TRADING_THREAD_ID")
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
