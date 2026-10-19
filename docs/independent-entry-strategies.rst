Independent entry discovery, baseline preserved
==============================================

Scope and authorization
-----------------------

This implementation adds five independent BUY discovery routes to the existing
scanner, before the baseline-specific trend/momentum rejection and the shortlist:

* VCP_BASE_CONTRACTION: a causal contraction base and completed breakout trigger.
* STOCKBEE_MOMENTUM_BURST: a prior base with completed price/volume expansion.
* PEAD: verified, available earnings publication and post-release continuation.
* TREND_PULLBACK_RECLAIM: trend, prior pullback and explicit reclaim trigger.
* RELATIVE_STRENGTH_LEADER: causal benchmark-relative strength plus an actual
  entry setup/trigger; a relative-strength ranking alone is not an entry.

These routes are OR, not additional mandatory filters on the existing route.
SINGLE, V2, exit strategies and an unfilled order are not counted as discovery
strategies or executed trades. The original detector remains BASELINE.

Each route has its own default-OFF server flag. With all flags OFF, baseline
candidate decisions and provider calls must be unchanged. This branch starts
from main1d61cc182e27696cd182555c4640ed3c257e7cf8; it does not depend on merging
PR85 and never enables its additional VCP filter.

Shared controls
---------------

All routes retain data validity, liquidity/ATR, current evidence, AI confidence,
fresh quote/session, duplicate, budget, exposure, cash, structural stop and
target/RR gates. They use the same _paper_order/record_signal/LIMIT/full-bar/
retry/TP-SL pipeline; no alternate execution, exit or SHORT policy is introduced.
An incompatible setup reports its exact entry/stop/target block, without moving
levels or lowering risk requirements. Discovery is not execution.

Merge by ticker and direction. Preserve strategy IDs, versions, source clocks,
trigger and all contributing detections; do not award a duplicate-strategy bonus.
Bounded fair ordering must preserve AI capacity and prevent indefinite exclusion
of a new route. Source metadata is immutable audit data, not a new executable
target-plan contract. Recovery readers and attribution round trips are tested;
no old-reader compatibility claim follows merely from an unchanged schema number.

There is one explicit directional arbitration: if the unchanged baseline emits
SELL and an independent route emits BUY for the same ticker, the existing
baseline direction takes precedence. The independent DETECTED observation and
opposing_baseline_direction block remain visible; the dropped BUY is not added
as a contributor to a SELL/SHORT signal. This avoids opposing duplicate orders
without introducing an untested highest-score direction-switching policy. It is
not a requirement to pass the old baseline: all five baseline-NONE positive
controls are tested independently. Opposing direction is reported separately
from lack of setup, data failure, AI rejection or target incompatibility.

Versioned entry compatibility for NEW independent contracts
----------------------------------------------------------

Each route confirms its completed daily trigger before discovering a candidate.
The current quote must still exceed at least one enabled frozen trigger and not
exceed that route's chase bound, both before AI/planning and at record_signal.
No missing/FORMING route becomes a valid trigger. Orders remain LIMIT, not STOP.
For NEW independent BUY entries without a BASELINE contributor, persist
independent_entry_execution_v1 in signal, order and trade. Freeze only branches
valid at the original quote, their source/audit digest, support and chase ceiling.
Branches are OR, not all required simultaneously:

* VCP, Stockbee, PEAD and RS: actual slippage-adjusted fill must be strictly above
  the frozen confirmed pivot and no greater than the frozen chase ceiling.
* Pullback Reclaim: after confirmed reclaim at admission, a later improved fill
  below that pivot is permitted only strictly above frozen EMA20 support and
  no greater than the frozen chase ceiling. EMA is never recomputed at fill.

All structural stop, resistance, RR, expiry and execution checks still apply.
New independent V1/STAGED orders also freeze the completed eligible-bar window;
that does not change V1 targets or create a new exit strategy.

