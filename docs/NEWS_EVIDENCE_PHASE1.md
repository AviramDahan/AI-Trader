# News evidence — opt-in phase 1 (2026-09-27)

## Scope and safety

Branch: `codex/cloud-news-evidence`. **Not activated or deployed.** Default
`NEWS_EVIDENCE_ENABLED=false`. No model, confidence/materiality thresholds,
strategy, targets, accounting, candidate limit, budget or monitor-role changes.

Enrichment is restricted to verified tickers still held in the main portfolio or
enabled in the watchlist, and only missing source information. An explicit
`NEWS_EVIDENCE_NOT_BEFORE` UTC activation fence is required: never backdate it.
Historical diagnostic replay cannot enqueue messages. Original publication
timestamps do not change when evidence is fetched.

Final stock analysis still uses its existing `fetch_recent_news` / candidate
input. Enriched documents live in separate tables. Only an **in-memory copy** is
passed to the news reviewer; no enhanced source content is written to the
scanner's shared `source_facts_json` or OHLCV/news caches.

## Permitted source and actual availability

Only public SEC EDGAR filings, whose reuse and automated access were verified:

- [SEC webmaster FAQ — public filing reuse](https://www.sec.gov/about/webmaster-frequently-asked-questions).
- [SEC automated-access policy](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

The published SEC ceiling is 10 requests/s. This adapter shares the existing SEC
request lock, uses at most one enrichment request per second, and requires the
existing identifying `NEWS_SEC_USER_AGENT`. HTTP 403 is not bypassed. HTTP 429
and Retry-After pause all enrichment requests, with at most three actual attempts
per filing. No per-ticker news quota. DNS/connection/body timeouts, a 512-KiB body
limit, a single concurrent fetch, and an immutable filing cache bound resources.

Actual read-only availability probes from the cloud returned HTTP 200 for the
ANET, DELL and MSTR sample filings (35,028 / 5,424 / 146,609 bytes; 0.33 / 0.14 /
0.21 seconds respectively). These successful requests do not guarantee future
availability. No investor-relations website, Yahoo article crawler, paid source,
proxy, or scraping bypass was added.

Only exact HTTPS SEC archive URLs are allowed; no queries, credentials, custom
ports, traversal, internal/multicast IPs, or cross-filing redirects. DNS results
are checked before connecting to the pinned public IP with normal hostname/TLS
verification. A maximum of two redirects is allowed, within the same issuer and
accession. Public XSL display URLs map to the original XML in the same accession.

The document must independently identify the same issuer CIK and verified ticker.
Form 4 extraction retains transaction facts **and qualifying footnotes**, failing
closed if they exceed the existing 2,000-character source input. Inline-XBRL
filings require issuer and ticker identity plus complete item paragraphs that fit
the input budget. Other forms, incomplete excerpts, or unverified identity remain
unavailable; similarity of titles/company names is never used to attach an event.

## Persistence, retries and cost attribution

Migration `004_news_evidence.sql` adds news-only tables:

- `news_evidence`: original source body, chosen excerpt, exact URL, original
  publication time, fetch time, issuer/accession and normalized content version.
- `news_evidence_attempts`: persistent per-filing and provider backoff, safe reason,
  HTTP status, attempts, next attempt. Permanent errors terminate, not AI retries.
- `news_review_cache`: successful reviews and terminal quality failures. Formatting
  or publication-time changes alone do not invalidate the evidence fingerprint.
  Identical terminal quality failures are shared across IDs/context changes.
- `news_publication_audit`: missing information, irrelevance, low importance,
  quality failure, duplication, routing failure, and explicit operational reasons.
- `news_ai_call_links`: links each **existing** `ai_call_usage.call_id` to news,
  content version and stage. No second monetary ledger. Stages distinguish source
  analysis, editorial review/repair, semantic deduplication and thesis comparison.
  Transport retries remain individual existing usage rows. Sum each call once.

The continuous feed and six-hour reviews use the same cache/queue. No DB write
transaction spans fetching or AI. Position Monitor runs in its existing separate
role and has no dependency on this adapter. A failure fetching missing SEC facts
defers the job or terminates as insufficient information, not low importance.
There is no automatic promotion of a news item based on enrichment alone.

Example read-only cost query (sum only this ledger once):

```sql
SELECT l.news_id, l.content_version, l.stage,
       COUNT(*) AS calls, SUM(u.actual_cost) AS actual_cost,
       SUM(CASE WHEN u.actual_cost IS NULL THEN 1 ELSE 0 END) AS missing_costs
FROM news_ai_call_links l JOIN ai_call_usage u ON u.call_id=l.call_id
GROUP BY l.news_id,l.content_version,l.stage;
```

Missing cost is not zero. Do not add this grouped total to the existing budget
total: it is a breakdown of the same calls, not additional spend.

## Fixed real sample comparison (no AI, no Telegram)

Read-only sample IDs: 84, 96, 99, 360, 384, 400, 409, 420, 426, 434, 436, 438,
519, 618, 751. Selected deliberately from earlier missing-evidence diagnostics;
**not a random or representative sample**. All 15 had missing body/meaningful
excerpt information. Eight were exact SEC filings and seven Yahoo-linked items.

First isolated source replay:

- DELL #420: `FORM 4` metadata became 1,166 characters of verified transaction
  fields and qualifying footnotes. Original publication time retained.
- HOOD #426: `FORM 4` metadata became 1,997 characters including the pre-existing
  trading-plan qualification. Prior quality rejection is historical; this test
  does **not** claim that the new review passed or that an alert is justified.
- MSTR #434: `4` metadata became 880 characters describing exercise/sale and
  vesting footnotes, not an invented prediction.
- ANET #384: rejected by the excerpt-size safeguard rather than dropping context.
- Three Form 144 filings: unsupported document type, not guessed into a summary.
- MSTR #438: source identity could not initially be validated. The parser was
  subsequently corrected to handle multiple explicitly named XBRL trading symbols.
  A repeat source replay then exposed financial tables whose flattened headings
  could misassociate numbers. Such HTML filings now fail closed as
  `tabular_layout_unsupported`; no ambiguous table text is sent to the model.
- Seven Yahoo-linked items: unchanged; no authorized exact-event adapter in phase
  1. A stronger-looking headline is not proof of a missed publishable alert.

Initial source extraction took 0.783–1.261 seconds per SEC item, including request
spacing; a repeat measured 0.531–3.601 seconds. The final identical-sample replay
measured 0.846–1.369 seconds, with 3 successful enrichments, 5 fail-closed SEC
outcomes and 7 unchanged Yahoo items. Additional model calls: **0**. Additional AI cost: **$0**. Public messages:
**0**. The test verifies source access/identity/excerpt preservation, not new model
quality, end-to-end delivery latency, or the number of deserved publications.
Those outcomes must not be reported as improved on this evidence alone.

## Validation and activation gate

`scripts/test_news_isolated.py` disables .env, blocks external sockets and runs
tests only with temporary DB fixtures. Tests cover the kill switch, immutable
source preservation, six-hour cache reuse, issuer/event mismatches, SSRF, bounded
retry/backoff, retained qualifiers, exact model-payload excerpt, terminal review
cache, cosmetic changes, material corrections, correct-topic dedupe, removal from
watchlist/portfolio, and independent DB writes while source/model calls run.
The same evidence tests run against PostgreSQL in Cloud Readiness CI, along with
usage-ledger reconciliation, trading regression, restore, Docker and frontend build.

Initial local regression: 470 tests plus 29 subtests passed, frontend build passed.
One legacy experiment-attribution test originally depended on live price retrieval;
its fixture now mocks that quote (test-only change, no trading code change). The
isolated runner permits temporary test .env fixtures but blocks the real .env.
An additional pending-version delivery regression was added afterward: an old
queued version cannot be rebuilt using a newer summary and duplicate the new alert.
Stored evidence provenance remains visible when the collection kill switch is off.

Before production activation:

1. Review fixed-sample outcomes and remaining limitations with the user; obtain
   explicit activation approval. No automatic merge/deploy from this branch.
2. Back up recovery state. Apply additive migration 004 in a controlled rollout.
   The existing deployment script correctly refuses an unplanned schema-version
   change; **its safety guard has not been weakened**.
3. Deploy with the flag off, verify readiness and unchanged trading inputs/state.
4. Set the activation fence to that moment and enable only after approval.
5. Use existing monitoring for 48–72 hours: per-source success/backoff, unique news
   versus attempts, reason distribution, source matches, missed/justified alerts,
   duplicates, correct topics, queue age, p50/p95 latency, real stage cost and
   unchanged Position Monitor performance. No minimum-message success target.
6. Kill switch: set `NEWS_EVIDENCE_ENABLED=false` and restart only news/API/Telegram
   roles as needed. Do not roll back trading state or run local writers. Additive
   tables can remain; do not drop evidence/history to disable the change.

Monday live-market validation and existing automations are unchanged.
