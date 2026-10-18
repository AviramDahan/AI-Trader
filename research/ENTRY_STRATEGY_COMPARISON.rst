Independent entry discovery: comparison contract
================================================

Scope
-----

Compare the existing Baseline with five independent BUY discovery hypotheses:
VCP/Base Contraction, Stockbee Momentum Burst, verified point-in-time PEAD,
Trend Pullback Reclaim and Relative Strength Leader with an actual trigger.
They are alternatives before the old baseline filter and shortlist, not five
additional gates imposed on an already-approved Baseline candidate.

The12 arms use the same frozen input frames, availability clocks, common data/
liquidity/ATR requirements, ranking/round-robin implementation, shortlist cap,
shared AI cap and execution contract: Baseline; each strategy alone; Baseline OR
each strategy; Baseline OR all five. A ticker is counted once per observation,
with every detecting strategy retained as attribution. Multiple labels must not
multiply AI slots, score bonuses, signals or orders.

Evidence classes
----------------

1. Current-observed vendor research: the fixed20-symbol Yahoo cohort acquired
   on18October2026 has501 daily bars per symbol. It is retrospective vendor data
   observed today, not historical known-at-decision data. Raw prices, Adj Close,
   actions and exact adjustment/source clocks remain private. No extra provider
   download is required for the first comparison. Missing benchmark/sector
   sources and verified earnings release facts remain UNKNOWN, never fabricated.
2. Synthetic controls: invented OHLCV, benchmark and independently timestamped
   earnings facts test positive discovery, old-baseline misses, overlap, caps,
   deduplication and future-data rejection. They are not historical opportunities
   or evidence of profitable trading. Mocked AI/lifecycle outcomes, if supplied
   by independent integration tests, are labelled separately.
3. Real Paper evidence: actual immutable linked reviews, signals, orders, legal
   entries, partial exits and fees are required before reporting conversion or
   net performance. Pending orders are not fills. The isolated comparison does
   not generate reviews, orders, entries or exits and does not read Production.

Matrix denominators and fairness
-------------------------------

Report input observations and unique symbol/direction opportunities separately
from overlapping strategy detections and repeated source configurations.
Retain rejection/UNKNOWN reasons for every strategy, including candidates not
selected. Report planned shortlist and maximum shared AI slots as plans, not
actual calls or AI approvals. Absent immutable outcomes produce null counts with
NOT_VERIFIED/DATA_INSUFFICIENT, not fabricated zero observed trades.

Run the actual shared discovery and ranking helpers, rather than a second copy
of strategy rules or a sorting model tailored to the fixture. Each arm receives
the same caps; the All arm does not receive five times the AI allowance. A fixed
round-robin cursor is shared for a paired comparison. Strategy scores remain
descriptive and are not calibrated decision confidence or return probabilities.

Safety and limitations
----------------------

The tool is offline: no database initialization, network/provider fetch,
scanner worker, AI, Telegram, broker or order execution. Historical source
observation clocks cannot be replaced with candle dates. A future bar or later
earnings correction must not enter an earlier supplied decision. A daily close
is explicitly a completed-bar reference, not a fresh executable quote.

There is no parameter sweep, historical AI reconstruction, invented intrabar
fill, fake PIT universe, OOS claim or profit claim. WR, net expectancy, PF and
drawdown remain DATA_INSUFFICIENT without appropriate real matched trade/fee
records. More discoveries, shortlist slots or fills alone do not establish edge.
All five implementations may be exercised by fixtures even when one real-data
arm is UNKNOWN because its independent evidence inputs are not available.

Raw operational data and vendor series are not committed. Only invented
fixtures, tool/tests, this method and sanitized aggregate result metadata belong
in the repository. Feature enablement, merge and Production deployment are
outside this comparison's authorization.

Actual results:20 stocks plus the separately acquired SPY benchmark
------------------------------------------------------------------

The comparison actually ran on the frozen20-stock cohort, with501 completed
daily candles per symbol,17October2024--16October2026. The later SPY packet
also has501 candles. Stock source observations remain18October18:18:25--18:18:46
UTC; SPY was observed at20:08:24.187491UTC. The NEW recorded comparison decision
was20:18:29.637232UTC, after both sources, and is retained for exact offline
replay. SPY was not backdated into the earlier stock-only comparison.

Every arm receives those same501-bar frames. This is not a count of live
Production discoveries: the unchanged default-all-flags-OFF6-month series may
produce different EMA warmup/zone inputs. Enabled discovery inputs may supply
a separate two-year completed prefix to all five detectors, including the
shorter-warmup routes, not only VCP/RS. This comparison holds501 bars fixed for
Baseline and every alternative; it does not reconstruct a whole default-OFF
versus enabled-worker fetch/cache experiment. No Production worker was run or
queried. The20-stock convenience sample is not a representative universe or
a historical survivorship-free membership reconstruction.

