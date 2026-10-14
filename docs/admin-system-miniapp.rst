Private Telegram operations Mini App
====================================

The existing Main Mini App gains an ``operations`` entry. No second bot,
scanner, database schema, Docker socket, provider fetch or AI job is added.
The public ``live`` entry and its read-only stock workspace remain unchanged.

Use the already verified bot username and existing Main Mini App URL::

    https://t.me/<existing-bot-username>?startapp=operations

The signed launch sends the user to the private operations view, not a new
public tab. ``market/?miniapp=1&ops=1`` can render the shell, but its URL,
Telegram display hints and unsigned user fields never authorize data access.

Authorization
-------------

``GET /api/admin/system-status`` requires either the existing scanner-manager
Bearer permission (ordinary operator website only), or the official Telegram
HMAC-signed ``WebApp.initData`` in ``X-Telegram-Init-Data``. The latter is checked
against the existing Main Mini App bot token, requires an explicit numeric user
ID, rejects duplicate fields, and expires after one hour (30-second future skew
tolerance). Reopen the Mini App after expiry. No browser token is imported into
a Mini App, and initData is not stored in URLs/storage/logs.

After signature verification, the server checks ``getChatMember`` in the
configured PRIVATE ``TELEGRAM_ADMIN_CHAT_ID``. Existing Admin token is used if
configured, otherwise the existing main token, like private alert delivery.
It never substitutes the public community. The checking bot must have sufficient
group permissions: Telegram guarantees other-user lookups for administrators.
Left/kicked/non-member users are denied. A provider error, malformed identity,
missing configuration or redirect does not grant access. Membership is cached
in process memory for at most 30 seconds (denials 5 seconds), with 512-entry
bound and invalidation on bot/group change. No new credentials are provisioned.

Existing authorized logs-group members gain read-only operational visibility;
no trading/config/worker/admin mutation permission is added. Never publish an
operator token or initData in a launch button. Responses are private/no-store;
the authenticated endpoint is NOT added to a public cache/feed.

Evidence and resource bounds
----------------------------

The API uses a repeatable-read PostgreSQL READ ONLY transaction, verifies that
mode, applies a 3-second per-statement bound, and reads indexed queue summaries,
retained service rows, advisory leases (same database), active price cursors
(sample capped at 32), SEC checkpoint counts and allowlisted provider metadata.
The large canonical-health JSON is projected to four fields inside PostgreSQL;
the full history/per_event report is never built or materialized by this view.
No ``init``, migration, watcher check, inference, backup, restore, replay, scan,
provider collection, order, outbox write or Telegram send runs from the route.
A five-second in-process cache coalesces concurrent authorized reads, after
authorization. The UI reads every 15 seconds, one flight at a time, with a
12-second timeout; hidden/unmounted pages abort/pause. Manual refresh refreshes
the VIEW only. Display clocks do not trigger network operations.

Thirteen nodes distinguish API/DB, sources/SEC, quotes/scanner, local and paid
AI routes/news analysis, paper state/monitor, delivery and encrypted backup.
Worker lease ownership is not completed work. No signals is not a failure.
On-demand AI is not stale solely for lack of generations; local ready/busy,
budget availability, processing results and actual inference are not conflated.
An unfilled order is not an active position. Unknown/missing/future timestamps
are not green; failed refreshes preserve visibly retained data. A revoked/expired
authorization clears retained private data. Regular-market closed checks are
not live execution proof. Provider configuration/backoff is visible separately
from overall pipeline liveness. The connections show LOGICAL architecture,
not proof one event traversed the full lifecycle.

The view does not inspect Docker health/OOM/restarts or claim live trading E2E,
accounting reconciliation, model calibration, Telegram readback or an independent
backup restore. These limits are visible in the UI. No money totals/returns are
invented, and no cash/sizing/TP/SL/news thresholds are changed.

Release and rollback
--------------------

Run existing exact-SHA CI and Cloud Readiness, including PostgreSQL tests,
frontend activity/research/signal rendering and Linux container build. Use only
the normal protected release mechanism after explicit deployment approval,
encrypted predeploy backup and verified compatible prior image. No schema or
runtime flag changes are required. Before posting the real entry notice, verify
bot identity, private destination, permissions and current message history to
avoid duplicate notices. Publish at most one authorized button notice in the
logs group, not the public community; read back its text and URL.

Verify actual build/deployed SHA, role liveness/leases, monitor and retained
accounting/holds, backup and old image. Read the authenticated view, verify no
auth/public leak, timestamp advance and missing/stale cases. Native Android/iOS
rendering requires observation; responsive browser fixtures are not native-client
proof. Rollback restores the compatible previous image on the current DB and
may remove/edit ONLY this entry notice; no data restore or trade conversion.
An absent endpoint on a rolled-back server must show unavailable, not green.

Tests and synthetic preview
---------------------------

From the repository root::

    python -m pytest service/server/tests/test_admin_system_status.py -q
    python -m pytest service/server/tests_pg/test_admin_system_status_pg.py -q

The latter needs TEST_POSTGRES_URL for a disposable test database; no live DB.
From service/frontend::

    npm run test:activity
    npm run test:research
    node test-signal-presentation.cjs
    npm run build
    node tests/preview-admin-system.mjs

The GET-only 127.0.0.1:4326 preview uses synthetic fixtures, labels itself as such,
and never calls Production/Telegram/AI. It tests normal, failed, busy, stale,
closed-market and missing data. On phones an expanded node takes the full row
to keep its evidence readable; collapsed nodes retain the architectural flow.