Independent QA reproduced an important distinction: an RS pivot100.85 and
LIMIT102 can legally fill at100.8 under the original V2 plan (stop97.46,
ATR1.90714), despite the earlier setup/admission having cleared the pivot. This
remains the exact behavior for retained audit-only contracts. With the NEW RS
contract,100.8 is below100.85: the order remains pending, no debit/fill/position
is created, and last_strategy_entry_block records the actual checked price/bar.
A later eligible complete bar may fill only after all unchanged controls pass.
Neither levels nor expiry move. Missing intervening bars remain uncertain with
reservation; restart/replay cannot infer a rejected touch as an earlier fill.
An unknown/malformed execution contract fails closed. Existing orders and
BASELINE-contributor entries retain their saved prior behavior, not auto-upgraded.

The existing structural planner is called unchanged for every discovered route:
nearest resistance and structural stop/ATR/minimum RR still apply; only the
already-authorized no_forward_zone path can use the existing Breakout policy.
Pullback/PEAD setups can be incompatible with those targets; the exact existing
target rejection is journaled rather than bypassed. Positive synthetic fixtures
test legal admission, and negative fixtures retain those blocks independently.

As-of and missing information
----------------------------

Only completed source prefixes available by decision time may be used. Preserve
market, publication, observation, processing and effective-availability times.
PEAD requires verified publication timing and post-event bars; a weekly schedule,
headline or filing acceptance time is not invented as an earnings release time.
Missing EPS/consensus is not fabricated and is not required for a policy that
does not infer an earnings surprise. RS requires an as-of benchmark; any sector
corroboration requires a verified, available mapping. Unknown information affects
only its own route. Today-downloaded adjusted prices are retrospective research
inputs, not original historical system snapshots.

Validation and reporting
------------------------

One frozen comparison reports twelve arms: baseline, each of five routes alone,
baseline OR each route, and baseline OR all routes. Keep identical data, periods,
cost/execution assumptions and existing quotas. Report unique opportunities,
overlap, shortlist, actual reviews/approvals/orders/entries and exact blocks.
Missing actual AI/execution outcomes remain unknown, not zero or reconstructed.
WR, net expectancy, PF and drawdown require adequate execution/outcome evidence.

Every route must demonstrate a candidate missed by the original detector using
actual detector code and synthetic market/provider fixtures. Independent QA
checks as-of boundaries, OR/dedup/fairness, default-OFF parity, unchanged common
gates, real code entry/exit/restart lifecycle, SQLite/PostgreSQL and recovery.
Synthetic lifecycle results, historical simulations and actual Paper results are
reported separately. A route's missing evidence does not block implementing and
testing the other routes. No parameter sweep or profitability guarantee applies.

Use at most two donor repositories including tradermonty/claude-trading-skills.
Keep source commits, licenses and attribution. Research already completed is
reused; available code is not evidence of profitable trading performance.

No Production access or changes, merge, deploy, live activation, real Telegram
send, paid inference, position changes or automated PR85 merge is authorized.

Implementation map and operation (not an activation instruction)
--------------------------------------------------------------

* entry_strategies.py: five bounded, causal daily detectors and trigger checks.
* entry_strategy_inputs.py: separate2-year discovery cache, plus SPY for RS; a bounded
  immutable verified-release reader for PEAD. It never overwrites baseline6-month
  frames/EMA/ATR/zones. No extra calls or DB reads with every new flag OFF.
  All enabled routes get the same discovery prefix independently of the other
  flags; switching VCP must not change another route's EMA seed/history. A
  missing long frame is UNKNOWN for discovery, not a short-frame substitution.
* entry_discovery.py: OR composition before the old trend/momentum gate,
  symbol deduplication, immutable source attribution and rotating fair queues.
* stock_scanner.run_scan: composition before shortlist, unchanged news/SEC/AI
  gates, shared quotas, fair ordering after news, existing _paper_order path.
