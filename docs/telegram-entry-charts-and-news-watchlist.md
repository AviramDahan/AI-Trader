# Telegram entry charts and news-only watchlist

After a native (non-Legacy, non-Shadow) paper entry is executed, the durable
Telegram outbox first sends the Hebrew entry text. It then queues exactly one
chart photo for that primary trade. The chart uses real Yahoo Finance 15-minute
OHLC data available before the recorded entry, with an actual simulated-entry
marker, original stop and the trade's snapshotted TP1/TP2/TP3. Under the default
single strategy, TP2 is labeled as the operational target and TP1/TP3 as Shadow.
It is not an AI-generated chart and the levels are not forecasts.

Chart generation and delivery have bounded retries and deduplication. Failure
does not repeat the text alert, alter the trade or block monitoring. Images are
cached only under ignored `.runtime/entry-charts`. Telegram credentials remain
server-side. No chart is sent retroactively for Legacy or previously opened
positions.

The News tab also exposes a durable news-only watchlist. Adding/removing symbols
requires either a global administrator or an explicitly enrolled scanner
operator; the public dashboard may display the list. Scanner operators do not
receive any other administrator capability. Enrollment is performed locally
with `python scripts/configure_scanner_operator.py <agent-name>`.
Watched symbols are fixed-priority inputs to the shared Yahoo collection batch,
ahead of rotating candidates. They reuse provider cadence, caching, rate-limit
backoff, cross-source deduplication and the separate Ollama analysis queue.

Only new, verified-ticker, actually related news assessed as medium/high
materiality and positive/negative/mixed creates a Hebrew Telegram alert. An open
position receives its position alert instead of a duplicate watchlist alert.
When a priority fetch matches a canonical row that the older market feed already
translated, the row is promoted to the full materiality analyzer rather than
being left at translation-only status. This promotion applies only to fresh
priority relationships (including watchlist articles published after the symbol
was added) and remains deduplicated by article/version/ticker.
Removing a symbol stops future priority collection and alerts. Adding a symbol
does not create a signal, order, position or trade, and old articles are not
retroactively alerted. Yahoo coverage is periodic and may be delayed or limited.

Telegram Forum routing uses five server-side topic IDs: `חדשות שוק`, `חדשות
מניות`, `סיגנלים`, `עסקאות דמו`, and `מצב תיק דמו`. The stock-news topic
contains one pinned scope card that lists the independently watched symbols,
open positions, active signals and the size of the rotating technical-candidate
pool. The card is edited in place, so it does not create repeated messages.
Every material alert names the verified ticker and company, preserves the
original publisher/title/publication time/direct URL, and labels Hebrew summary
and interpretation as AI output. Headline-only coverage is stated explicitly.

Stock news is not restricted to held positions. A verified item for any ticker
in the priority/rotating scanner collection may be broadcast without creating a
signal or trade, but only when Ollama marks it actually related, high
materiality and at least 80% relevant. There is deliberately no per-ticker or
daily hard cap: a second distinct critical event must not be hidden. Spam is
controlled through verified attribution, strict quality gates, canonical
cross-source/event-version deduplication and no repeat for unchanged items.
Market-wide Telegram alerts are limited to high-materiality, high-relevance
official Federal Reserve/BLS releases; other market news remains in the UI.

The paper-portfolio topic contains one pinned mark-to-market card. It is edited
every five minutes and after a delivered entry/TP/stop/SELL/stop-change event.
It reports managed-account equity, cash, exposure, net result, gross realized
P&L, current unrealized P&L, fees and open-position levels. Adopted Legacy
positions remain visible but are counted separately from the managed scanner
account so their historic funding is not invented or mixed into its equity.
The topic message ID is durable in SQLite; bot token, chat ID and forum topic IDs
remain only in ignored local configuration/private backup.

The Signals topic contains individual new strong-signal alerts plus one edited,
pinned `active signals / open positions` card. That card includes every current
primary open position without replaying fake signals. Hebrew labels are forced
RTL and Latin tickers, company names, prices and percentages use Unicode bidi
isolation so Telegram does not reorder mixed-language lines. Entry, current
price, stop, operational target, confidence and time horizon use separate lines;
the operational price is labeled `יעד`, while duration is labeled `טווח זמן`.
Lifecycle events and entry charts remain in the separate paper-trades topic.

Authenticated browser notifications send their token in the first WebSocket
message, never in the WebSocket URL. This prevents browser/proxy access logs from
capturing credentials. Production supervision also disables Uvicorn access logs;
`scripts/sanitize_runtime_logs.py` removes legacy credential-shaped entries from
local operational logs.
