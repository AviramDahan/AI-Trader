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

Authenticated browser notifications send their token in the first WebSocket
message, never in the WebSocket URL. This prevents browser/proxy access logs from
capturing credentials. Production supervision also disables Uvicorn access logs;
`scripts/sanitize_runtime_logs.py` removes legacy credential-shaped entries from
local operational logs.
