Telegram news-only operation
============================

Set ``AI_TRADER_OPERATION_MODE=news_only`` in every application role. Keep
``STOCK_SCANNER_ENABLED=true``: the legacy global switch also owns the news,
SEC, translation and Telegram loops. News-only mode stops trading discovery
before initialization, market-data download, final trading AI or signal work.
The scheduled task remains alive and reports an explicit disabled state.

Entry execution independently rejects news-only mode, including retained
pending/recovery orders after restart. The durable entry emergency pause is
also kept enabled. Its resume command is rejected while news-only is configured.
Switching a creation flag off is never treated as cancellation of an old order.
Existing positions and their TP/SL/close execution are not liquidated or disabled.

Disable all independent discovery/short/PEAD flags and the separate
``STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED`` flag at cutover. Preserve news
collection, news-only translation/editorial configuration, approved sources,
topic routing, watchlist and Telegram outbox. Historical trades and the existing
website are retained; this mode does not erase records or Telegram messages.
No broker or real-money execution is introduced. Backup and Codex automation
pauses remain as explicitly requested by the operator.

Verify effective mode/flags in all four running application roles, healthy
database/roles, durable entry pause, open/pending counts, zero post-cutover
trading scans/reviews/signals/orders/fills and advancing natural news workers.
Natural publication requires an eligible source event; no synthetic Production
trade, AI call or Telegram message is needed for verification. Reenabling trading
requires explicit operator direction, a mode change and a deliberate durable
resume; news-only mode never resumes trading automatically.
