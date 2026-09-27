# Canonical news rollout (schema 005)

Implementation branch: `codex/cloud-news-events-cutover`, starting at `4c23993`.
This document is a runbook, not evidence that production deployment passed.

## Runtime boundary

- `NEWS_EVENTS_RUNTIME=true` enables the DB-controlled selector. Migration 005
  creates `ne_control` in **phase1** mode. No implicit activation on migration.
- Existing collectors and the sole Telegram reader keep the existing provider
  checkpoints/backoffs. Their ingestion calls normalize into canonical events
  when selected. Final stock-review inputs and trading code are unchanged.
- Discovery → deterministic verification → missing-evidence SEC completion →
  canonical version claim → Luna source analysis → independent quality review →
  current membership routing → existing atomic Telegram outbox.
- One analysis **job** normally makes **two billable requests**, not one. One
  editorial correction/review is allowed; transport does not add nested retries.
  Terminal/ambiguous failure is held instead of rerunning a potentially billed job.
- Global OpenRouter budget/pacing client and `ai_call_usage` remain authoritative.
  `ne_ai_call_links` links individual ledger calls to event/version/stage; metrics
  must never be added to that ledger's totals a second time.
- `scanner_news` is a UI/six-hour-review projection without legacy AI jobs.
  The scanner's independently collected candidate input is not replaced.
- Outbox enqueue and dispatch check active mode, version, membership, age, rights,
  conflict, and cutover epoch. Old-path queued news is fenced, not replayed.

## Controlled release and recovery

Run `deploy/migrate-news-events.sh FULL_SHA --approved-schema-4-to-5` as the
existing operator only after exact-SHA CI/readiness success and main promotion.
It obtains the existing deployment lock, builds the exact image, creates an
encrypted off-server Recovery-State backup, stops writers, runs numbered 005,
starts API/Monitor, switches news while both publishers are stopped, and checks
health and portfolio hashes. It never starts a local worker or rewinds a DB.

Because schema 4's entrypoint rejects schema 5, **news rollback after a committed
migration uses the tested Phase 1 compatibility path on the schema-5 image**,
not the unmodified schema-4 image. Before migration commit the prior image can
be restored directly. If the schema-5 API itself is broken, operator recovery is
required: do not falsely claim that a news-mode switch repairs arbitrary API bugs.

For manual news rollback, stop scanner/telegram, run
`python -m news_events.cutover phase1 --reason operator_rollback`, restart those
roles. Publication fence advances; no historical backlog broadcast. The existing
auto-deploy schema-version guard stays intact.

Private operations check runs in the existing Telegram operations loop. It
fences canonical news and resumes Phase 1 on detected topic/outbox integrity,
per-event cost >$0.05, last-hour cost >$0.25, pending queue >300 or >1h, or Monitor
failure/staleness >15min. These are operational brakes, not weaker news/trading
thresholds. Semantic wrong-company matches cannot all be detected automatically;
ambiguous identities/conflicts are held by the deterministic pipeline.

## Provider audit, 27 September 2026

- **Investing**: [official RSS directory](https://www.investing.com/webmaster-tools/rss)
  and [syndication](https://www.investing.com/webmaster-tools/real-time-news-feed).
  Cloud DNS/TLS/HTTP200/XML parse passed (10 items, 0.174s). `pubDate` values such
  as `2026-09-27 16:01:15` have **no timezone**. Website clock is not an RSS contract.
  Disabled pending authoritative timezone and permitted syndication/AI workflow.
- **GlobeNewswire**: [official public-company feed directory](https://www.globenewswire.com/rss/list),
  [media relations](https://www.globenewswire.com/Home/About/Media-Relations).
  Cloud DNS and TLS1.3 passed; HTTP response timed out after 8.133s. No proxy or
  bypass attempted. Royalty-free newsfeed marketing is not treated as proof of
  every AI/redistribution use; media@globenewswire.com can confirm feed license.
- **PR Newswire**: [terms](https://www.prnewswire.com/terms-of-use/) require written
  owner approval for redistribution/use of contributed content. Disabled pending
  permission covering retained metadata, AI processing and attributed summaries.
  [Partner application](https://www.prnewswire.com/contact-us/become-a-partner/).
- **Benzinga**: [official APIs](https://www.benzinga.com/apis/) and
  [API documentation](https://docs.benzinga.com/home). Full adapter exists but no
  licensed token. The site's Free Stock News RSS link returned 404; Free API Key
  points to a malformed URL. Contact licensing@benzinga.com for News API access,
  retained metadata, AI use, redistribution scope, price and RPM. No account,
  subscription, fee, or unverified license was accepted.
- **TipRanks**: [enterprise Market News](https://enterprise.tipranks.com/market-news/).
  Requires provider-supplied enterprise endpoint/response contract, credential and
  redistribution/AI license. Pricing and quotas are not publicly verified. No
  undocumented endpoint or consumer/MCP license is substituted.

Three broad alternatives were checked; none meets the explicit free/public-use
permission requirement without further approval:
[Alpaca redistribution FAQ](https://alpaca.markets/support/redistribute-alpaca-api),
[Finnhub terms](https://finnhub.io/terms-of-service) (written redistribution approval,
including derived results), and [Marketaux terms](https://www.marketaux.com/tos)
(personal-use restrictions; API syndication/AI scope needs clarification).
No paid resources or subscriptions were created.

New providers remain independently disabled. Server-only
`NEWS_EVENTS_PROVIDERS`, `NEWS_EVENTS_PROVIDER_APPROVALS` and optional credential
variables control licensed enablement. An approval reference cannot repair a
missing timezone or undocumented enterprise contract.

## Validation limitations

Mocked PostgreSQL E2E does not establish real public delivery. Live release
acceptance must separately record natural post-fence events, actual generation
cost, route/delivery receipts, unchanged Monitor and restart results. Zero fresh
SEC filings on a Sunday is not an enrichment E2E PASS. No fake public news and no
deliberate replay are permitted. Historical Phase 1 observation metrics retain
their start time; post-cutover canonical metrics are a separate series.
