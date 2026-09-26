# Phase 1: cloud readiness (not a production deployment)

The existing scanner, thresholds, limit **6**, single/staged strategies, targets,
fees and execution/accounting functions are retained. No live account was migrated.
The local Windows service and public Pages configuration must remain unchanged in
this phase. The following commands are a **future isolated staging runbook**.

## Services and resource envelope

One non-root Python 3.11 Linux image has `api`, `scanner`, `monitor`, `telegram`
and one-shot `migrate` commands. API background tasks are forced off. Worker tasks
are explicitly allowlisted; the original social/crypto tasks are not started.

| Service | RAM ceiling | CPU ceiling | Notes |
|---|---:|---:|---|
| PostgreSQL 17 | 2 GiB | 1.25 | 512 MiB shared buffers, 80 connections, high CPU shares |
| Position monitor + quote refresh | 768 MiB | .75 | Separate process; high CPU shares; no AI |
| Scanner/news/Telegram reader | 2 GiB | 1 | Low CPU shares; external AI only |
| API | 768 MiB | .5 | One HTTP worker; no background loops |
| Telegram dispatcher/status | 512 MiB | .25 | Persistent outbox; independent from monitoring |
| Caddy | 192 MiB | .25 | HTTPS; only public ports 80/443 |
| Hourly encrypted backup | 384 MiB | .25 | Optional `backups` profile; enable before cutover |
| Migration (one-shot) | 512 MiB | .5 | Must finish before API/worker startup |

Normal service ceilings total about 6.56 GiB, leaving ~1.44 GiB for the host.
CPU quotas can total more than four cores; CPU shares favor DB and monitor during
contention. This is a starting envelope, **not a CX33 load-test result**. Docker
resource quotas are not real-time guarantees. Disk capacity must cover PG growth,
WAL, caches and local logs; no local LLM or model weights are used.

## PostgreSQL and process ownership

`migrations.py` records numbered versions in `schema_migrations`, with a global
session lock for migration ownership. Version 001 bootstraps the original schema;
002 adds the active import manifest and cloud indexes. After this baseline, add
new numbered files rather than changing deployed migrations. API and worker cloud
entrypoints **do not run schema initialization** and refuse unknown versions.

The adapter handles natural-key tables without blindly appending `RETURNING id`,
SQLite scalar MIN/MAX/Julian-date expressions, and named/positional row access.
Short existing write transactions acquire a transaction-scoped PG advisory lock,
preserving SQLite's serialized accounting semantics. Queries have bounded connect,
statement, idle-transaction and lock timeouts. This is bounded connections, not a
connection pool. Slow external calls must be outside database transactions.

Each worker role owns a different PostgreSQL **session advisory lock**. A second
worker of the same role fails closed, while monitor and scanner can coexist. Every
new worker DB connection verifies ownership; a heartbeat also checks the dedicated
lock connection. Loss of ownership terminates the complete process, including its
threads. On shutdown the process exits before releasing the lock: incomplete DB
transactions roll back and durable cursors/outbox are recovered. Deploy must stop
old owners before starting replacements; do not run rolling overlapping writers.

Telegram claim uses `UPDATE ... RETURNING` with `FOR UPDATE SKIP LOCKED`; expired
claims recover. Telegram delivery is **at least once**, not provably exactly once:
if a send succeeds and acknowledgement is lost, a retry may duplicate that message.

Health checks verify DB/schema, stable scanner/account identity, API response or
role heartbeat/task survival. Monitor readiness also checks fresh progress and
provider errors (market-closed is valid). Docker marks unhealthy containers but does
not restart them solely because of health status; fatal role/lock failures exit and
the restart policy handles them. Dashboard provider statuses remain separate from
process health. Single-server hardware/storage failure still stops all services.

## Server-only configuration

Copy `deploy/runtime.env.example` to ignored `deploy/runtime.env`. It deliberately
disables scanners and real notifications for the initial staging boot. Copy and
review the **existing non-secret settings** (including session policy, thresholds,
exit strategy, news cadence, simulation fees and TP settings) before enabling any
worker. The template is not a replacement for the existing configuration.

Create `deploy/secrets/` outside Git, directory 0700, files 0600, readable by UID
10001 for app-mounted secrets. Docker Compose file secrets are bind mounts, not an
encrypted vault. PostgreSQL initialization secrets must also be readable by its
entrypoint. Never put any secret in build arguments, runtime-config.json or Pages.

Required secret files:

