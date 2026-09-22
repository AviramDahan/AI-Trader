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
requires the existing admin token; the public dashboard may display the list.
Watched symbols are fixed-priority inputs to the shared Yahoo collection batch,
ahead of rotating candidates. They reuse provider cadence, caching, rate-limit
backoff, cross-source deduplication and the separate Ollama analysis queue.

Only new, verified-ticker, actually related news assessed as medium/high
materiality and positive/negative/mixed creates a Hebrew Telegram alert. An open
position receives its position alert instead of a duplicate watchlist alert.
Removing a symbol stops future priority collection and alerts. Adding a symbol
does not create a signal, order, position or trade, and old articles are not
retroactively alerted. Yahoo coverage is periodic and may be delayed or limited.
