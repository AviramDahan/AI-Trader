SEC decision intelligence (branch-only, not activated)
======================================================

Scope and trust boundary
------------------------

This module uses the existing S&P 500 + Nasdaq-100 ``load_universe`` union.
It does not create a watchlist, change the technical/target gates or open a
separate order path. Official SEC ticker→issuer-CIK mapping is exact; ambiguous
or unavailable mappings remain unknown. The universe's dated composition is
stored in ``si_universe_snapshots``. This is not whole-market coverage.

The scanner-role background task ``stock_sec_intelligence`` rotates at most
eight issuer CIKs per minute, independently of market hours and the position
monitor. It reads SEC submissions ``recent`` and continuation files, with
durable per-issuer catch-up checkpoints and a 600-filing pending cap. It parses
at most two documents per minute. A first-time import continues through at
most the 90-day feature horizon; older history is unknown, not negative.
Outages use the last seen accession and continuation checkpoint. A shared
PostgreSQL reservation clock limits *all scanner SEC callers* to at most two
requests per second; 403/429 and transient failures back off. Only official
HTTPS SEC paths are allowlisted; redirects are disabled, responses/time/size
are bounded, and XML DTD/entities are rejected. An operator User-Agent with a
real contact email is mandatory. EdgarTools is not required; SEC XML/XBRL
definitions and original filing references are authoritative.