- `postgres_password`: cluster-admin password; not used by the application.
- `app_password`: non-superuser `ai_trader` password; no CREATE ROLE/CREATE DATABASE.
- `database_url`: app connection string using host `postgres`, database `ai_trader`.
- `openrouter_key`: provider key; only server processes receive it.
- `scanner_token`: must match the preserved scanner agent token; do not rotate just
  one side. The active snapshot contains sensitive authentication parent rows.
- `telegram_bot_token`, `telegram_api_id`, `telegram_api_hash`: the latter two and
  authorized reader session are needed only for Telegram news ingestion. Empty
  files may be mounted while those optional features are disabled.
- `age_recipient`: **public** encryption recipient, not the private decryption key.
- `recovery_deploy_key`: write SSH deploy key scoped only to the private recovery repository.
- `github_known_hosts`: pinned public GitHub SSH host keys.

Set non-secret `PUBLIC_API_HOST`, `APP_IMAGE` (prefer tested immutable digest),
`RECOVERY_GITHUB_REPO=owner/private-backup-repo`; exact GitHub Pages CORS origin is
in runtime.env. No public PostgreSQL port, Redis or local PC tunnel is required.

AI uses explicit `OPENROUTER_NEWS_MODEL`, optional `OPENROUTER_SUMMARY_MODEL` and
`STOCK_SCANNER_FINAL_AI_MODEL`; no fixed cloud model. All active cloud AI paths
(news, position news, translation, summaries, final review) route to OpenRouter.
Missing keys/model/provider failure never falls back to localhost/Ollama. Final
review preserves strict JSON schema, one shared retry/repair budget and telemetry.
The news transport validates supplied JSON schemas and allows at most one transport
retry/repair. Existing editorial/relevance/news-job retry policies are unchanged.
Real model quality, provider schema support and paid usage still need the separate
approved benchmark; this phase does not make paid calls.

## Active Portfolio Snapshot

`service/server/active_snapshot.py` exports read-only SQLite data from one consistent
transaction. At cutover, **stop all local writers/supervisor/autostart first**; the
CLI requires explicit `--writers-stopped` acknowledgement, not a claim that it can
detect every remote/local process automatically.

Included, with original identifiers and field values:

- All open primary **and open Shadow** trades, including managed legacy positions.
- Entry, original/remaining quantity, original R/stop, current stop, TP1/2/3 and
  fractions, strategy, immutable settings JSON, timestamps, last bar, marked P&L.
- All fills for those trades (entry, partial TP/SL/SELL), cumulative realized P&L,
  fees/slippage, event keys, target revisions and legacy adoption evidence.
- Required original positions/agents/signals and scanner signals/entry orders.
- Original entry thesis and embedded news/technical context inside those signals;
  the separate historical news/feed tables are not copied.
- Scanner cash/account totals and original agent wallet (legacy accounting stays
  separate), required FK parents, operator rows and active strategy setting.
- Price cursors: old bars and already executed targets must not be replayed.

Excluded: unrelated closed trades, scan/candidate/AI telemetry history, pending
orders/signals, old news/alerts/outbox, old cooldowns, weekly report state. Old news
watchlist is **not** portfolio state: reconfigure explicitly if desired. Topic IDs
remain environment routing config; old pinned message IDs are not imported.

Validation rejects corrupt checksums, nonfinite/invalid quantities/targets,
unreconciled native fills, unsupported strategies/shorts, pending parent orders,
missing required parents, and original open positions that have no managed trade.
Legacy historical entry evidence is retained as unverified, never invented.
Import requires an empty migrated database and no role owners, executes atomically,
advances sequences, compares every preserved row before commit and refuses repeat
imports. It schedules a fresh position-news review; no old Telegram messages replay.

**Cash baseline:** current cash/initial cash/cumulative P&L are copied unchanged.
Because closed history is intentionally absent, an explicit opening audit adjustment
in `active_snapshot_baseline` reconciles preserved cash against retained fills. This
only informs read-only accounting verification; execution and account mutations are
unchanged. Trade statistics represent retained/new trades, not full historic results.

Example (private `.runtime` or encrypted transfer location; never Git):

```powershell
.venv/Scripts/python.exe service/server/active_snapshot.py export --source service/server/data/clawtrader.db --snapshot .runtime/portfolio.active-snapshot.json --writers-stopped
.venv/Scripts/python.exe service/server/active_snapshot.py validate --snapshot .runtime/portfolio.active-snapshot.json
```

Then, on **isolated staging only**, after provisioning secrets and backing up the
source, run the migration job, import with a private read-only snapshot mount, and
start API. Do not start any worker until the import/identity/config checks pass:

```sh
docker compose -f deploy/compose.yml build
docker compose -f deploy/compose.yml up -d postgres
docker compose -f deploy/compose.yml run --rm migrate
docker compose -f deploy/compose.yml run --rm --no-deps --entrypoint python \
  -v /private/portfolio.active-snapshot.json:/snapshot.json:ro api \
  /app/service/server/active_snapshot.py import --snapshot /snapshot.json --writers-stopped
docker compose -f deploy/compose.yml up -d api caddy
# Only after separate staging approval/configuration: scanner monitor telegram.
```

During this phase do not run these commands against the live portfolio. For staging
with imported real state, keep Telegram disabled and prevent staging from advancing
the live portfolio; use cloned state and explicitly mocked feeds for execution tests.

## Volumes and backup

`postgres_data` is authoritative. `runtime` stores regenerable history/universe/news
and chart caches, not cloud scanner cooldown state (now PostgreSQL). `reader_session`
contains only the single-owner Telethon login session; export it after reader stops,
preserve restrictive permissions and encrypt transfer. Windows DPAPI encrypted
copies cannot simply be reused on Linux. Never put the session in the Docker image.
`logs` are capped; Caddy volumes hold private TLS state. Old Windows PID/lock/tunnel
files are not migrated. Earnings GitHub Actions remain independent; no weekly state
is copied into PostgreSQL.

Discarding old news deduplication state means a previously published story that is
still inside the provider lookback window can be collected/alerted again. Dropping
old outbox rows prevents queue replay, not this re-collection. Review first-feed
behavior and old pinned Telegram cards at staging/cutover; do not claim historical
deduplication after deliberately discarding its evidence.

The updated user-approved backup is **active Recovery State only**, gzip + age to
a separate private GitHub repo. No full DB/news/history upload, Storage Box or R2.
Retention: 24 hourly / 7 daily / 4 weekly + latest predeploy. Git history retains
older ciphertext; its growth is monitored separately. `backup.sh` invokes the new
recovery exporter, and `redeploy.sh` requires a successful predeploy backup.
See [RECOVERY_STATE_BACKUP.md](RECOVERY_STATE_BACKUP.md) for exact contents,
exclusions, secret handling and the `recovery_state.py` restore procedure.
The old `restore.sh` is only a full-dump compatibility utility, not the current
recovery format. Successful hourly recovery implies up to ~1 hour active-state RPO,
worse during outages; **no WAL/PITR**. Losing the offline age key makes backups
unrecoverable. Authentication/services must be provisioned separately at restore.

## Validation / release gate

- `python -m pytest service/server/tests -q`
- With an isolated PG URL: `python -m pytest service/server/tests_pg -q`.
  These tests create/drop only unique `test_*` schemas; HTTP is blocked. They reuse
  the existing lifecycle and news suites against PostgreSQL, including concurrency,
  restart replay, partial targets, Shadow separation, snapshot parity and encryption
  round-trip (requires pg_dump/pg_restore/age tools). Missing PG/tools is a **skip**,
  not successful verification.
- `npm --prefix service/frontend run build`.
- `.github/workflows/cloud-readiness.yml` adds PostgreSQL and Linux image validation,
  **no image push, deployment, production credentials or live Telegram**.

Before calling staging ready: build/run the Linux image, validate secret-file/volume
permissions, check process failure/restart behavior, restore a remote encrypted backup,
test HTTPS/CORS/Pages against an isolated backend and benchmark configured OpenRouter.
Do not switch public Pages BACKEND_URL or restart production during this phase.

### Local evidence, 2026-09-26

- Backend/scanner regression: **376 passed**, 10 subtests; two pre-existing
  Starlette/httpx/AnyIO deprecation warnings.
- Real PostgreSQL 17.6: **99 passed**, 8 subtests in the combined lifecycle/news/
  snapshot/backup run; **one additional API dashboard test passed separately**
  (100 PostgreSQL tests now collected). No skipped PostgreSQL/encryption cases.
- New cloud unit checks: 8 passed (included in the 376, not extra).
- Frontend TypeScript/Vite production build passed; Compose official CLI `config`
  validation passed using dummy host/backup configuration, no real secrets.
- Read-only active source validation: 8 primary open trades (3 managed legacy),
  5 open Shadow trades, 9 price cursors, 12 retained fills; no unmanaged original
  positions detected. Source data was neither exported to a persistent file nor
  imported; all import tests used synthetic isolated portfolios.
- Test PostgreSQL was a separate loopback-only temporary instance. Extra test
  libraries were installed in `.local-tools/cloud-python`, not the live venv.
- Linux image **build/run not performed**: no Docker Engine available on this
  workstation. CI workflow added but not pushed/executed on GitHub. No Hetzner,
  HTTPS staging, off-server upload, live OpenRouter or live Telegram verification.
