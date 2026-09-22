# Structural targets and displayed prices

New scanner signals use `confirmed_daily_swing_zones_v1`, not an LLM-generated
price forecast. Old signals, open positions and their settings remain unchanged.

Using the existing daily history cache (up to 126 completed sessions), highs and
lows are confirmed with two bars on each side. The current daily candle is
excluded. Pivots within 0.5 ATR form a zone. Both former highs and lows can change
roles after a break. Each zone retains its observed dates and touch count.

For BUY, the first three zones above entry give targets 0.15 ATR before the
near edge. SELL mirrors this using lower zones; it never opens a short.
The stop uses the nearest opposite zone plus 0.25 ATR buffer, with risk at least
1.5 ATR and 1% of entry. Risk beyond 4 ATR is rejected. TP1 must offer at least
1R; TP2 and the weighted plan must meet the existing minimum risk/reward. The
scanner never skips a nearby obstacle to manufacture a favorable ratio.
Insufficient zones (including price discovery above all observed levels) means
no published signal, not extrapolated targets. This stricter experimental method
may substantially reduce coverage; no predictive edge has been demonstrated.

One third at each target remains the quantity-allocation rule, NOT a price
increase of 33%. The prices and resulting R ratios vary with observed structure.
Single remains operational (TP2); staged remains shadow. New structural targets
are preserved at actual entry, not replaced by fixed R multiples. Older pending
fixed-R plans retain their previous behavior.

## Explicit revision of already-open paper positions

Open positions are never silently retargeted by the scanner. A user-requested,
one-time revision can be prepared with
`python scripts/revise_open_position_targets.py` and applied only after review
with `--apply`. It runs only while the US market is closed, downloads five years
of adjusted daily history plus the completed latest session, creates a SQLite
backup, and refuses any trade that already recorded a TP fill.

The revision method `daily_resistance_and_measured_move_v1` preserves entry,
quantity, original/current stop, original R, fills and accounting. It first uses
confirmed overhead daily resistance zones. Where price discovery leaves fewer
than three overhead zones, it fills the gaps with clearly labelled measured-move
objectives projected from the completed 20-session high/low range. These are
chart projections, not claimed resistance or forecasts. Every before/after value
and the full evidence snapshot is stored in `scanner_target_revisions` and in the
trade settings snapshot. Re-running an unchanged plan is idempotent.

Current/last prices in signal cards are served from a persistent server cache:
the signal's verified quote, then completed 5-minute monitor bars. No network or
LLM call is made on page opening. Timestamp and source are shown, prices older
than 15 minutes are marked stale (including market closures); missing prices
are never replaced with entry. Historical inactive signals are not continuously
refreshed. Yahoo data can be delayed and is not a real-time exchange feed.

Conceptual references (not evidence validating this implementation):
- https://www.fidelity.com/learning-center/trading-investing/technical-analysis/support-and-resistance
- https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr
