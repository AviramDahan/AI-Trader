VCP Breakout proof of concept (not activated)
============================================

Purpose and scope
-----------------

This is an isolated selection experiment in the existing US-stock scanner, not
a new scanner, execution engine, investment product or profitable-strategy claim.
The three existing specialist roles are reused: Trading implements the adapter,
Research Improvements produces the comparison, and Independent QA reviews both.
The coordinator integrates their evidence. No additional agent runtime, schedule
or Production report publisher is introduced.

STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED defaults to false. Missing, false or
unrecognized configuration must not add the VCP confirmation to baseline entries.
When explicitly enabled in an isolated experiment, only NEW BUY/SINGLE breakout
fallback selections can require the new confirmation. The original structure
builder runs first. Known resistance, inside-zone, invalid stop, liquidity, ATR,
technical score, current evidence, AI/confidence, session, quote, allocation,
exposure and duplicate checks are not bypassed or weakened.

Baseline A is the existing Breakout contract. Candidate B is that same contract
with additional VCP setup confirmation. B cannot turn a structural rejection
into an approval. It may reject more setups; that is not itself improved quality.
No new scoring weights or production thresholds are selected from a test sample.
Stockbee Momentum Burst and PEAD are NOT implemented in this POC.

Frozen POC hypotheses (not optimized thresholds): use 252 completed prior
sessions plus a separate completed trigger session (253 rows). The prior base
must have a valid contraction pattern, volume dry-up below its own prior-50
average, and a completed close above the raw pivot with at least 1.5x prior-50
volume. The current price must remain in the donor's confirmed Breakout state,
within 3% above that pivot and without a damaged trend. These are additional
selection requirements in the isolated POC only; none changes the existing
technical/RR/risk thresholds. There is no ranking bonus or refill expansion.

Source and provenance
---------------------

The sole strategy-code donor is MIT-licensed tradermonty/claude-trading-skills,
pinned to b29c6dfc2d4dc82bdfcfc13891e490863283405f. The reviewed components are
the VCP pattern, volume pattern, execution state and pivot proximity calculators.
The vendored source/provenance records preserve the upstream license and explain
local adapter constraints. External instructions, CLI orchestration, paid data
clients, orders, sizing and exit policies are not imported.

The upstream code's setup score, state and future-breakout labels are not win
probabilities or trade returns. No upstream performance claim transfers to our
LIMIT entry, structural stop and fixed-target exits.

Point-in-time contract
----------------------

Only completed sessions known by decision_at may influence the adapter. Preserve
the source observation time separately from candle time and pivot confirmation.
Do not turn an old downloaded dataset into historical system availability merely
by substituting candle dates. Reject unknown/future observation times; never use
a later pivot or incomplete candle in an earlier decision. Pattern and volume
dry-up calculations must not include an unknown future trigger candle.

Insufficient warmup, missing pivot, invalid data or unavailable source clocks are
UNKNOWN, not a positive signal or proof of a bearish setup. The existing history
loader requests six months, insufficient for genuine SMA200/52-week coverage.
The POC does not silently change live downloads, cache policy or providers to
obtain that coverage. Additional long histories belong to isolated datasets.

Completed daily volume is not current intraday relative volume. No comparable
time-of-day volume is fabricated. The existing fresh-quote and full-bar order
eligibility checks remain the execution authority; a completed setup is not a
fill at its historical pivot or breakout price.

Retained-state and rollback compatibility
----------------------------------------

No migration, executable target-plan version or backup-format change is required
for selection-only metadata. The existing scanner remains the only route through
_paper_order, record_signal, pending LIMIT, full-bar process_bar, position, TP/SL
and retained accounting. SINGLE still has its original target/stop and 100% exit.
Legacy, SHORT, existing V1/V2 orders and Shadow pairs keep their original rules.

The VCP creation switch must never be checked by retained order/position handling.
Disabling it stops additional confirmation on new selections, not management of
existing orders. No levels, expiry or reservations are rewritten. Selection
provenance is audit metadata, not an execution-critical plan field. Active-state
recovery is not a complete strategy-research archive; do not claim otherwise.

Comparison interpretation
-------------------------

Keep these cohorts separate:

* Synthetic fixtures: deterministic behavior, no-lookahead and plumbing evidence,
  never market performance, historical AI decisions or real paper trades.
* The dated local daily-history cache: identical-data setup/coverage comparisons
  at an explicitly observed snapshot. A reference close is NOT a fresh executable
  quote. Current membership is not a survivorship-free historical universe.
* The 16 October retained cohort: 94 observations, 87 structural rejections,
  six closed-session skips and one AI HOLD. These are not 94 AI calls/trades.
  Missing per-observation OHLCV cannot be filled using an earlier unrelated cache.
* Any separately sourced, pinned historical dataset: label instruments, price
  adjustment basis, availability assumptions and chronological split. A detector
  replay is not full AI-Trader net-performance evidence without actual decision,
  quote, fill and exit records.

Report independent source configurations as well as repeated observations. Use
identical costs and execution assumptions for paired variants; do not manufacture
an intrabar path from daily OHLC. A pending LIMIT is not an executed trade. Do
not sum signal returns as portfolio returns or treat Shadow as independent capital.

Win rate, net expectancy in R, PF, drawdown, holding period and signal-to-entry
conversion require the relevant actual records. Where absent, report
DATA_INSUFFICIENT with the missing fields, rather than zero or synthetic results.
No parameter sweep, same-sample weight optimization, historical AI reconstruction,
live scan/fetch, real Telegram send or paid inference is part of this POC.

Reproduce the committed invented-data controls from the repository root::

  python -B research/scripts/compare_vcp_breakout.py --synthetic-fixture --summary-only
  python -B -m pytest research/tests/test_compare_vcp_breakout.py -q
  python -B -m pytest service/server/tests/test_vcp_breakout.py service/server/tests/test_vcp_breakout_integration.py -q

The comparator also accepts --dataset, --history-cache or --frozen-case-packets
for explicitly provided LOCAL inputs. --retained-funnel adds a separate bounded
aggregate receipt without joining its rows to another dataset. --summary-only
omits per-observation details. Raw operational receipts/cache data are private,
not committed fixtures. The tool denies network and subprocess calls while
evaluating both arms; it never generates signals, orders or fills.

Required validation and activation gate
--------------------------------------

Independent QA must inspect the implementation and comparison, then execute the
new tests and existing Breakout/V2/retry/admission/recovery regressions in isolated
SQLite and PostgreSQL. Tests mock external providers and AI; local test writes
must never address Production. Cover default-OFF parity, incomplete/future data,
pivot confirmation, volume, full-bar eligibility, stop/target path uncertainty,
expiry, duplicate signal/fill/outbox, retained execution after switch-off and
unchanged cash/exposure guards. Record passed, failed and skipped tests exactly.

No merge, deployment or live activation is authorized. Before a controlled Paper
activation, require independent QA, exact-commit CI/readiness, adequate point-in-
time source coverage, compatible retained-state verification, and a separate
operator decision informed by the paired results. Unit tests alone, more detected
setups, or fewer orders cannot establish improved risk-adjusted net performance.

Local implementation evidence, 18 October 2026
---------------------------------------------

The Trading role's seven-suite regression finished with 163 passed. Independent
QA's SQLite/lifecycle matrix finished with 199 passed; its real PostgreSQL matrix
finished with 15 passed, including real age encryption/decryption and active-state
restore. Independent research controls finished with 19 passed. The coordinator's
final adapter/scanner/comparison matrix finished with 80 passed. These suites
overlap: their counts must NOT be added as distinct tests or market observations.

The positive scanner fixture uses the actual technical analyzer, four donor
calculators, target builders, record_signal and full-bar/TP/restart lifecycle;
prices and AI responses are explicitly synthetic and providers are mocked.
Frozen executable levels were unchanged. A format-6 active-state snapshot was
encrypted and restored with the selection switch off; audit-only VCP metadata
is intentionally not promised as part of that backup contract.

QA found a real POC edge case in which a Saturday could count as a completed
session. It was corrected using the existing market calendar, with negative and
unavailable-data regression controls. Other reviewed boundaries include raw pivot
precision, prior-only volume denominators, UNKNOWN reasons and immutable bounded
metadata. No existing trading-engine defect or net-return gain is claimed.

Windows cannot collect the existing SEC backup-service PostgreSQL test module
because it imports POSIX fcntl. No application portability change or stub was
introduced to disguise that limitation. The full mandatory Linux CI/readiness
result on the exact branch commit remains a separate prerequisite, not inferred
from local counts. See research/VCP_COMPARISON.rst and its sanitized JSON results
for the actual paired cohorts and DATA_INSUFFICIENT performance conclusion.
