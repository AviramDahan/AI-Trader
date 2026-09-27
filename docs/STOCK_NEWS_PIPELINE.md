# Stock news delivery repair (2026-09-27)

Scanner-collected Yahoo news previously went through translation only. The feed
worker now promotes recent rows into the existing strict news analysis queue,
after independently verifying the headline/company identity. It reuses the
existing source record and deduplicates syndicated/per-ticker copies. Unrelated
headlines and old records are not promoted. No extra provider call is needed.

`STOCK_SCANNER_NEWS_SCAN_BRIDGE_MAX_AGE_HOURS=6` is the maximum age for this bridge;
the cutover `TELEGRAM_NEWS_NOT_BEFORE` boundary remains authoritative. No old
history is replayed. Existing news quality, materiality and relevance thresholds
are unchanged. A translated row is not proof of a publishable news alert.

Yahoo priority collection defaults to 20 tickers every 900 seconds
(`STOCK_SCANNER_YAHOO_NEWS_TICKERS_PER_CYCLE`,
`STOCK_SCANNER_YAHOO_NEWS_INTERVAL_SECONDS`). Open positions and watchlist are
first, active signals next, then a persistent rotating selection of technical
candidates and the cached stock universe. With eight positions and one watchlist
ticker, 11 slots remain for non-portfolio coverage. This is polling, NOT a
real-time full-universe feed; coverage reports the selected and rotating counts.
Existing provider backoff still applies. Scanner-sourced news is reused in
addition to these requests.

Explicit provider summaries are preserved when supplied. A missing summary is
not invented. Headline/feed-summary metadata is never treated as a full article.

## Primary company feed

Intel IR's public RSS is linked directly from its [official press releases
page](https://www.intc.com/news-events/press-releases):
https://www.intc.com/news-events/press-releases/rss

One conditional request every 15 minutes, ETag/Last-Modified and Retry-After
support. Only the supplied RSS headline/description/link/date are used; no
article scraping. Issuer identity verifies INTC, but relatedness/materiality
still require the unchanged analysis. The feed does not cover other companies.
No published contractual rate/SLA is assumed. Permission to reuse source content
remains the operator's responsibility; publicly accessible does not mean public
domain. Original publisher/link and source-vs-AI separation are retained.

## Delivery and safety

- Held stocks and enabled watchlist -> personal news topic.
- Other verified highly material stocks -> important-stock-news topic.
- Unverified macro/market items retain the separate market-news route.
- No forced alerts, paid AI benchmarks, historical replay or fake signals.
- Analysis stays in the separate news worker; position monitoring, accounting,
  TP/SL, strategy, model and AI candidate limit are unchanged.
- Telegram is still sent solely through the bounded, deduplicated outbox.
