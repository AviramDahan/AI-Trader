Independent intraday entry evidence experiment
==============================================

Status and boundaries
---------------------

``STOCK_SCANNER_INDEPENDENT_INTRADAY_ENABLED`` defaults to false. This is a
separately versioned, uncalibrated Paper experiment, not a performance claim or
an instruction to generate positions. PEAD and the original Baseline remain
unchanged. Existing daily-confirmed detections remain valid OR alternatives;
the intraday path does not replace them, add an AND condition, or move their
levels. New creation is disabled in a Bridge build, but retained management is
independent of the current creation flags.

The unchanged common liquidity/ATR, nearest-resistance 2R, stop/risk floor,
News, AI, exposure, sizing, fees and TP/SL rules still decide whether an
opportunity becomes an admitted, pending and eventually filled order. A
confirmed detector is not an executable quote, admission or trade.

Two stages in the existing bounded scanner
------------------------------------------

1. ``entry_intraday.prepare_setups`` consumes only completed, available prior
   daily bars. It freezes the daily pivot/support and a 3 percent chase ceiling.
   Qualified records stay FORMING with ``intraday_confirmation_pending``.
   Private ``_intraday_setups`` may participate in the same fair strategy queues,
   one-ticker deduplication and global shortlist/AI quotas. They are never
   executable ``entry_discovery`` attribution.
2. ``entry_discovery.needs_intraday_volume`` performs the cheap setup/price
   check against the existing quote's actual completed regular 5m evidence.
   The scanner owns acquisition limits. ``confirm_intraday_candidate`` promotes
   only after the completed price witness and strict causal RVOL proof both
   validate. A failed optional confirmation preserves a valid Baseline or
   daily alternative, including legacy Baseline inputs without an audit clock.
   No missing provenance is fabricated.

The four routes remain OR, not cumulative confirmations:

* VCP: prior confirmed contractions, trend and volume dry-up, followed by a
  completed 5m close above the frozen prior pivot.
* Stockbee: prior daily consolidation plus a completed 5m burst. Price shape
  requires at least one of: 4 percent gain over the prior daily close, a
  0.90-dollar positive candle body, or range above the prior three daily ranges
  with prior-day gain at most 2 percent. Close location is at least 0.75 and
  measured cumulative volume at least 100,000. A volume-only tag is insufficient.
  These are explicitly new intraday hypotheses, not equivalent daily outcomes.
* Pullback reclaim: prior daily uptrend, pullback and EMA20 touch, then a bullish
  completed 5m close above the frozen reclaim level and SMA50. EMA20 support is
  retained for the new execution contract.
* Relative-strength leader: causal, date-matched SPY comparison and prior daily
  base/trend, then a completed 5m break with the existing close-location rule.
  Both equity and benchmark must have recorded adjusted-price basis.

RVOL and clocks
---------------

RVOL is cumulative regular-session volume from open through the exact completed
5m boundary, divided by the mean SAME clock-offset cumulative volume from ten
prior fully covered sessions of the same session length. It is not last-5m
volume divided by full-day volume. The versioned new policy requires ratios
1.5 for VCP, Stockbee and RS, and 1.0 for Pullback. These thresholds are not
optimized, empirically validated or assertions of profitability.

``intraday_volume.public_evidence`` is the shared strict pure reader for both
new confirmation and retained proof. It validates explicit Yahoo adjusted-OHLC /
unscaled-reported-volume basis, action coverage, ten prefix samples, arithmetic,
finite types, exact boundary and source/observation/decision clocks. A missing
history, split ambiguity or unavailable calendar is UNKNOWN, never a neutral
or positive ratio. The bounded normal history window may not contain ten prior
half-days; an otherwise valid half-day price witness still cannot invent them.

Creation uses the authoritative pinned XNYS calendar, including holidays, DST
and early close. A witness must be fully completed, contiguous, current-session
regular 5m data; unfinished/future rows and stale prior-session witnesses cannot
promote. Quote and witness age at admission are at most 720 seconds. The current
quote must remain above the frozen trigger and within its frozen chase limit.
The new path requires an explicit ``yahoo_auto_adjusted_v1`` source stamp.
Merely enabling a flag does not stamp or refresh an old cache retroactively.

Frozen versions and recovery
----------------------------

The provisional version is ``independent_entry_setup_intraday_v1``. Confirmed
records are ``independent_entry_discovery_intraday_v1`` under policy
``completed_regular_5m_prior_daily_setup_v1``. Attribution uses
``entry_discovery_intraday_v1``; independent-only saved execution uses
``independent_entry_execution_intraday_v1``. Any retained new attribution,
including a mixed Baseline alternative, requires snapshot format 10 and an
explicit format-10-capable same-source Bridge proof before any live activation.
Old v1 records and order contracts are not rewritten or reinterpreted.

Cold readers validate frozen typed session bounds, OHLC, volume proof, source
clocks, hashes and evidence IDs without consulting today's calendar/provider.
Creation establishes authoritative calendar provenance; a hash is not an
authentication signature, and a complete malicious rewrite of trusted DB
state is not made authentic by rehashing it.

The original frozen LIMIT expiry and eligible-bar execution window remain in
force (normally 24 hours). Later valid bars, including a following session,
may retry at the original levels under all original guards. Admission proof
freshness does not silently shorten order lifetime or claim the trigger was
continuously refreshed. A rejected touch does not debit funds or infer a fill.

Diagnostic repair, not historical reconstruction
------------------------------------------------

An invalid consumed daily OHLCV now retains only a strict bounded diagnostic:
predicate, actual source/decision clocks, consumed-prefix count, first failing
session and SHA256 through the first failing row. Raw values are not retained,
later/future rows cannot change that fingerprint, and the original UNKNOWN
outcome remains unchanged. The prior missing five-scan snapshots remain
NOT_VERIFIED; new fingerprints cannot reconstruct their original cause.
