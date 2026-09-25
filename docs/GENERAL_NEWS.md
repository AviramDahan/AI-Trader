# General Telegram news

The existing market-news topic now receives short Hebrew general-news bulletins,
independent of holdings. No new paid provider or Telegram topic is required.
Existing sources include cached market feeds (BBC Business, Federal Reserve,
CoinDesk and EIA RSS fallback) and the connected official news providers.
Coverage is partial, not a real-time wire. Provider failures/backoff remain visible
in the scanner dashboard. Existing source collection schedules are unchanged:
the pipeline checks every 5 minutes, Yahoo priority every 15 minutes, and the
upstream broad-market snapshot schedule uses MARKET_NEWS_REFRESH_INTERVAL.

Only market-scoped, analyzed, topically relevant news is eligible.
Routine and neutral updates are allowed regardless of market materiality. General
news defaults to relevance 0.5 (configurable with
STOCK_SCANNER_GENERAL_NEWS_MIN_RELEVANCE, minimum 0.5); this is topical relevance,
not signal confidence. Ads, lifestyle advice and investment promotions are excluded.
Verified company-ticker news stays in the
stock-news path. The trade/signal quality thresholds are unchanged.

- STOCK_SCANNER_GENERAL_NEWS_ENABLED: true by default; false disables bulletins.
- STOCK_SCANNER_GENERAL_NEWS_MAX_AGE_HOURS: 6 by default (1–24).
- TELEGRAM_MARKET_NEWS_THREAD_ID: existing destination; secrets remain server-side.
- TELEGRAM_COMMUNITY_URL: public Telegram join link configured in the local .env.
  The shared sender appends it to every news event (general, stock, position,
  watchlist and corrections), including queued retries. Trade and signal alerts
  are unchanged. Missing/invalid links omit the footer safely. Existing Telegram
  messages are not edited or resent.

Messages contain a Hebrew AI translation, original publisher, publication time
and original link. Headline-only inputs are explicitly marked, without a generated
article summary. No investment interpretation or recurring empty-status posts.
Persistent event deduplication and the existing retry outbox are reused. There is
no daily per-ticker cap. Old analyzed backlog is not replayed on deployment.

## Sources added 2026-09-25

- ECB: https://www.ecb.europa.eu/rss/press.html and
  https://www.ecb.europa.eu/rss/statpress.html — monetary policy and statistics.
  [Official RSS list](https://www.ecb.europa.eu/home/html/rss.en.html).
  [Reuse conditions](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html)
  require accurate attribution and marking modifications; translations are labeled.
  We do not collect the separately licensed working-paper feed.
- Global Voices: https://globalvoices.org/feed/ — complementary international
  affairs/technology coverage, not a financial breaking-news wire.
  [Republication policy](https://globalvoices.org/about/global-voices-attribution-policy/)
  permits CC BY reuse. Author and original link are placed above translated
  headlines and the license link is included. No media or full text is copied.
  Items without an author are skipped.

Both were fetched successfully with HTTP 200 and parsed in the deployment
environment before activation. Each feed currently exposes 15 items (not full
historical coverage). No numerical provider quota was specified in the reviewed
pages: the selected cadence is a conservative application setting, not a claimed
provider guarantee. They use the existing 5-minute scheduler, conditional HTTP
requests, persisted validators and rate-limit/error backoff. Source frequency
varies; there is no guarantee of a message every five minutes. Existing providers
and trade/news-monitor schedules are unchanged.
