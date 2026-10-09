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
through that script as-is**. A separately reviewed compatibility/migration
release path and schema-7-capable rollback image must be available *before*
any future approval to activate ``shadow`` or ``paper``. Do not bypass the
schema guard, roll the database back or claim the old schema-6 image can run
against schema 7. Rollback of a safe future release means setting the mode to
``off`` for new decisions and returning only to a schema-7-compatible image
that understands ``sec_intelligence`` outbox rows (or after all such rows are
drained/cancelled with an audited procedure). An older unknown-event router
could otherwise misroute a queued SEC alert to General. The compatibility
image is a release prerequisite, not something this branch has already built.
It never rewrites existing paper orders or positions.

The existing encrypted ACTIVE-state recovery continues to preserve the paper
portfolio and recovery holds on schema 7; it intentionally excludes analytical
filing bodies, historical rank rows, news and prompts. A full PostgreSQL
backup is required if preserving the SEC analytical history across disaster
recovery is operationally required. Loss of that history results in unknown
coverage until recollected and must not be presented as negative evidence.

One-time operator configuration after a separately approved migration/release:
set a genuine ``NEWS_SEC_USER_AGENT`` with contact email; keep the shared gap
at least ``0.5`` seconds; select ``SEC_INTELLIGENCE_MODE=shadow`` to inspect
coverage and forward selection differences. A separate explicit operator
decision may later choose ``paper``. Neither mode changes live brokerage;
only the existing simulated paper lifecycle is reachable.
