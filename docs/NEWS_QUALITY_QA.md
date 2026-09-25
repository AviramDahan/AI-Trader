# News quality repair — September 25, 2026

The later opt-in market fast path and delivery measurements are described in
[FAST_NEWS_FEED.md](FAST_NEWS_FEED.md). The strict editorial path below remains
in use for position analysis and suspicious market output.

## Findings and safeguards

- A malformed multi-story Ollama response previously retried the whole batch, sometimes more than 90 times. Production now processes and commits one story at a time with an explicit JSON schema, type validation and a finite retry budget. One failed story cannot poison other stories.
- Source translation never receives the entry thesis, past generated summaries or other news. A separate source-only bilingual check rejects unsupported claims and poor Hebrew. Numerical facts in title/summary must exist in the supplied source. One editorial correction is allowed, then the item fails closed. Thesis comparison is separate and cannot change positions.
- Event comparison is separate from translation and compares original facts with previously alerted stories. Same-topic news is not automatically a duplicate; material new facts remain eligible. Duplicate records retain original sources and are linked to the retained story. This is best-effort semantic comparison, not proof that every event in every source will be perfectly clustered; there is no per-stock news quota.
- `news_ai` reports unresolved retries/failures even when no job is currently due. Idle does not overwrite the last actual successful analysis time.
- Historical summaries that injected technical claims absent from source metadata are quarantined, original metadata retained, and re-reviewed at lower priority. Repairs never replay the backlog as new Telegram alerts. The UI displays the outstanding historical review count.

## Configuration

- `OLLAMA_NEWS_MODEL`: optional installed local Ollama model for Hebrew news, separate from trading review. This machine uses `gemma3:12b`; the previous smaller Qwen model mistranslated tested headlines. No new paid service or API key.
- `STOCK_SCANNER_NEWS_ANALYSIS_MAX_ATTEMPTS`: default 6. Exhausted jobs remain visible as failures for operator investigation; they are not mislabeled “no news”.

## Historical maintenance (completed)

One-off repair, replay and news-chat cleanup scripts were removed after the user
chose a clean news-chat history. They are not part of application startup or
ongoing operation. Their source remains recoverable from Git history. Private
database snapshots and message archives remain in ignored `.runtime`; removing
the tools does not undo completed data repairs or restore deleted Telegram
messages. Trading data, credentials and runtime safeguards are unchanged.

## Validation

### 2026-09-25 follow-up

The completed historical review handled 364 quarantined records as
source-only Hebrew headline summaries, clearing the historical review backlog.
It checked source identity against the original backup and created a fresh SQLite
backup before writing. It emitted no alerts and did not rewrite trade history. A live
before/after comparison confirmed accounts, orders, fills and trades unchanged.
SEC summaries identify the form and issuer only; metadata is not evidence of
price impact. Tests specific to the retired one-off tool were removed with it;
ongoing news and trading regression tests remain.

Two additional Telegram messages (685/686) were corrected in place after a
durable-goods mistranslation; original text is archived privately. A deterministic
terminology guard now rejects narrowing durable goods to electrical appliances
and confusing analyst consensus with a preliminary official estimate.

SEC recovered from one ReadTimeout on its next scheduled attempt without a
manual restart. This does not guarantee provider availability. Older Telegram
messages were subsequently cleared at the user's request, as recorded below.

### Final scoped audit (after user-requested news-chat cleanup)

- The user chose clearing the news topics instead of further editing old
  messages and explicitly excluded news queue optimization. The cleanup removed
  and verified 114 messages from the three configured news topics only. Original
  message records were archived under ignored `.runtime`; topic IDs, trading
  history and status/signal topics were preserved.
- The syndicated-URL regression now uses the source ledger when a relay changes
  its headline, preventing a second article for the already known source URL.
  The focused news suite passed 50 tests plus 8 subtests after that change.
- The full local suite before that final regression passed 308 tests plus 10
  subtests; CI for commit `9c83670` passed including the additional regression.
- A read-only live Ollama regression translated the previously failing durable
  goods headline correctly as מוצרים בני קיימא and consensus as תחזית האנליסטים,
  preserving the -0.4% forecast. No news row or Telegram message was created.
- Controlled backend and tunnel termination passed automatic recovery: new owned
  processes, one API listener, healthy public HTTPS, automatic Pages deployment
  and changed runtime-config. The already-open browser displayed a connection
  failure during the outage and recovered without reload or Retry click.
- Final public health returned HTTP 200/ok, SEC status was ok without error,
  and there were zero unsent Telegram retries. Pages and CI both passed.

Known limitations are not proof of a remaining identified regression: source
availability and model translation quality cannot be guaranteed for all future
news. Real SELL/SL events were not fabricated; their lifecycle paths are covered
by isolated tests, not claimed as new live executions.

Tests cover schema rejection, isolation of one bad story, bounded correction, source/thesis separation, invented price/time rejection, duplicate-versus-new-fact behavior, source-link retention, bounded retries, and visible unresolved status. Existing integration coverage covers paper lifecycle, shadow isolation, news collection/retries, material position alerts and Telegram failures. Tests block real Telegram network access.

Live verification must separately check health/CORS, scanner/monitor freshness, accounting reconciliation, real topic receipts and browser rendering. Mocked delivery does not prove a new real fill occurred. Historical evidence restoration does not masquerade as a new trade.
