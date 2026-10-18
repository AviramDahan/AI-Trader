VCP POC: reproducible comparison and evidence limits
==================================================

This is a partial component comparison, not a new trading/backtest framework.
It does not create signals, orders, fills, model decisions or a second portfolio.
No Production, provider, model or Telegram request is made. The existing pure
target builders and the VCP adapter run on the same source/decision/reference.
The engine's existing pure market-session calendar is reused; no new calendar
or holiday policy is introduced.

Contract
--------

* Baseline A is existing BUY/SINGLE V2 target geometry, including only the exact
  ``no_forward_zone`` fallback to ``single_breakout_v1``. This is NOT approval by
  Technical, News, AI, cash, exposure, hours or full-bar execution gates.
* Candidate B filters only an already-valid ``single_breakout_v1`` plan with
  confirmed as-of VCP evidence and fresh reference-price validation. Known
  resistance, insufficient RR and all other baseline failures remain failures.
  Non-breakout V2 approvals are unchanged. Ranking is not modified in this POC.
* Completed bars and optional ``available_at`` are cut at the original source
  observation and decision times for BOTH arms. Future/uncompleted rows cannot
  change source deduplication. Missing evidence is UNKNOWN, not a losing trade.
* Observation IDs, ticker/source structures and source/reference configurations
  have separate counts. Repeats are not independent trades. Conflicting duplicate
  observation IDs are rejected, not silently overwritten.
* Net expectancy R, WR, PF, drawdown, holding period and signal-entry conversion
  remain null/DATA_INSUFFICIENT without a complete historical decision and
  closed Native trade/fee ledger. No intrabar path or historical AI is invented.
* The same existing LIMIT, costs, slippage, full-bar, stop-first and TP/SL rules
  would apply to both arms; this tool does not simulate execution or silently
  introduce a next-open or buy-stop fill assumption.

Commands
--------

Run from the feature checkout with the existing server Python dependencies::

  python -B -m unittest discover -s research/tests -p test_compare_vcp_breakout.py -v
  python -B research/scripts/compare_vcp_breakout.py --synthetic-fixture --summary-only
  python -B research/scripts/compare_vcp_breakout.py --history-cache <authorized-local-cache.gz> --summary-only
  python -B research/scripts/compare_vcp_breakout.py --frozen-case-packets <authorized-single-case.json> <authorized-batch-case.json> --summary-only

Optionally add ``--retained-funnel <authorized-dated-aggregate.json>``. It reports
that aggregate separately; it does not join it to older prices. There are no URL,
fetch, database, worker, model, parameter-search or execution options. Network and
subprocess use are blocked during evaluation. Output is JSON on stdout; the tool
does not copy raw OHLCV or case sources. Private inputs must never be committed.

An explicit JSON dataset can instead be supplied with ``--dataset``: ``version``
is1, ``synthetic`` is an explicit Boolean and ``observations`` contain ticker,
observation_id, timezone-aware decision_at/source_observed_at, reference_kind,
reference_price, optional reference_at/source_inputs and chronological OHLCV bars.
The tool hashes the input and reports the kind of reference; a daily close is
never relabeled a live quote or executed entry.

Results actually obtained, 18 October2026
---------------------------------------

See ``results/vcp_poc_comparison.json`` for sanitized aggregates and input hashes.
Raw retained sources and the old cache remain private. Three distinct cohorts
must not be pooled:

1. Existing cache observed26September02:28:12UTC:523 symbols,72-127 daily bars
   (March17-September25). No symbol has200 bars or the required253-bar VCP
   warmup. All523 VCP evaluations are UNKNOWN. Four reference-geometry approvals
   are existing nearest-resistance V2 plans, unchanged in B;519 failures are
   unchanged. There are ZERO applicable approved breakout plans. A daily close
   cannot exceed its same source's20-session high, so this reference cohort
   cannot measure VCP selectivity, quality, neutrality or profitability.
2. Twelve retained16October source/quote cases were independently recomputed
   using the unchanged target builders. A0/B0, all12 still
   ``invalid_rounded_levels``; VCP evidence UNKNOWN because the complete original
   OHLCV is not archived in these packets. This reproduces12 cases, not all87.
3. An explicitly invented253-session fixture has5 appearances/four source
   configurations. Baseline A approves4 appearances/three source configurations;
   B retains2 appearances of the SAME one valid setup, filters one weak-volume
   trigger, leaves one insufficient-warmup case UNKNOWN and preserves the
   existing resistance/RR rejection. These are calculation controls, not trades
   or historical/out-of-sample performance.

The separately retained16October aggregate has94 observations,88 tickers and
two scans:87 structural failures, six waiting-for-session rows and one AI HOLD.
Structural reasons are28 nearest-resistance<2R,16 inside-zone,13 old-policy RR,
12 invalid levels,10 old-policy insufficient zones and8 below completed high.
The structural ratio87/94 is92.55% of observations, NOT an AI rejection rate or
trade-loss rate. Nominal requested end20:08UTC is kept separate from effective
snapshot end20:05:07.943146UTC. Without changing the protected gates VCP cannot
rescue those87 failures; complete per-row source histories are unavailable for
assessing the other seven. No later cache is substituted retrospectively.

Nineteen research tests passed, zero failures/skips, including a cold CLI import,
real adapter/target calls with synthetic bars, source-clock and per-row
availability controls, future-bar invariance, deduplication and denominator
checks. The existing urllib3 secure-extra deprecation is not a new POC failure.
Full application, PostgreSQL and lifecycle tests are reported separately by the
Trading and Independent QA roles, not claimed as research backtest proof.

Decision
--------

GO for isolated implementation/independent code validation only.
NO-GO for activation with current history coverage.
DATA_INSUFFICIENT for net performance improvement or reduced missed entries.

Minimum missing evidence is actual253+session as-of source coverage for relevant
qualified breakouts, original quote/availability times and an actual historical
review/order/exit/fee ledger, or an explicitly detector-only chronological
comparison. Historical universe/corporate-action basis must also be documented.
There is no arbitrary number of collection days or optimized parameter grid.
Keep the default-OFF switch unchanged; no deployment or activation is authorized
by these comparison results.