* scanner_engine.record_signal/_create_trade_rows: same admission/execution,
  saved bounded provenance in signal/order/trade; closing SELL audit belongs
  to its own closing signal, not to the historical entry.
* entry_strategy_journal.py: rejected/UNKNOWN and positive discovery observations
  in existing scanner_candidates, stage=entry_discovery/status=observed. They
  are not public signals, orders, positions, or rejection outcomes.
* recovery_state.py/single_target_recovery.py: validate and preserve provenance,
  including recovery_uncertain closes and their original attribution.
* entry_strategy_execution.py: new-only frozen OR fill guards; price failure
  observations, full-bar retry/recovery and public reason projection.
* earnings_releases.py/news_pipeline.run_feed_cycle: original-page PEAD producer
  on the existing feed worker, outside HTTP scan/UI and transactions over HTTP.

Five default-OFF flags are listed in .env.example. They are independent; there
is no VCP GO dependency or mandatory AND across routes. Disable all five to
stop new independent discoveries, returning to original baseline selection.
Stored orders/positions, their TP/SL and uncertainty reservations continue under
their saved original execution contracts. No existing row is converted/deleted.

No database migration is added: existing schema7 JSON columns and journals are
reused. Snapshot format7 is required by entry_discovery attribution, including
retained earlier audit-only data. Format8 is required by the new execution guard
or its observation. Readers reject a mislabeled older format rather than erase
metadata. Pre-feature main1d61 is UNSAFE_NOT_SUPPORTED for rollback: an old
runtime can ignore the new auxiliary guard even if its backup reader rejects7/8.
No DB rewind, audit deletion or automatic release of holds is permitted.

Build a supported compatibility bridge from the SAME exact candidate source SHA:

::

  docker build --build-arg BUILD_SHA=<exact_sha> --build-arg ENTRY_DISCOVERY_ROLE=bridge -t ai-trader:entry-discovery-bridge-<sha> .
  docker build --build-arg BUILD_SHA=<exact_sha> --build-arg ENTRY_DISCOVERY_ROLE=candidate -t ai-trader:entry-discovery-candidate-<sha> .

The build stamps a root-owned read-only capability before dropping privileges;
bridge creation is OFF even if runtime discovery flags are accidentally true.
It retains new readers, pending/recovery management, exits and formats7/8.
Disabling flags stops creation only; it is NOT a binary rollback. Future release
must build/verify/pin the actual host bridge image ID and SHA BEFORE enabling any
route, retain it, and return only to that bridge on the CURRENT database.
The test-only entry-discovery-compatibility workflow exercises actual images on
isolated Linux/PostgreSQL with real age, old-runtime unsafe probe on a CLONE,
bridge current-DB management/restart and encrypted restore into an empty DB.
An image manifest/rebuild recipe is not a retained rollback image. If the tested
archive exceeds250MiB it is not uploaded; report ROLLBACK_ARTIFACT_NOT_RETAINED
and keep activation gated until a real host rollback image has been retained.
Existing active-state backups still cover open positions/recovery_uncertain
holds, not every ordinary pending order or the research observation journal.

PEAD producer and honest coverage
-------------------------------

When PEAD is ON, the existing feed worker consumes canonical ne_sources from
already-enabled/approved PRnewswire and GlobeNewswire original releases. It does
not enable a provider, infer a license, crawl issuer sites, depend on a watchlist,
or guarantee whole-universe earnings coverage. Unsupported sources/mappings,
intraday releases and separately linked correction URLs remain explicit gaps.
Cached current-universe membership and the official SEC issuer mapping verify
the original reporting paragraph's exchange/ticker. No reporting-owner/path CIK,
fuzzy identity or LLM guess is used.

