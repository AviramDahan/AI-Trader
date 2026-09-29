# Retained-news evaluation — branch only, no production deployment

## Dataset and method

Window: 2026-09-28 16:32:30 through 2026-09-30 00:23:58 Asia/Jerusalem
(31h 51m, not two complete days). 3,310 retained news rows. Actual fallback
deliveries: 565 market, 75 stock, 1 watchlist and 2 position messages: 643 messages
covering 642 distinct source news rows.

Frozen, private dataset SHA256:
`58938f388026e2ef6ec9af62b7ce4ec5ded24a6c4853a6c56570ce2ad4311c64`.
The dataset and per-row results remain outside Git under the ignored local
`.runtime/staging` directory. No database/news export is committed.

`service/server/scripts/evaluate_retained_news.py` evaluates the identical file
using baseline `65954d5` or the branch rules. It performs no DB writes, HTTP,
AI requests, Telegram delivery or historical replays. A separate read-only
production export supplied the file. Existing saved analysis scores are reused
only as routing proxies, not as new canonical quality-review results.

## Results

- Pre-AI eligibility: 155 -> 164 retained rows (+9).
- Existing-analysis routing proxy: 127 -> 135 (+8).
- Among messages actually delivered, market routing proxy: 122 -> 128;
  stock routing proxy: 5 -> 7. Personal messages cannot be reconstructed reliably.
- Additional rows requiring analysis to know the outcome: 28 -> 29.
- Missing original Yahoo ticker metadata: 1,130 rows, unchanged. Within the
  delivered messages, 55 lack that evidence (52 stock, 3 personal).
- First blocks: identity 836 -> 830; classification 635 -> 633;
  insufficient evidence 470 -> 469; stale/future 66 unchanged;
  low importance 14 unchanged; relevance 4 unchanged.

These are NOT 135 promised deliveries. Cross-row canonical aggregation,
new SEC enrichment, new canonical AI/quality decisions and historical watchlist
changes are not reconstructed. 2,708 later source observations are excluded to
avoid look-ahead; retained source text itself can still have been updated.
Provider permissions are assumed from the existing approved collection paths,
not independently re-audited. Current issuer catalog is used.

## Recovered rows / review

All nine are retained Telegram-source observations. The following judgments
concern eligibility for review, not independent verification of the news claims.

- #2323 ECB/Lagarde inflation outlook higher in 2027/2028: identity block ->
  market proxy, relevance .80. GOOD for review; attributed outlook, not certainty.
- #2329 ECB/Lagarde broad-based growth continuing in Q3: identity block ->
  market proxy, .83. GOOD for review.
- #2358 Russia plans extension of diesel export ban through October, attributed
  to TASS: identity block -> market proxy, .70. GOOD for review; keep "plans".
- #2359 Preparing document for another month's diesel export ban: identity block
  -> requires analysis. QUESTIONABLE as an additional item: same apparent event
  as #2358. Do not count two unique events or promise two messages.
- #2585 US two-year Treasury yield reaches 4.952%: evidence block -> market
  proxy, .90. GOOD for review; numeric claim preserved exactly.
- #2980 BA/FAA delays MAX 10 approval while studying software issue:
  classification block -> important-stock proxy, .97. GOOD for review.
- #3181 AMD reportedly agrees to buy World Labs for $8.2bn: classification block
  -> important-stock proxy, .98. QUESTIONABLE pending grounding of this major
  acquisition claim; a relay headline is not independent confirmation.
- #4694 BoE/Taylor statement about monetary policy and energy-price shocks:
  identity block -> market proxy, .86. GOOD for review.
- #4891 BoE/Taylor conditional wage-growth expectations near 3%:
  identity block -> market proxy, .50. QUESTIONABLE standalone speech fragment;
  do not turn the conditional statement into a forecast.

Review: 6 suitable review candidates, 3 caveats, no demonstrated wrong-company
mapping among these nine. This deliberately selected sample is not a broad
false-positive rate. Questions/listicles, vague statements, live-speech notices
and secondary company mentions remain covered by negative regressions.

## Changes

- Narrow observed macro/classification/evidence fixes only. No routing scores,
  model, materiality requirements, identity rules or trading changes.
- Fallback source ledger retains supplied Yahoo ticker hints, publisher,
  summary, timestamps and sanitized original URL, plus the first observation
  recorded after this change. Hints do not become verified tickers. Old lost
  metadata cannot be recovered. Scanner/final-review facts and hashes unchanged.
- Private health alerts gain allowlisted diagnostics and one recovery message
  per incident generation. First failure context is retained after recovery.
  Raw exception text/credentials are not forwarded to Telegram.
- Canonical safety reports retain monitor/price context. The existing stop
  condition, timeout, fencing and manual-resume requirement are unchanged.

## Safety finding and recommendation

Validation performed: local backend 673 tests + 29 subtests; disposable
PostgreSQL 189 tests + 23 subtests; Linux image/import check and frontend build
passed. A CI test-module import-path issue was found after PostgreSQL passed,
fixed in the test files, and the 33 focused tests passed without local
PYTHONPATH. The final branch workflow is rerun before reporting completion.

The canonical watchdog latches fallback when monitor status is error or its
last success is older than 900 seconds. A later healthy monitor does not
automatically resume canonical news. The historical record proves the latch,
not the precise transient failure: generic alerts and overwritten details do
not establish a root cause. Do not remove the safety check based on inference.

Branch only. Recommend review/approval for these targeted fixes, not another
threshold change. The gain is modest and does not justify claiming full stock
coverage or a reliable Telegram/day forecast. No AI calls or AI charges were
generated by this evaluation. Remaining gaps require retained live evidence,
not an expensive historical AI batch by default.
