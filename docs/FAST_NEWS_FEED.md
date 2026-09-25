# Fast news feed

Paper trading, confidence/risk thresholds and price monitoring are unchanged.
This is a news delivery change, not a new trading strategy.

## Processing

- Ready analysis jobs drain continuously; the configured AI interval applies only
  when idle. Market stories get scheduling priority 90; position news retains 100.
  Market stories published within ten minutes receive a freshness bonus. Waiting
  adds up to 30 priority points; every fifth completion reserves a catch-up slot
  for work waiting over ten minutes. New market news does not sit behind all old
  filings, while old work still progresses. The counter persists in job storage.
- Exact URL/source-ledger duplicates are merged at ingestion. Potential semantic
  duplicates still receive a separate source-only comparison; material new facts
  are not suppressed and there is no per-ticker quota. A model duplicate verdict
  cannot suppress a release with numerical facts absent from the referenced source.
- With `STOCK_SCANNER_NEWS_FAST_MARKET=true`, ordinary market news uses one
  source-only translation/classification call. Schema, Hebrew, numerical and
  known terminology checks remain mandatory. Uncertain/suspicious drafts fall
  back to the strict editorial path. Possible duplicates need an extra call.
- Position/thesis assessment retains its strict path. Its text cannot contaminate
  market translations. It never changes trades or TP/SL. Price monitoring runs in
  a separate existing background task.
- SEC 424B2/424B3/FWP items whose excerpt is *only* filing date/accession/size
  retain metadata and a source-only label without using the model or generating
  an alert. Substantive excerpts and other filings are not discarded by this rule.

## Telegram ingestion

`TELEGRAM_NEWS_STREAM_ENABLED=true` enables one authorized local reader session
for the configured public-channel allowlist. No private messages, automatic joins
or new credentials are needed. Live updates and edits are ingested idempotently.
Every 60 seconds the reader also catches up from the persisted per-channel cursor.
Live arrivals do not advance that cursor, preventing out-of-order gaps. Flood
waits preserve cursors and are respected. Disabling the flag restores the original
periodic provider path. RSS provider cadences/backoff are unchanged.

Public channels may not deliver every live update to a session; catch-up is the
fallback, not a guarantee of exchange-style real-time delivery.

## Configuration and measurement

- `STOCK_SCANNER_NEWS_FAST_MARKET`: defaults false; enabled locally after testing.
- `TELEGRAM_NEWS_STREAM_ENABLED`: defaults false; enabled locally after testing.
- `STOCK_SCANNER_NEWS_AI_INTERVAL_SECONDS`: idle wait, default/local 2 seconds.
- `OLLAMA_NEWS_MODEL`: existing `gemma3:12b`, unchanged from before this update.

News rows persist actual `analysis_seconds` and `analysis_finished_at`. News UI
shows recent measured analysis time, ingestion-to-completion (including waiting)
and ingestion-to-Telegram delivery. Samples are distinct from source publication
delay. The latest 100 measured stories can include old backlog; the UI must not
be interpreted as an SLA or a prediction for every future story.

A read-only comparison on three existing source stories measured Gemma at
8.69/3.95/3.31 seconds and Qwen3 8B at 34.74/56.75/4.89 seconds, including fallback
where applicable. Qwen produced broken mixed-script Hebrew; it was not selected.
This small local comparison includes loading/contention and is not a general
hardware benchmark. No benchmark output was stored as news or sent to Telegram.

Parallel GPU generation is not enabled: the smaller-model trial did not establish
a benefit, and serial committing keeps semantic deduplication deterministic.
The 30–60 second end-to-end target remains an operational measurement target,
not a guarantee under bursts, outages or strict fallback.

## Verification on 2026-09-25

- Full local backend suite: 316 passed plus 10 subtests before the final guards;
  subsequent focused quality/scheduler tests passed; final full suite runs in CI.
- Frontend production build passed. Public Pages news view checked in a real
  browser at desktop and 390px, Hebrew RTL and English LTR, without horizontal overflow.
- Public HTTPS health returned 200; browser recovered after the supervised restart.
- Telegram market topic received real source news; no synthetic news/test alerts.
- Initial live burst during catch-up/restarts: three delivered stories measured
  78, 93 and 136 seconds from ingestion. This does NOT establish the 30–60 second
  target. Historical backlog makes the dashboard's rolling aggregate larger.
- Rejected translations remain visible as failures/retries, never as no-news.
  Model translation is not infallible; known truncated/mixed-script/currency and
  auction-imbalance failures now trigger strict review or rejection.
- Existing source records and paper-trade accounting were preserved. Narrow
  re-evaluation of items misclassified during rollout uses the same dedupe ledger;
  already-sent alerts are not replayed.
