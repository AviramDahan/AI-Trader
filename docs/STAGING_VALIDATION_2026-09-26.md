# Staging validation — 2026-09-26 (not a production cutover)

## Recovery-state follow-up — current checkpoint

- **PASS:** separate private `AviramDahan/AI-Trader-Recovery` repository created;
  active-state-only gzip+age uploads from Linux, scoped write deploy key, hourly
  scheduler, 24/7/4 retention and latest predeploy checkpoint. Full DB/news/history
  are not uploaded. No Storage Box/R2 created. Decryption identity stays off-server.
- **PASS:** actual encrypted GitHub file downloaded, decrypted locally and piped
  into a fresh `ai_trader_recovery_verify` PostgreSQL DB. Preserved fields, cash,
  schema, empty news/outbox verified and authentication regenerated. Staging has
  **zero** trades; this does not claim that the eight live positions were imported.
- **PASS:** separate nonempty synthetic encrypted restore covers primary + Shadow,
  TP1 partial fill, remaining quantity, cash/fees, cursor replay and identical next
  execution. Current fixture: 6,320 JSON / 1,882 gzip / 2,082 encrypted bytes.
- Current actual empty-account snapshot with execution policy: **897 bytes**
  encrypted (1,484 JSON / 697 gzip). 35 slots at that size: **31,395 bytes**;
  plus predeploy: 32,292 bytes. Synthetic nonempty fixture: 72,870 bytes for 35.
  These are content-size projections, not a measurement of the future live eight.
  Local Git metadata/history currently 38,857 bytes; history is NOT bounded by
  retained files. A 100 MiB warning is logged/status-exposed; no automatic rewrite.
- **PASS:** one user-approved Hebrew Staging message delivered via real PostgreSQL
  outbox to the existing Telegram community's general chat, then seen in browser.
  Immediate second dispatch sent zero messages. Temporary test schema removed;
  token existed only in the isolated container's memory/SSH stdin, never image/Git.
  Production delivery remains disabled in all persistent staging workers.
- **PASS:** removed deliberate internal-only scanner network overlay, verified
  outbound HTTPS and API DNS, reset only staging scheduling. Completed real scan:
  universe/data 518/518, technical 398, news shortlist 25, AI 0, signals 0.
  Saturday freshness checks skipped AI; no confidence/risk filter was weakened.
- **PASS:** Linux image rebuild, guarded predeploy backup, migrations, app redeploy,
  and PostgreSQL container recreation with persistent volume. All seven persistent
  containers healthy; unchanged empty account and no duplicate fills.
- **PASS:** local 377 tests + 10 subtests; full Linux/PostgreSQL 104 tests + 8
  subtests; latest recovery-specific rerun 4/4 (adds runtime-policy mismatch case).
  Frontend TypeScript/Vite build passed. Known deprecation warnings only.
- **PASS:** GitHub CI run https://github.com/AviramDahan/AI-Trader/actions/runs/36233170195
  on branch `codex/cloud-staging-recovery`: **105 PostgreSQL tests + 8 subtests**,
  **377 backend tests + 10 subtests**, Linux image and frontend build. Initial CI
  failures were missing PGDG client-17 and the runner selecting client-16; fixed
  by official PGDG installation and explicit version-17 binary paths.
- Latest real role probes rejected second scanner/monitor/Telegram owners.
  Repeated stalled-AI + CPU-load synthetic monitor test: **123.18 ms**, PASS.
- Latest post-restart load: 300/300 `/health`, concurrency 12, p50 17.46 ms,
  p95 69.53 ms, max 72.49 ms. This is a short health load, not a full-market soak.
- Host idle after restart: 1,118 MiB used, 6,632 MiB available. During real scan +
  integration tests: ~1,629 MiB used; scanner reached its 1 CPU limit and 368 MiB.
  Monitor ~78 MiB remained independent. Disk ~5.9/75 GiB, 9–11 DB connections.
- Cost audit via Hetzner API and console: one CX33 $9.99 + one IPv4 $0.60; free
  IPv6/firewall. Zero volumes, snapshots, load balancers, buckets or Storage Boxes.
  Account pricing currently reports 0% VAT and 20 TiB included traffic.
  Baseline $10.59 + AI usage up to $20 = **$30.59/month**, excluding payment fees
  and exceptional traffic overage. No automatic top-up. Current OpenRouter key
  usage $0.00746939 (includes live staging activity, not just the 3 smoke calls).
- Real news processing now succeeds (18 completed jobs at the observation), with
  one separate `news_quality_rejected` job retained in retry/error state. It was
  not published and no quality filter was bypassed; not every article is accepted.

Remaining before production approval: provider/model quality on representative
inputs, key rotation for the explicitly reauthorized chat-exposed key, independent
safe copy of the offline recovery identity, production secrets/session/routing,
75%/90% internal budget notifications and model allowlist. Hetzner $20 email warning
is currently off; action-time confirmation requested. GitHub image/deploy automation
has not yet replaced the tested server deployment script. No Pages cutover and no
live portfolio import have been performed. Historical checkpoint below is retained
as evidence of earlier measurements, not the current list of completed gates.

---

## Earlier checkpoint (superseded where noted above)

## Actual deployment

