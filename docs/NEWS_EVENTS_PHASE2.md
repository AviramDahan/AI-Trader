# Phase 2: canonical news events — isolated branch, NOT deployed

Baseline: production `d9ab6ce`, schema 004. No existing runtime, migration,
worker, scanner table, trading input, threshold, model, budget or Phase 1
observation setting is changed. All new providers default to disabled.

## Architecture and activation boundary

`NewsProvider → normalize → verified identity/recency/type → canonical event`
`→ EvidenceProvider/cache → one canonical quality job → content-based routing`
`→ version/topic-unique sandbox delivery preview`.

`news_events/` is deliberately not imported by the production role launcher.
The sandbox has **no Telegram transport** and no default live AI client. It
cannot send a public message. Existing collectors can be injected through
`ExistingProvider`; their data then follows exactly the same core. Adapters do
not choose topics. Future adapters require registry/config/tests, not edits to
routing, AI or trading. The legacy production pipeline is NOT secretly replaced
by this branch.

The existing scanner S&P 500 + Nasdaq-100 union supplies the identity catalog;
`bridge.scanner_identity_catalog` adds CIKs from the existing official SEC ticker
map. The scanner cache itself does not contain CIKs. Bare symbols/common words
are not verified identities. No new per-ticker news feeds or IR-page crawler.

Before any controlled deployment, a separate approved activation change must
wire a dedicated worker, the effective production policy and budget-enforcing
completion client, schema migration, and event delivery to the real outbox.
Tests here verify the event outbox/preview contract, **not live Telegram**.
Phase 1 and its 48/72-hour measurement remain untouched.

## Canonical schema and durability

`ne_events`: event_id/canonical_event_id, provider/source list, URLs, publisher,
source type, original publication and collection times, title/source excerpt,
normalized attributed evidence, verified ticker/company/CIK, event type,
provenance/rights, content hash, evidence version, analysis state, reason,
conflict state. AI interpretation is stored separately in `ne_analysis`.

`ne_sources` retains immutable source revisions, including inactive superseded
revisions. `ne_versions` preserves evidence snapshots. `ne_anchors` maps exact
event identities. `ne_evidence_cache` is shared across discoveries.
`ne_provider_state` persists checkpoints, cursors, backoff and leases.
`ne_analysis` has an atomic event/version claim; `ne_delivery` is unique on
event/version/topic. `ne_metrics` stores providers, stage, outcome, latency and
per-call usage/cost without allocating one event's cost multiple times.

SQLite requires a fresh isolated DB. PostgreSQL installation rejects schemas
other than `test_*` / `news_phase2_*`. This DDL is intentionally not registered
with production migrations. No DB transaction spans provider/AI I/O. Restart
retains caches/claims/preview receipts. An interrupted possibly-billed AI call
is held as `interrupted_unknown`, not automatically repeated.

## Dedupe, updates and conflict policy

- Strong keys: same canonical article URL, exact issuer/accession or substantive
  verbatim facts. Explicit filing/story references link cross-source reporting.
  Homepage, category and quote links cannot merge events.
- No automatic same-company/day or fuzzy-headline merging. Unrelated company
  stories remain separate. A bridge between two existing canonical events is
  held for review rather than silently merging previously delivered stories.
  Its original evidence is retained in `ne_quarantine`, not dropped.
- One event/version gets one analysis job even with concurrent workers.
- Changed timestamps/markup/provenance alone do not generate another job.
- Structured new facts or grounded new primary-source quantities create an evidence version eligible for re-analysis.
  Unproved paraphrases after analysis are held (`needs_material_review`), not
  re-analyzed automatically and not discarded as a verified duplicate.
- Conflicting grounded claims, including narrowly matched numeric sentence
  frames, are retained with preferred primary-source values and block publication.
  This is not a universal semantic contradiction detector. Attribution is
  preserved for the model; no contested fact is declared certain.
- A later version cancels pending old-version previews. Current portfolio /
  watchlist membership is rechecked at preview delivery. Separate topic keys
  prevent wrong-topic dedupe from hiding the correct destination.

Identical syndicated reports can avoid repeated jobs. Independent paraphrases
without a shared strong reference may remain separate/held; no claim of perfect
real-world semantic dedupe is made from synthetic tests.

## AI and failure isolation

Luna remains unchanged. `CanonicalAnalyzer` accepts an explicit single-request
completion client. There is no local/Ollama fallback or production client in
this sandbox. Structured schemas, Hebrew checks, number/terminology grounding,
independent quality review and at most one editorial correction are retained.
Terminal quality failures are not re-run for identical evidence.

**One canonical analysis job is not one billable HTTP call.** Normally it is
analysis + independent quality review (2 calls); correction + review can add
2 calls. Removing this quality gate to claim one HTTP call would change quality
behavior and is not done. Transport/schema failures fail closed in this adapter;
no nested retry loop. Failed/unknown costs remain unknown rather than zero.