Original-page article:published_time/datePublished must be a nonconflicting
timezone-aware datetime. A date-only field, headline, scheduled calendar, SEC
acceptance, first-seen, or download time cannot replace it. An original-body
actual financial-results statement with its fiscal period is required; a
conference preview or future announcement is not a verified release. This
producer verifies timing/identity, NOT EPS surprise or analyst consensus.

Preserve original released/published, first-seen, actual page-observed, processed
and effective availability clocks, content hash, parser version, issuer-map hash
and stable event/source IDs. Same-URL corrections append immutable revisions.
A pending/unverified correction or source withdrawal blocks the old fact instead
of reviving it. A changed original publication timestamp is UNKNOWN. Clean daily
revalidation does not refresh the event's original availability or age. Backfill
is context, never an old trade or newly published alert.

Reuse scanner_settings for an atomic producer lease, source-key checkpoint,
recoverable jobs, fair completed-page rotation, backoff/provider circuit breaker
and coverage. Each cycle scans at most200 sources and fetches at most2 approved
pages (12s/2MiB per request); HTTP runs outside DB transactions. HTTPS exact
host/path allowlists, pinned public DNS, redirects disabled, parser text/node/
metadata limits and no executable document instructions remain enforced.
Immutable facts use scanner_candidates stage=earnings_release. The scanner only
reads bounded facts as-of; it never fetches a release in a UI/scan request.
Coverage metadata: scanner_settings key pead_release_coverage_v1 and the returned
load_context.earnings_coverage. OFF and bridge perform zero producer DB/network.
This analytical journal is not part of the active-position backup, which remains
an active-state transfer, not a full application backup.

Synthetic worker→fact→reader→actual PEAD→paper lifecycle is testable now. Public
live publication coverage and a profitable PEAD edge are separate unverified
claims; unavailable facts return UNKNOWN for PEAD only. All five flags stay OFF.

Expanded comparison boundaries
-----------------------------

The twelve arms use a fixed cohort and multiple predeclared market cutoffs.
Baseline receives its six-calendar-month prefix; new detectors receive a separate
long prefix. Actual download/observation clocks are preserved. Historical
calculations use entry_discovery_component_v1, which live validation, AI review,
record_signal and execution refuse; calculation_at is not a fabricated historical
availability time. Research-only exact pure-helper memoization is independently
compared with unmemoized calls. Planned AI-slot competition is not historical AI
approval; daily reference-price structural probes are not executions. Missing
PIT releases, historical model decisions or actual fills keep outcome metrics
NULL/DATA_INSUFFICIENT, never invented zero trades or profit.

Donor attribution
-----------------

One external repository is used, not two forced selections:
https://github.com/tradermonty/claude-trading-skills at
b29c6dfc2d4dc82bdfcfc13891e490863283405f, MIT. Vendor PROVENANCE.json records
paths, Git blobs, SHA256 and included/excluded symbols. VCP's pure calculator is
copied unchanged; Stockbee uses the donor's base/price/volume primitives without
its clients, stop/sizing/exit policies. PEAD daily follow-through, pullback/reclaim
and RS base-break adapters are local untuned hypotheses, not claimed copies of
the donor's weekly PEAD strategy or externally proven profitable algorithms.
The earlier18-strategy research is reused; no compatible, credibly profitable
executable replacement was found there for these minimal adapters.

Isolated validation commands
----------------------------

::

  python -m pytest service/server/tests/test_entry_strategies.py service/server/tests/test_entry_strategy_inputs.py service/server/tests/test_entry_strategies_integration.py -q
  python -m pytest research/tests/test_compare_entry_strategies.py -q
  python -m pytest service/server/tests_pg/test_entry_strategies_pg.py -q
  python -m pytest service/server/tests -q

PostgreSQL tests require the existing isolated TEST_POSTGRES_URL fixture and real
age/age-keygen for encrypted round trips. They do not use a worker or Production.
Linux CI/Readiness runs the relevant full backend/PostgreSQL/frontend/image suites;
a skipped historical compatibility-image workflow is not compatibility proof.
