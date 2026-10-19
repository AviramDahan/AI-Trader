Independent entry discovery: comparison contract
================================================

Expanded follow-up:19October2026
--------------------------------

The latest comparison expands to108 deterministically selected configured
universe members, eight predeclared market cutoffs and one actual-current
observation, on all12 arms. It supersedes the earlier20-stock same501-bar
Baseline comparison below for baseline-window parity. No source repository,
strategy threshold or result-driven cohort selection was changed.

Membership was frozen before the expanded acquisition:73 S&P500-only,12
Nasdaq100-only and23 overlapping members from the dated518-member configured
union. Each sorted stratum uses evenly spaced ordinal selections, after a
minimum12 allocation and proportional largest-remainder allocation. This is
index representation, not sector stratification or a survivorship-free historic
universe. Existing5 stock packets and SPY were reused without relabeling clocks;
103 additional stock packets were acquired from the same free Yahoo source.
All108 remain in the denominator; no failure/short history is replaced.

Actual acquisition completed108/108,208 HTTP requests, no circuit stop. Most
stocks have501 daily rows; CRWV391, HONA87 and SPCX88 retain their true shorter
coverage. The helper derives OHLC from raw OHLC*(AdjClose/Close), Close=AdjClose,
and leaves Volume unchanged; raw prices, actions, mapping metadata and exact
response/packet hashes remain private. Retrospective provider adjustments are
not independently certified point-in-time values. Jan9/2025 is an acknowledged
exceptional market closure, not an imputed missing Yahoo bar.

The target HTTP spacing was0.55s; QA measured a minimum UTC start interval of
0.541196s, a small deviation from that target, still below2 requests/second.
The immutable receipt is not rewritten and the acquisition is not repeated to
hide this discrepancy. No reason for the timing discrepancy is asserted.

Baseline/common metrics now receive a distinct SIX-CALENDAR-MONTH prefix;
independent detectors receive the separately supplied up-to2y prefix. Baseline
EMA/zone state is not reseeded with the longer detector history. Both paths use
the same actual observation clocks and the original pure application helpers.
The current snapshot uses the actual recorded comparison clock
2026-10-19T04:53:45.048406+00:00. Earlier market cutoffs are:
2025-11-28,2026-01-30,2026-03-31,2026-05-29,2026-07-31,2026-08-31,
2026-09-30 and2026-10-16.

Those eight older prefixes are NONEXECUTABLE RETROSPECTIVE COMPONENTS observed
today, not historical eligible decisions. ``calculation_at`` is the separate
16:10 New York feature-calculation clock; actual ``decision_at``, source
observation and effective availability are never backdated. Prefixes are cut
before calculation. Component attribution has a separate version rejected by
AI/admission/execution validators; a read-only explicit branch projection does
not enable execution. The final historical cutoff and current observation
share the16October market session and must not be counted as independent trades.

.. list-table:: Expanded real-data discovery observations, NOT trades
   :header-rows: 1
   :widths: 45 15 13 14 13

   * - Arm
     - Candidates across9 snapshots
     - Unique tickers
     - Planned AI slots
     - Added to Baseline
   * - Baseline
     - 705
     - 108
     - 54
     - 0
   * - VCP alone
     - 0
     - 0
     - 0
     - 0
   * - Momentum Burst alone
     - 5
     - 4
     - 5
     - 1
   * - PEAD alone
     - 0
     - 0
     - 0
     - 0
   * - Pullback Reclaim alone
     - 2
     - 2
     - 2
     - 0
   * - RS Leader with trigger alone
     - 1
     - 1
     - 1
     - 0
   * - Baseline OR VCP
     - 705
     - 108
     - 54
     - 0
   * - Baseline OR Momentum Burst
     - 706
     - 108
     - 54
     - 1
   * - Baseline OR PEAD
     - 705
     - 108
     - 54
     - 0
   * - Baseline OR Pullback Reclaim
     - 705
     - 108
     - 54
     - 0
   * - Baseline OR RS Leader
     - 705
     - 108
     - 54
     - 0
   * - Baseline OR all five
     - 706
     - 108
     - 54
     - 1

The9 snapshot totals are972 ticker observations, not972 independent source
configurations or trades. The result reports distinct market/ticker/direction
observations separately from exact hashes of the two consumed source frames.
Baseline has623 distinct market/ticker/direction observations and703 consumed
dual-frame configurations; All has624 and704 respectively. Different current
versus final-cutoff6mo window starts can change a source configuration without
adding a new market-session opportunity. Neither denominator is a trade count.
Baseline has360 BUY and345 existing SELL-direction observations. New routes
remain BUY-only; no new SHORT policy is inferred. Current-only Baseline and All
both have82 candidates,55 BUY/27 existing SELL; Burst labels NI, already in the
Baseline set. This is not82 accepted plans or imminent fills.