- Hetzner CX33, Falkenstein, Ubuntu 24.04: 4 vCPU / 8 GB / 80 GB.
- Server plus IPv4: USD 10.59/month before tax. No extra paid storage created.
- Key-only `trader` SSH; root/password login disabled; provider and host firewall.
- Docker Engine 29.8.1 / Compose 5.5.1; application image built on Linux.
- HTTPS health endpoint: https://2-28-100-77.sslip.io/health (HTTP 200).
- Exact GitHub Pages CORS origin verified. Public Pages was NOT switched.
- PostgreSQL has no published host port; schema migrations 001/002 applied.
- API, monitor, Telegram dispatcher and Caddy healthy. Telegram has no bot secret
  and sending is disabled: process health is NOT proof of Telegram delivery.
- Scanner is running in a deliberate **internal-network-only outage test** using
  server-only `deploy/staging-outage.yml`. Provider/scan errors are expected;
  healthy process heartbeats do NOT mean successful scans. Do not call this a
  complete live scanner deployment. Live feeds are not enabled by this report.
- Empty isolated staging paper account; zero trades/fills. No active portfolio
  import, no production worker shutdown, no real-money trading.

## AI smoke test

Same messages, schema and validators as the earlier Gemma smoke test. No market
data, signals or trading writes. OpenRouter `openai/gpt-6-luna`, 512 output-token
ceiling, reasoning disabled. `temperature` omitted because the provider's supported
parameter list excludes it (the preliminary request with it returned HTTP 404;
this was a request capability error, not a schema failure).

- Three valid requests: **3/3 PASS**, parsed and schema-validated without repair.
- Latency: 1.116 / 1.157 / 1.239 seconds.
- Each: 84 input tokens, 35 output tokens, zero reasoning tokens, USD 0.0000259.
- Luna total USD 0.0000777. Earlier Gemma tests USD 0.00027254.
- All AI test usage reported by OpenRouter: **USD 0.00035024**.
- Default key fingerprint matched the key assigned to the USD 20/month Guardrail.
  The key itself also has a separate USD 100 lifetime limit; the monthly Guardrail
  is the relevant restriction. Auto Top-Up was verified disabled.
- This is a connectivity/format smoke test, NOT evidence of stock-analysis quality.
  Luna is configured temporarily for news, summaries and final review in staging;
  separate task model settings remain available. MiniMax was not needed/tested.

## Tests actually run

- Local backend/scanner regression: **377 passed, 10 subtests**, two existing
  deprecation warnings. Frontend TypeScript/Vite build passed.
- Real Linux/PostgreSQL integration: **100 passed, 8 subtests**, one deprecation
  warning. Dedicated `ai_trader_test` database, HTTP blocked and synthetic data.
- Additional `test_price_execution_completes_while_ai_is_stalled`: PASS, including
  a repeat under a one-core CPU load. A synthetic price bar completed in 154.646 ms
  while the mocked OpenRouter call remained stalled, then timed out.
- Existing integration coverage includes atomic concurrent outbox claims, role
  locks, replay/duplicate fills, partial exits, Shadow isolation, snapshot parity,
  news scheduling and real pg_dump -> age -> decrypt -> pg_restore round-trip.
- A real second monitor container was rejected with `role_already_owned:monitor`.
- API/monitor/Telegram force-recreate and PostgreSQL container force-recreate
  preserved the volume, account and zero-trade/zero-fill state. Workers recovered
  from lost database sessions. Synthetic duplicate-execution coverage is in tests;
  there were no live staging positions to exercise on the container restart.
- API load: 300/300 successful `/health` requests, concurrency 12, 0.787 s total,
  p50 14.54 ms, p95 71.8 ms, max 91.56 ms. This is a short health-endpoint test,
  not sustained full-universe/real-position load validation.
- Initial integration run used a separate schema in the staging DB and conflicted
  with database-scoped advisory role locks. It was stopped and rerun successfully
  in a separate DB. Never run ownership tests alongside services in the same DB.

## Measured resources (snapshots, not capacity guarantees)

- Host approximately 1.1 GB used, 6.6 GB available; disk 4.5 GB used / 75 GB.
- API ~104 MiB; monitor ~78 MiB; dispatcher 78–92 MiB; scanner ~88 MiB;
  Caddy 11–13 MiB; PostgreSQL 58–162 MiB. Ten DB connections during tests.
- CPU load container reached ~100% of one core; monitor health remained valid.
- Today was market-closed. Real quote/TP-SL monitoring of the eight active
  positions was deliberately not tested or imported.

## Remaining gates — NOT ready for cutover

- Hourly off-server backup destination/retention/upload/remote restore not yet
  configured. BX11 in Helsinki quoted at USD 4/month; purchase approval requested.
  Current encrypted restore test is on-server; it does not prove remote backup.
- Complete live scanner/provider testing and final-review quality validation.
- Dedicated Telegram test destination / live test delivery, not production group.
- Model allowlist and internal 75%/90% budget alerting remain outstanding.
- Hetzner USD 20 cost alert and GitHub image/deploy pipeline remain outstanding.
- Replace the chat-exposed OpenRouter key before production (its temporary use
  was explicitly reauthorized). Provisioning token remains private until setup
  completes, then revoke if unnecessary.
- Do not switch Pages, import active state or stop local production yet.
