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

Entry compatibility: completed setup, then existing passive LIMIT
---------------------------------------------------------------

Each route confirms its completed daily trigger before discovering a candidate.
The current quote must still exceed at least one enabled frozen trigger and not
exceed that route's chase bound, both before AI/planning and at record_signal.
No missing/FORMING route becomes a valid trigger. This does not create a BUY STOP
order, a live intraday volume detector, or a requirement that every later fill
remain above the original independent pivot. The existing passive LIMIT and
frozen SINGLE/V2 or legacy target contract remain the execution authority.

Independent QA reproduced an important distinction: an RS pivot100.85 and
LIMIT102 can legally fill at100.8 under the original V2 plan (stop97.46,
ATR1.90714), despite the earlier setup/admission having cleared the pivot. This
is existing improved-price/pullback LIMIT behavior, not proof that the fill
reconfirmed a breakout. It is not silently changed or presented as a strict
above-pivot execution strategy. A policy that requires actual fill above the
independent pivot needs a separate versioned executable contract and compatible
rollback/restore readers, with explicit failure/retry semantics. That additional
execution policy is a compatibility gap/proposal, not implemented here.

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
  typed verified-release reader for PEAD. It never overwrites baseline6-month
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

Five default-OFF flags are listed in .env.example. They are independent; there
is no VCP GO dependency or mandatory AND across routes. Disable all five to
stop new independent discoveries, returning to original baseline selection.
Stored orders/positions, their TP/SL and uncertainty reservations continue under
their saved original execution contracts. No existing row is converted/deleted.

No database migration is added: existing schema7 JSON columns and candidate
journal are reused. Snapshot/recovery format remains determined by existing
execution contracts (2..6). Provenance is audit metadata, not a new fill rule.
Current readers preserve it; pre-feature recovery readers are NOT certified:
old sanitizers can drop signal/trade attribution or reject additional settings.
Use this feature-capable binary for restore/rollback if attribution must survive.
Disabling discovery flags is not proof of older-binary recovery compatibility.
Existing active-state backups still cover open positions/recovery_uncertain
holds, not every ordinary pending order or the research observation journal.

PEAD live-input readiness is explicitly limited: the current collectors do not
produce the required verified official_earnings_release/verified_earnings_release
typed earnings_events facts. The detector, point-in-time adapter and complete
mocked-provider lifecycle are implemented, but a scheduled earnings calendar,
headline or SEC acceptance timestamp cannot substitute for that missing source.
Thus PEAD returns UNKNOWN until verified publication/identity/processing facts
exist. This blocks PEAD data validation only, never the other four routes.

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