Real-data component labels, computed only at the actual19October observation,
are Burst KO30January-prefix, MTD/ODFL29May-prefix and NI16October-prefix
(NI repeats in current observation); Pullback HST31March-prefix/DD29May-prefix;
RS KO30January-prefix. These are not claimed historical system discoveries.
Only MTD29May is absent from the corresponding Baseline candidate set. VCP has
0 DETECTED,3 FORMING,949 REJECTED and20 UNKNOWN. PEAD is UNKNOWN on all972
observations because actual verified earnings release facts were not supplied;
this is missing input evidence, not negative performance. No facts are invented.

All holds the same25-shortlist/6-shared-AI cap per snapshot,54 planned slots
across9 snapshots. Six selected slot observations differ from Baseline; adding
labels can reorder existing candidates as well as introduce one new candidate.
This is raw discovery ranking competition, not a replay of the whole scanner's
news/SEC enrichment, target-refill credits or actual AI selection/outcomes.
The fixed cursor is paired across arms; live rotation history is not invented.

Every independent detection's actual daily close is inside its necessary
frozen strategy branch interval. Nevertheless the unchanged pure BUY/SINGLE
structure builders reject all8 such observations at that SAME reference close:
Burst4 nearest-resistance-below2R and1 entry-not-above-completed-high;
Pullback1 inside-zone and1 invalid-rounded-levels; RS1 entry-not-above-completed-
high. The one extra MTD candidate is among the2R failures. A daily close is not
a current quote; these are component diagnostics, NOT proof that the real-time
system would reject every possible future legal price. No hypothetical quote
above High20, stop/target change, intrabar fill or relaxed gate was introduced.

Actual AI reviews/approvals, orders, entries and outcomes remain NULL, not
observed zero trades. WR, net expectancy, PF and drawdown remain
DATA_INSUFFICIENT. This broader sample proves executable detection/competition
and exposes remaining entry-fit constraints; it does not establish edge or
justify Paper activation by itself. No parameter tuning was performed.

The bounded research-only cache hashes complete causal frames/index/attrs,
context/configuration and actual/calculation clocks, returns deep copies, and
does not change application runtime caches. ``entry_strategy_ids`` is excluded
only from the legacy analyzer's key because that exact analyzer does not read
it; all independent detector results are computed by the actual helper and
then selected by ID. Independent QA repeats an unmemoized subset.
Custom configuration contexts bypass that bulk optimization and call the exact
requested-ID helper: an invalid override on a disabled strategy must not change
another arm. A failing regression reproduced that research-cache contamination
before the small bypass; the application detector itself was unchanged.

Reproduction on the same authorized private immutable packets, without any
network, database, AI or order action::

  python research/scripts/compare_entry_strategies.py --expanded-acquisition-result <private-expanded-acquisition-result.json> --comparison-decision-at 2026-10-19T04:53:45.048406+00:00 --memoize --reference-probes --summary-only

The expanded sanitized aggregate is
``research/results/entry_strategy_expanded_comparison.json``. Source packet and
manifest hashes, actual clocks, all12 arm/date counts, reasons and NULL metrics
are retained; raw OHLCV and private paths are not published. Research controls
now include actual6mo Baseline versus2y positive controls, exact calendar-window
slicing, source-clock preservation, missing-source denominators and cached/cold
helper equivalence. This suite is separate from application/lifecycle suites.
The command ``python -m pytest research/tests/test_compare_entry_strategies.py -q``
actually passed27 tests,0 failures/0 skips in14.58s after the PEAD fact-trace
update. Both real/synthetic calculation code hashes were identical and stable.
The final signed replay pins the code actually evaluated, including the final
frozen-rule execution projection and downgrade guard. The guard's independent
lifecycle tests are code-correctness evidence, not a claim of improved
conversion/performance. Earlier diagnostic receipts remain private and are not
silently rewritten or relabeled as final-code executions.

Scope
-----

Compare the existing Baseline with five independent BUY discovery hypotheses:
VCP/Base Contraction, Stockbee Momentum Burst, verified point-in-time PEAD,
Trend Pullback Reclaim and Relative Strength Leader with an actual trigger.
They are alternatives before the old baseline filter and shortlist, not five
additional gates imposed on an already-approved Baseline candidate.

The12 arms use the same frozen paired input frames, availability clocks, common data/
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

Earlier results:20 stocks plus the separately acquired SPY benchmark
--------------------------------------------------------------------

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