Provider I/O: HTTPS allowlist, public-IP DNS pinning, no redirects, 12-second
deadline, 1 MiB body bound, bounded collection parallelism (3), persistent
backoff honoring Retry-After, terminal configuration/auth failures. After three
transient failures the circuit waits at least an hour before another probe.
Evidence has its own persistent backoff/cache. One provider's failure does not
mark other providers failed. Collection and AI are separate entry points; tests
show a blocked AI call does not hold the event database transaction. No Position
Monitor/trading code is imported or modified by the pipeline.

SQL/Python metrics distinguish canonical jobs, HTTP calls, source versions,
unchanged polls, duplicate evidence, outcomes, queue age, provider health and
known/unknown cost. Provider contributions are recorded but event cost is
counted once. AI-cost figures in unit fixtures are simulated, not new spending.

## Provider access review (27 September 2026)

### Investing.com — implemented RSS adapter, disabled

Official [RSS directory](https://www.investing.com/webmaster-tools/rss) and
[feed](https://www.investing.com/rss/news.rss). Actual isolated GET/parse:
10 items, 0 normalized: all observed dates lacked a timezone, e.g.
`2026-09-27 14:48:32`. We do not silently assume UTC or renew publication time.
Observed transport/parse latency 0.516 s (earlier probe 0.547 s). No article scrape.

[Support](https://www.investing-support.com/hc/en-us/articles/360002357417-Use-our-data)
and [terms](https://in.investing.com/about-us/terms-and-conditions) do not provide
an unambiguous grant for this AI/translated-public-Telegram workflow.
Use the [official syndication request](https://www.investing.com/webmaster-tools/real-time-news-feed).
Need publication-time contract and appropriate redistribution permission.
RSS is free to access; no published numeric rate allowance was verified.
Configured 300-second cadence is a local default, not a claimed vendor quota.

### GlobeNewswire — implemented broad RSS adapter, disabled

Exact Public Companies feed discovered from the official
[RSS directory](https://www.globenewswire.com/rss/list):
`https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies`.
Native sandbox transport failed before HTTP status, after 3.031 / 3.094 s;
earlier ordinary directory requests timed out. No bypass attempted.

The official [newsfeed service](https://www.globenewswire.com/Home/About/Media-Relations)
describes royalty-free distribution and RSS/Atom delivery, with subscription /
technical terms obtained from media@globenewswire.com. Confirm our storage,
Hebrew AI transformation and public Telegram use with this service; public
reachability is not a contract. No numeric RPM/quota verified. Press-release
wire identity does NOT automatically certify every release as company-authored.

### PR Newswire — RSS adapter/schema tested with fixtures, disabled

[Official RSS directory](https://www.prnewswire.com/rss/) confirmed endpoint
`https://www.prnewswire.com/rss/news-releases-list.rss`.
[Terms](https://www.prnewswire.com/terms-of-use/) restrict redistribution and
AI/software use. Therefore no live content-feed collection/AI experiment was
performed. Need [publisher/partner permission](https://www.prnewswire.com/contact-us/become-a-partner/)
covering this workflow. No price or numeric rate limit for that license was
publicly verified. Do not treat RSS availability as approval.

### Benzinga — documented Newsfeed API adapter, disabled

[Official API contract](https://www.benzinga.com/apis/blog/mastering-the-benzinga-newsfeed-api/):
`GET https://api.benzinga.com/api/v2/news`, token auth, broad pages (100 items),
updatedSince overlap, persisted pagination/checkpoint, full body/teaser and
stock metadata. Credentials never enter event metadata. No credential used.

Requires **Benzinga Newsfeed API access**, not a Benzinga Pro UI subscription.
Full text, retained data, AI derivatives and public redistribution require the
appropriate agreement; contact licensing@benzinga.com per
[official docs](https://docs.benzinga.com/home). Full licensed product price and
numeric rate limits were not publicly verified: obtain a quote, do not invent one.
A supplier [AWS Marketplace basic tier](https://aws.amazon.com/marketplace/pp/prodview-xwgvhwowjmw3g)
lists **$0 access** for headlines/teasers/link only; credentials, applicable terms
and our redistribution rights still need confirmation. No AWS subscription opened.
The official `news-removed` endpoint is integrated: persisted withdrawal
tombstones block re-import and cancel pending publication, without deleting
historical evidence. Live credential/license verification remains outstanding.

### TipRanks — contract-mapped enterprise adapter, disabled

[Market News API](https://enterprise.tipranks.com/market-news/) is the relevant
product. Public pages do not disclose its authenticated endpoint/response
contract, numeric rate limits or price. Adapter maps contract-provided fields,
auth header and cursor, with mock validation; **not live-contract verified**.
Need licensed enterprise endpoint/schema/credential and rights for retained
data, AI transformation and public feeds; request vendor quote.

Do not substitute the retail/MCP service: [MCP terms](https://mcp.tipranks.com/terms)
restrict public redistribution/standalone archives. Its free-call quota is not
a license for this Telegram feed. No purchase or account change occurred.

### Existing sources / SEC

Existing SEC/Yahoo/Telegram/FinancialJuice/official bulk collector output is
adapted by `ExistingProvider` with checkpoint preservation. Callers must provide
isolated collectors/read-only records, not invoke production workers.
`SECEvidence` can enrich an event discovered by any provider when an exact filing
reference matches the verified company CIK. It reuses audited Phase 1 transport
and extraction helpers, NOT Phase 1 state/prepare/review. Cache is canonical.

Current extraction coverage is structured Form 4 plus supported inline-XBRL
filing paragraphs; it does not crawl all exhibits or flatten financial tables.
Unknown accession/company, ambiguous evidence, oversized content, unsupported
forms/tables fail closed. This limitation must be addressed separately if broader
SEC facts are needed. No fabricated filing links or fuzzy issuer search.

## Offline DELL #420 / HOOD #426 forensics

Only pre-existing `.runtime/reports/news-evidence-phase1-final.jsonl` and
`news-evidence-ai-comparison.jsonl` were inspected; no AI rerun or public replay.

DELL: saved SEC extraction verifies company/filing, contains 1,166 characters
including quantities, prices and qualifying footnotes. It is below the old
2,000-character excerpt limit; no observed extraction/truncation failure in the
saved artifact. Enriched run completed four schema-valid calls then failed final
quality. The rejected draft and exact per-check verdict were not retained in
that historical report, so number-grounding vs language/editor/model cause
cannot be proven. Recorded old experiment cost was $0.001156175 (not new spend).
Canonical attribution preserves these facts and avoids per-outlet reruns, but
no independent additional source for this exact DELL event is in the saved
sample; cannot claim multi-source input would make it pass.

HOOD: 1,997-character verified excerpt retains conversion/sales and 10b5-1
qualifications. Saved enriched result: related=true, relevance=.93,
materiality=low, sentiment=neutral. It describes a planned insider sale, not
evidence of changed company fundamentals; non-publication is valid under the
existing gates. Old experiment: 3 calls, $0.0006626, including thesis comparison.
No new independent evidence exists in this sample to justify raising materiality.

## Validation and rollout recommendation

Tests: `service/server/tests/test_news_events.py`,
`service/server/tests_pg/test_news_events_pg.py`.
They cover cross-source canonicalization, concurrent one-job claims, material
updates, conflict/identity protection, all three topic destinations, SEC from a
different discovery provider, license/recency/unsupported prechecks, retries,
checkpoints, database availability during blocked AI, restart/unknown outcomes,
terminal quality, strict JSON and topic/version duplicate prevention.

Commands:

```text
python scripts/test_news_isolated.py service/server/tests
python -m pytest service/server/tests_pg -q
npm --prefix service/frontend run build
python scripts/news_event_sandbox.py --help
python scripts/probe_news_event_feeds.py --network
```

Synthetic four-outlet same-evidence case: 1 canonical event, 1 quality job,
3 duplicate jobs avoided. With unchanged 2-call quality path this represents
6 avoided mock HTTP calls compared with analyzing 4 rows separately; **not a
measured production saving**. Real AI spend during this Phase 2 turn: $0.
No real AI latency measured and no production cost projection inferred.

Local synthetic ingest timing (30 independent fixture events, 120 source
versions): 30 canonical events, 90 duplicate-evidence versions; median 66.128 ms
and p95 75.802 ms per four-source event on Windows/SQLite. This excludes model
and network time and is NOT a production throughput measurement.

Recommended next trial is **isolated/nonpublishing** with existing authorized
collectors + SEC exact-event evidence. No new provider is yet cleared for a
public trial: Investing timezone/rights, Globe access/rights, PR license,
Benzinga license/credential, TipRanks contract/credential.
Do not merge this branch into main: main auto-deploys production. Preserve Phase
1 measurements and scheduled live-market validation until explicit approval.
# Verified press-feed access recovery

A previously successful, currently enabled and rights-approved press feed may
perform one delayed recovery probe after a terminal HTTP 403, at least one hour
after its last attempt. The incident marker is persisted before I/O, including
across interruption/restart; another denial remains terminal, not an endless
retry. Unverified feeds, credentials/rights errors, unsafe endpoints and invalid
metadata are not unblocked. A recovery timestamp fences out the outage backlog.
Successful collection clears stale HTTP/error/backoff telemetry through the
existing collector and reports the transition to Admin only. No alternate host,
IP, scraping, bot impersonation or licensing bypass is used.
