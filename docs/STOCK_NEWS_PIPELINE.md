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

## Dynamic company coverage (no issuer-specific scheduled feed)

The permanent Intel-only RSS adapter has been removed. Yahoo and SEC use the
live database portfolio/watchlist on each collection cycle; no issuer-specific
connector is required when a user adds or removes a stock. Removed providers are
marked `retired`, excluded from the active provider UI, and no longer fetched.
Existing articles and provider checkpoints are retained, not deleted.

Removing a watch ticker removes its dedicated priority unless a main position
is still open (or a valid, unentered active signal separately warrants priority).
An old ENTERED signal alone no longer creates a perpetual subscription after
the actual position closes. Broad-universe rotation remains independent: an
unwatched ticker can still appear in important-stock news under the unchanged
stricter materiality/relevance requirements. This is not dedicated monitoring.

Immediately before each personal Telegram send/retry, the dispatcher resolves
the stored news reference and checks the original target tickers against the
current open main positions and enabled watchlist. Removed targets are excluded
from the ticker/company labels. If no relevant target remains, the message is
persistently cancelled with a reason (no retry). If a held stock becomes watched
only, the message is relabelled accordingly. Unknown legacy references fail
closed; no instructions or tickers are inferred from free text. Already sent
messages and historical data remain intact. No DB transaction is held across
Telegram HTTP; a state change during an already in-flight send cannot retract it.

No automatic broad-tier promotion of cancelled personal alerts: that could
bypass the broad tier's stricter filters or replay history. New broad news
continues normally. Additional official issuer feeds, if added later, must use
verified issuer mappings and dynamic subscriptions, not one-off ticker code.

## Delivery and safety

- Held stocks and enabled watchlist -> personal news topic.
- Other verified highly material stocks -> important-stock-news topic.
- Unverified macro/market items retain the separate market-news route.
- No forced alerts, paid AI benchmarks, historical replay or fake signals.
- Analysis stays in the separate news worker; position monitoring, accounting,
  TP/SL, strategy, model and AI candidate limit are unchanged.
- Telegram is still sent solely through the bounded, deduplicated outbox.