.. list-table:: Discovery counts only, not admitted signals or trades
   :header-rows: 1
   :widths: 42 14 14 15 15

   * - Arm
     - Vendor candidates
     - Planned AI slots
     - Synthetic candidates
     - Planned AI slots
   * - Baseline
     - 17
     - 6
     - 1
     - 1
   * - VCP alone
     - 0
     - 0
     - 1
     - 1
   * - Momentum Burst alone
     - 0
     - 0
     - 4
     - 4
   * - PEAD alone
     - 0
     - 0
     - 1
     - 1
   * - Trend Pullback Reclaim alone
     - 0
     - 0
     - 1
     - 1
   * - RS Leader with trigger alone
     - 0
     - 0
     - 1
     - 1
   * - Baseline OR VCP
     - 17
     - 6
     - 2
     - 2
   * - Baseline OR Momentum Burst
     - 17
     - 6
     - 5
     - 5
   * - Baseline OR PEAD
     - 17
     - 6
     - 2
     - 2
   * - Baseline OR Pullback Reclaim
     - 17
     - 6
     - 2
     - 2
   * - Baseline OR RS Leader
     - 17
     - 6
     - 2
     - 2
   * - Baseline OR all five
     - 17
     - 6
     - 6
     - 6

The actual vendor Baseline candidates are16 BUY and1 existing SELL direction;
the five new routes are BUY-only and do not activate or change SHORT policy.
One observation fails common data/liquidity/ATR eligibility. No external route
adds a detected candidate at this current snapshot: VCP20 REJECTED; Momentum
Burst19 FORMING/1 REJECTED; Pullback20 REJECTED; RS5 FORMING/15 REJECTED. RS is
no longer UNKNOWN after the actual SPY data were supplied. PEAD20 remain
UNKNOWN because verified release facts/timing were not supplied. This is not
evidence that PEAD has negative performance, nor a reason to fabricate events.

All actual AI review/approval, signal, order and entry counts are null with
NOT_VERIFIED_NO_IMMUTABLE_MATCHED_OUTCOMES.17 discoveries are not17 accepted
plans or orders; the unchanged downstream News/AI, fresh quote, session, target,
confidence, duplicate, budget/exposure and legal-entry gates were not declared
passed. WR, net expectancy, PF and drawdown are DATA_INSUFFICIENT in every arm.

Actual synthetic controls and tests
-----------------------------------

Each of the five invented positive controls passes the actual independent
detector and the unchanged common liquidity/ATR requirements, while both old
BUY and SELL technical counts remain below5. Thus independence is tested before
the old baseline filter, not by mocking a positive detector or softening a gate.
Invented older spikes/declines intentionally construct these causal controls;
they are not market examples, robustness frequencies or profitable outcomes.

The actual fair-ranking helper is reused. Some synthetic symbols match several
strategies: attributions exceed unique candidates, but All emits only6 unique
tickers with6 shared planned AI slots. A separate40-row mocked-discovery
plumbing control exercises the real fair-ranking helper's25-shortlist/6-AI cap
and representation of all queues, without claiming that40 market setups exist.

Declared mock review/signal/order inputs are explicitly synthetic. All has5
declared mock pending orders and0 declared mock entries; no engine order or
position is created by this tool. Independent application/lifecycle tests, not
these mock counts, are the place to prove the existing PAPER route.

Research test command actually passed20 tests,0 failures/0 skips::

  python -m pytest research/tests/test_compare_entry_strategies.py -q

Coverage includes all five actual baseline-missed controls, exact12 arms,
duplicate labels/tickers, fair shared caps, input permutation, source clocks,
future/unavailable bars, missing PEAD/benchmark evidence, later benchmark timing,
receipt hashes, duplicate JSON keys, nonfinite inputs and honest null outcomes.
Code hashes normalize CRLF to LF before SHA256 and declare
``code_hash_newline_policy=LF`` so Windows checkouts match Linux/Git code blobs.
The regression test proves CRLF/LF code identity while immutable JSON/vendor
artifact receipts still hash exact original bytes without newline normalization.
Fixture code receipt keys use canonical POSIX paths on every platform, not
Windows-specific path separators; their hashes still use the same LF policy.
These20 tests are a research suite, not a sum to add to overlapping app suites.

Reproduce without Production or downloads
-----------------------------------------

Synthetic controls, public and self-contained within the repository tests::

  python research/scripts/compare_entry_strategies.py --synthetic-fixture --summary-only

Same frozen private authorized vendor packets, no provider call::

  python research/scripts/compare_entry_strategies.py --acquisition-result <private-stock-acquisition-result.json> --benchmark-artifact <private-SPY.json> --comparison-decision-at 2026-10-18T20:18:29.637232+00:00 --summary-only

The tool verifies every stock artifact receipt hash, retains source observation
clocks and excludes unavailable bars before both arms. The recorded comparison
clock must not precede the actual source packets. Public aggregate output is
research/results/entry_strategy_comparison.json; vendor series remain private.
It records LF-normalized implementation/tool/fixture hashes and confirms those
code hashes stayed unchanged during both actual comparison runs. No net-performance
claim or Production activation is justified by these discovery counts.
