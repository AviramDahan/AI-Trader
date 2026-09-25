# General Telegram news

The existing market-news topic now receives short Hebrew general-news bulletins,
independent of holdings. No new paid provider or Telegram topic is required.
Existing sources include cached market feeds (BBC Business, Federal Reserve,
CoinDesk and EIA RSS fallback) and the connected official news providers.
Coverage is partial, not a real-time wire. Provider failures/backoff remain visible
in the scanner dashboard. Existing source collection schedules are unchanged:
the pipeline checks every 5 minutes, Yahoo priority every 15 minutes, and the
upstream broad-market snapshot schedule uses MARKET_NEWS_REFRESH_INTERVAL.

Only market-scoped, analyzed, relevant medium/high importance news is eligible.
Neutral economic releases are allowed. Verified company-ticker news stays in the
stock-news path. The trade/signal quality thresholds are unchanged.

- STOCK_SCANNER_GENERAL_NEWS_ENABLED: true by default; false disables bulletins.
- STOCK_SCANNER_GENERAL_NEWS_MAX_AGE_HOURS: 6 by default (1–24).
- TELEGRAM_MARKET_NEWS_THREAD_ID: existing destination; secrets remain server-side.

Messages contain a Hebrew AI translation, original publisher, publication time
and original link. Headline-only inputs are explicitly marked, without a generated
article summary. No investment interpretation or recurring empty-status posts.
Persistent event deduplication and the existing retry outbox are reused. There is
no daily per-ticker cap. Old analyzed backlog is not replayed on deployment.
