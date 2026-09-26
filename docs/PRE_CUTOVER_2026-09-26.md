# Pre-cutover rehearsal — 2026-09-26

No production cutover. Windows production and Pages routing remain unchanged.
Cloud Telegram is disabled; credentials/session/routing are prepared in root-only
`deploy/cutover-pending`, not mounted in the running services.

## Active state

Read-only consistent SQLite snapshot: 2026-09-26 10:25:54 UTC. Local writers were
NOT stopped. This rehearsal cannot replace a fresh frozen cutover snapshot.
Imported into NEW PostgreSQL `ai_trader_precutover`; old staging DB preserved.

- Primary 8/8: DELL, HCA, HPE, HOOD, CRWD, ANET, MRVL, MSTR.
- Shadow 5/5: HOOD, TMO, CRWD, MRVL, MSTR.
- Every preserved column compared: entry, original/remaining quantity, TP state,
  current/original stop, fills, fees/P&L, account/cash, settings, 9 monitor cursors.
- 12 fills preserved. No new fills or Telegram events across restart/monitor.
- Replay of 9 saved checkpoints rejected without mutation.
- Three adopted Legacy positions retain unverified flags; no history invented.
  Old news/target-revision provenance omitted; current execution levels retained.
- A second online local snapshot matched staging after restart.

Saturday monitoring: 9 tickers, zero new bars, zero errors, ~70 ms. This is NOT a
live weekday TP/SL hit. Isolated PostgreSQL tests cover actual lifecycle execution.

Actual GitHub encrypted Recovery-State artifact downloaded and restored into
new `ai_trader_precutover_restore`; all preserved rows match, zero old news/outbox.
Artifact 10,245 bytes; 35 retention slots ~358,575 bytes plus predeploy and Git
history. Size monitoring remains enabled. Decryption identity stays off-server.

## AI and costs

Existing key: monthly $20 Guardrail; Allow Only `openai/gpt-6-luna`; Auto Top-Up OFF.
News/summary/final model settings remain separate, all currently Luna.
`ai_budget.py` fails closed on missing usage or exhausted budget before cloud
calls/retries and publication. No DB transaction spans provider IO; bounded HTTP
timeouts. Provider Guardrail remains authoritative for concurrent/in-flight caps.
Monitor does not call the budget checker. Persistent internal warnings at
$15/$18/$20 live in `scanner_settings`; current state in `scanner_service_status`.
Threshold tests use mocks, not spending. Usage observed: $0.12765933.

Hetzner email cost warning verified $20 (not a hard cap). Only CX33/Falkenstein
and assigned IPs: $9.99 + IPv4 $0.60 = $10.59/month, account VAT 0%.
No paid volumes, snapshots, additional servers or load balancers.
Infrastructure plus full AI cap: $30.59 before payment fees/excess traffic.

Linux build, PostgreSQL restart, app recreation, readiness and actual remote
restore passed. Public HTTPS health 200. Load 300/300 at concurrency 12:
p50 17.71 ms / p95 70.34 ms. Host ~1.23 GB used with regression running.

Initial local suite: 382 passed +14 subtests. Initial PostgreSQL suite: 106 passed
+8 subtests; one inherited disabled staging TP-alert flags. Its fixture now
explicitly enables mocked alert scenarios, and targeted rerun passed. No live
Telegram settings were enabled to make tests pass. Final CI is recorded in GitHub.

## Handover still requires explicit approval

Hold cloud trading/news workers after validation to prevent independent rehearsal
state advancing alongside local production. API/backup can stay available.
On approval: stop local writers/reader; capture fresh final snapshot; import into
another clean migrated DB; compare; switch cloud DB; set
`TELEGRAM_NEWS_NOT_BEFORE` to the final UTC handover time before enabling delivery.
This boundary suppresses older/missing-date news notifications (including late
edits retaining an old publication date), not collection/analysis or trade events.
It prevents rebroadcast after intentionally omitting historical news dedupe state.
Then activate prepared credentials/roles, update Pages API URL, verify CORS/UI and
Telegram. Never enable the same reader session on both hosts concurrently.
Keep the frozen local DB for rollback. Never silently merge two advancing copies.