Document recovery (parser v2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ownership ``xsl.../FILE.xml`` primary paths are SEC presentation wrappers.
The worker requests ``FILE.xml`` directly under the same verified issuer and
accession, retaining the original primary metadata and the actual evidence
URL/hash. It does not parse rendered HTML as ownership XML or relax DTD/entity,
allowlist, redirect, time or two-request-per-second protections. Financial
10-Q/10-K primary documents have a bounded 10 MB hash-only transport ceiling,
matching their existing structured XBRL ceiling. Ownership/current-report
limits and news extractors remain unchanged.

The normal bounded worker may attempt once, under parser v2, prior generic
``ValueError`` failures from the v1/null parser only for rendered ownership
documents and financial reports. Successful rows are never reprocessed;
unsupported failures record the attempted parser and a whitelisted reason,
so repeated loops/restart cannot create an infinite recovery cycle. Transient
failures retain the existing finite backoff policy. Accepted/published/first-
seen timestamps and immutable decisions are not rewritten, and old filings
remain ineligible for fresh evidence/publication. This is analytical recovery,
not replay of trades or public news. Arbitrary exception text is never stored.

A persisted processing cursor rotates issuers across worker cycles, rather
than only inside each batch. It commits with each attempt, including a failed
attempt, without increasing the batch size or SEC request rate. The cursor is
an operational hint in existing settings, not source evidence; an isolated
restore can safely start it empty because processed accessions remain final.

Form 4/4/A transactions keep issuer versus reporting-owner CIK distinct.
Only non-derivative common-equity P/acquired transactions with positive shares
and price contribute to the initial purchase metric. P is *not* evidence of an
open-market trade; private/10b5-1 status remains unknown unless explicitly
supported. Known scheduled/private purchases remain AI evidence but receive no
ranking bonus; purchases whose execution character is unknown receive only a
small bounded research adjustment, never the label "discretionary". Shared
owners of the same economic purchase form one buyer group.
The 7/30/90-day windows, purchase/filing weights and material-change cutoffs
are bounded server settings in ``.env.example`` and are retained with each
immutable snapshot. Changing them requires a new forward comparison; it does
not rewrite earlier decisions.
An amendment supersedes exactly one original only when report period, owner
set, security set and transaction count all match; otherwise its new purchase
rows do not contribute. Earlier immutable decision snapshots are not revised.

10-Q/10-K comparisons are XBRL tag+unit+period matched. Quarter versus YTD,
currency mismatch, future restatements, zero denominators and absent/custom
tags yield unknown instead of a fabricated percentage. 8-K and one related
99 exhibit may supply a specific, quoted guidance update for AI review; no
numeric guidance change is inferred without a same-period prior value. The
bounded parser never executes document text or passes it as system instructions.
Only validated material comparisons (at least 10% relative change or 2
percentage points of operating margin) become current signal evidence;
smaller or non-comparable filing facts remain stored context, not a fresh-news
substitute. These initial cutoffs are uncalibrated research controls.

Decision path and modes
-----------------------

``off`` (default): no SEC selection effect; the existing scanner behavior and
prompt are preserved. ``shadow``: retains alternate ranks for every technically
qualified candidate but leaves shortlist, prompts, signals and Telegram on the
baseline path. ``paper``: attaches a precomputed, time-fenced SEC snapshot to
all technically qualified candidates *before* the shortlist cut; enhanced
ranking can change which candidates receive the original deeper review.

The unchanged combined news/technical rank is saved as
``baseline_rank_score``. A research-hypothesis SEC adjustment is bounded to
[-0.10,+0.10] and saved separately as insider/filing components and
``enhanced_rank_score``. It is applied once at each selection stage, not twice
inside one score. Missing SEC coverage contributes zero, not a clean bill of
health. An explicit accession overlap with ordinary news suppresses the
separate SEC rank bonus. Contradictory validated financial declines and
purchase evidence can force a BUY review to HOLD, never SELL.

Current official SEC evidence can substitute for absent Yahoo news only while
it is fresh under the scanner's existing news-age setting. It does not fabricate
Yahoo relevance or model confidence. The existing target plan, quote, hours,
AI confidence, budget, cooldown, duplicate, risk and ``record_signal`` gates
remain in force. A qualified signal and a pending LIMIT order are not a fill.
Existing positions' stops/targets are untouched. ``SEC_INTELLIGENCE_KILL_SWITCH``
removes this module's influence on *new entries*; the monitor and existing
positions continue normally. A provider failure is marked degraded and the
baseline path remains subject to its original gates.

Immutable decisions store scan ID, ticker, mode, snapshot/evidence IDs, scores,
decision time and a rejection reason. Signals retain the SEC snapshot in their
existing technical JSON; the UI explains support/opposition, rank change and
official source date/link. In paper mode, a qualifying signal's existing
Telegram message also carries a bounded Hebrew SEC explanation, rank change
and reporting date; no filing URL is put in the public message. Operational
coverage is manager-authenticated at ``/api/scanner/sec-intelligence/status``.

Dedicated SEC Forum topic
-------------------------

``📑 דיווחי SEC מהותיים`` is a separate optional public Telegram topic. It is
not a new scanner, AI review or order path. The scanner queues an alert through
the existing durable Telegram outbox in the same transaction that records a
fresh verified filing. The existing Telegram worker delivers it with the
``sec_intelligence`` route and one accession-level dedupe key. One issuer
filing with multiple share-class tickers therefore produces at most one alert.
No document is posted merely because it was collected. A verified non-
derivative P/acquired purchase must have either at least two independent
buyer groups or at least 1 million in verified transaction value; explicitly
scheduled/private transactions do not qualify for this public purchase alert.
The message never claims a public-market discretionary trade. A 10-Q/K
comparison must cross the bounded material-change research threshold and
remain unit/period comparable. Text-only 8-K guidance is retained as decision
evidence but is not published to this topic without a validated quantitative
comparison. These public-notice rules are conservative anti-noise controls,
not an empirical edge claim.

Public SEC alerts require *all* of: ``SEC_INTELLIGENCE_MODE=paper``, kill
switch off, existing Telegram enabled, a valid dedicated
``TELEGRAM_SEC_INTELLIGENCE_THREAD_ID``, and an explicit UTC
``SEC_INTELLIGENCE_PUBLIC_NOT_BEFORE``. The filing acceptance time must be at
or after that cutover and within the configured 1–24-hour freshness window
(default 6 hours) when processing finishes. Off/shadow, missing configuration,
stale catch-up and backfill remain silent. Pending SEC alerts are cancelled if
the mode is turned off, the kill switch is set or the dedicated topic becomes
unavailable before dispatch. The topic has no fallback to General or the
stock-news topic. Source URLs stay in evidence/UI and are removed at the
public-news presentation boundary. Coverage status includes SEC alert counts
by delivery state; it does not treat ``sent`` alone as reader-side proof.

After a separately approved schema-7-compatible release, the operator can run
``python scripts/configure_sec_intelligence_topic.py`` once via the protected
deployment channel. The script creates only this topic (or verifies its
configured ID), writes the ignored server ``.env`` and sends no public post.
After an uncertain Telegram creation or an interrupted ``.env`` write, inspect
the chat/topic before rerunning: Telegram does not provide an idempotency key
for topic creation. Set the UTC cutover to the actual approved activation time;
do not backdate it or replay old filings.

Forward comparison, not backtest
--------------------------------

Discovery under backpressure assigns a bounded share of the existing queue to
each visited issuer. A partial submissions block/continuation page retains
its prior accession/page checkpoint and forces a refetch on the next turn;
already retained accessions dedupe. Rotation advances only past issuers
actually visited, not past the rest of an interrupted batch. A full queue
performs no filing-discovery request. The 600-job ceiling, eight-issuer batch,
processing cadence and shared SEC request limit remain unchanged.
Status reports distinguish mapped universe issuers, checkpointed issuers and
completed issuer checkpoints: ticker mapping alone is not filing coverage.

``python scripts/sec_intelligence_compare.py --hours 168`` reads retained
``si_decisions`` and compares baseline, insider-only, filing-only and combined
top-25 selections at the same scan timestamps. It reports actually executed
Native outcomes separately. It does **not** impute AI decisions, fills, net
returns or drawdown for unselected names. These require point-in-time market
data, natural decisions and a dated equity series; a same-sample parameter
sweep would not establish an edge. Counts include rejected candidates.

Activation and recovery boundary
--------------------------------

No production migration/config change is authorized by this implementation.
Schema 7 is cumulative and the cloud runtime correctly refuses schema 6.
The existing ``hetzner-deploy.sh`` deliberately blocks an image whose schema
version differs from the active image. Thus **do not merge/deploy this branch
through that script as-is**. The prerequisite bridge is PR #39. It retains
the normal schema-6 migration target, can read a complete schema 7, and
fail-closes queued SEC alerts so they cannot fall through to General. The
dedicated ``deploy/migrate-sec-intelligence.sh`` is an operator-approved
transition only: it requires the actual bridge image, exact main SHA and
successful release checks, an encrypted predeploy backup, exclusive deploy
lock, all writers stopped for migration 007 and the SEC mode ``off``. It
supports explicit resume on validated schema 7 without rerunning DDL. The
normal deployment schema guard remains intact. Its command-double tests
exercise failure after migration, bridge rollback and safe resume; Linux
PostgreSQL/image tests and operator approval are still required before use.
Do not return to the older schema-6-only image, rewind the database or treat
the kill switch as a binary rollback. The bridge never rewrites paper orders
or positions. SEC alerts cancelled during bridge rollback are not replayed.

The existing encrypted ACTIVE-state recovery preserves the paper portfolio
and recovery holds. A separate SEC-only companion archive (format 1, schema
7) now preserves all six analytical SEC tables, including immutable decisions,
transaction identities, amendments, dated universe membership and discovery
checkpoints. It contains no unrelated news, prompts, credentials or full DB.
Release and rollback bridge both export/read this companion. Before migration
007, absent SEC coverage is explicit; an absent archive is not proof of zero
filings. ACTIVE recovery formats 2/3/4 are unchanged. Their capture time and
the companion's capture time are separate; this is not one cross-module
transaction or a point-in-time backup of the entire database.

Each companion is exported through one repeatable-read, read-only transaction
and a bounded server cursor, encrypted in at most 1 MiB chunks using real age.
An encrypted manifest verifies counts and checksums; unchanged chunks reuse
ciphertext under the same recipient. Only ciphertext and non-sensitive
paths/checksums reach disk and the existing private recovery Git repository.
Manifest pointers retain 24 hourly / 7 daily / 4 weekly / latest predeploy
coverage. Old Git objects are not rewritten or securely erased; historical
repository size still grows and the existing size warning remains necessary.

``SEC_INTELLIGENCE_HISTORY_DAYS=400`` (allowed 400..730) bounds live analytical
history, not trading thresholds or the shorter scoring windows. Only after
the encrypted companion is pushed and the exact remote Git commit verified
can the activation backup process prune at most 200 old, unchanged rows per
table per run. Active Native/Shadow positions, pending/uncertain orders,
current snapshot dependencies, amendment links, queued/retry jobs, and all
discovery checkpoints are protected. Cleanup uses short non-waiting SEC-only
locks; contention defers it atomically and reports degraded maintenance.
The rollback bridge archives but never prunes. Backfill older than the retention
horizon cannot re-enter discovery after pruning; it is unavailable context,
not negative evidence or a new filing. Earlier decisions remain recoverable
from the encrypted archive and are never re-evaluated retrospectively.

For disaster recovery, restore ACTIVE state first using its existing guarded
tool. With all workers stopped and all role leases free, restore the trusted
SEC companion into empty, fully validated schema-7 SEC tables using:
``python service/server/sec_history.py --repo PRIVATE_RECOVERY_CHECKOUT
--manifest sec/manifests/HASH.age --identity PROTECTED_OPERATOR_IDENTITY
--database-url-file PROTECTED_URL_FILE --workers-stopped``.
Decryption stays in memory; no private identity belongs on the source server.
Restore is atomic, validates references/counts/hashes, rejects a nonempty
destination and queues no publication, trades or fills. It retains original
processing times and checkpoints instead of relabelling backfill as fresh.
This companion is intentionally not a full-system recovery of news or prompts.

One-time operator configuration after a separately approved migration/release:
set a genuine ``NEWS_SEC_USER_AGENT`` with contact email; keep the shared gap
at least ``0.5`` seconds; select ``SEC_INTELLIGENCE_MODE=shadow`` to inspect
coverage and forward selection differences. A separate explicit operator
decision may later choose ``paper``. Neither mode changes live brokerage;
only the existing simulated paper lifecycle is reachable.
