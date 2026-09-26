# Active Recovery State (not a database archive)

The staging backup is a separate **private** GitHub repository:
https://github.com/AviramDahan/AI-Trader-Recovery . PostgreSQL remains the only
live source of truth. No news/history, logs, caches, pending signals/orders or
Telegram outbox is uploaded. GitHub does not run the application.

## Content and safety

`recovery_state.export_postgres()` reads one PostgreSQL REPEATABLE READ snapshot.
It includes open primary and Shadow trades, required parent signals/orders,
entry/remaining quantities, fixed original risk, all target prices/fractions,
current stops, completed partial fills, relevant P&L/fees, account cash, original
position links and price cursors. Exposure can be recomputed from open quantities;
stale quote caches are deliberately excluded. Unknown unmanaged open positions
abort export rather than disappear silently.

Authentication columns, operators, news/technical payloads and historical target
revisions are removed. Per-trade execution settings and an explicit allowlist of
global risk/exposure, extended-hours and monitor settings are preserved. Restore
refuses a different runtime policy; provision matching nonsecret settings first.
No entire `.env` is backed up. Required scanner credentials are generated anew at
restore. Known credential patterns/environment secrets fail validation.

Canonical JSON is gzip-compressed in memory and encrypted with age before disk
or Git. The source server has only the public age recipient. The private age
identity is in the protected local staging directory and private credential
document; the owner must keep an additional safe offline copy. Loss of that key
makes the encrypted backups unusable.

The server's SSH deploy key can write only this backup repository. It is not a
GitHub account token. SSH host keys are pinned; anonymous readability of the repo
aborts upload. Repository visibility was also checked through authenticated GitHub
access at setup. A filesystem lock prevents concurrent backup writers.

## Schedule and retention

Start `docker compose -f deploy/compose.yml --profile backups up -d backup`.
It runs on startup and at each UTC hour. Failures retry after 60 seconds without
touching the success heartbeat. Health becomes unhealthy after 7,500 seconds
without a successful upload. Monitoring does not block trading/price workers.

Retained working-tree files: 24 hourly, 7 daily, 4 ISO-weekly; each daily/weekly
slot contains that period's latest successful snapshot. The latest additional
predeploy checkpoint is retained separately. Multiple snapshots within an hour
replace that hour's current file, not create additional hourly slots. New installs
accumulate retention naturally; missing past snapshots are never invented.

`deploy/redeploy.sh` takes and pushes a checkpoint **before** stopping services or
running migrations, and aborts if backup fails. Use it for subsequent redeploys.
For a separate significant migration, run first:

```sh
docker compose -f deploy/compose.yml --profile backups exec -T backup \
  python /app/service/server/recovery_backup.py --once --predeploy
```

**Git history retains previous encrypted blobs** even when working-tree retention
deletes old paths. No force-push/history rewrite is performed. `/backup/status.json`
and structured logs record encrypted size, retained count and all local `.git`
bytes. `RECOVERY_GIT_WARN_BYTES` defaults to 100 MiB; `warning:true` requires review
before changing retention. This is a status/log warning, not an email/push alert.
At the measured tiny sizes growth is modest, but it is not bounded by 35 files.
This is not immutable/WORM storage: compromise of the server's write deploy key
could alter/delete backup history. Encryption protects confidentiality, not remote
availability. A later immutable second copy can reduce that risk if needed.

## Restore

Clone the private backup repo on a trusted recovery machine; retrieve the offline
age identity separately. Provision a **new empty** PostgreSQL DB, migrations 1/2,
and matching runtime policy. Stop all writers, including API, and supply newly
generated scanner authentication in a protected file. Never merge a recovery
snapshot into a running or populated database.

```sh
python service/server/recovery_state.py validate \
  --snapshot PATH.json.gz.age --identity /secure/recovery-identity.txt
python service/server/recovery_state.py restore \
  --snapshot PATH.json.gz.age --identity /secure/recovery-identity.txt \
  --database-url-file /secure/database_url \
  --scanner-token-file /secure/scanner_token --workers-stopped
```

Read-only snapshot validation precedes import. One transaction holds role and
table locks, restores required parents, advances ID sequences, verifies every
preserved column and adds an explicit opening-accounting baseline for omitted
history. Importing twice or while a worker lease exists fails. Price cursors and
fill IDs survive; pending events/history/outbox do not. News checks are scheduled
fresh. Secrets, Telegram sessions, model settings and infrastructure configuration
must be provisioned separately; this is deliberately NOT full server recovery.

Tests: `tests_pg/test_recovery.py` exercises encrypted roundtrip, partial fills,
Shadow, cash/fee parity, replay, next-bar execution, secret rejection, runtime
policy mismatch and retention. Actual staging ciphertext was also downloaded
from GitHub, decrypted off-server and restored over SSH stdin into a separate
fresh PostgreSQL database. The decryption key was never uploaded to the server.
