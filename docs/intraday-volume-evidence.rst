Intraday cumulative relative-volume evidence
============================================

This measurement does not authorize BUY, change ranking, create a trading gate,
or establish profitability. Acquisition is off by default. Missing evidence is
``UNKNOWN``; it must not be described as weak volume or replaced by zero/one.

Version and definition
----------------------

``intraday_cumulative_rvol_v1`` compares cumulative reported share volume from
the current XNYS regular-session open through a completed five-minute boundary
with the arithmetic mean at the identical elapsed regular-session offset in the
last ten prior comparable sessions. It is NOT the latest five-minute candle's
volume divided by a daily average. No ratio threshold is defined by this module.

The current numerator requires every completed one-minute OHLCV row from open
to that boundary. The denominator uses five-minute OHLCV rows and requires full
coverage of each prior session, not just its prefix. The prefix contributes to
the denominator; its later afternoon volume does not. There is no gap filling,
interpolation, skipping a damaged recent sample for a more favorable older one,
or inclusion of the unfinished current minute/five-minute bucket.

Ten prior sessions is a coverage requirement for publishing the statistic, not a
trade threshold or a tuned strategy parameter. Less coverage remains UNKNOWN.
Complete observed zero current volume can produce a known ratio of zero; zero
or unavailable denominator produces UNKNOWN, never infinity or an invented one.

Calendar and source basis
-------------------------

The optional local ``exchange_calendars`` XNYS calendar supplies timezone-aware
open/close instants, holidays, special closures and early closes. No network or
installation is performed by this module. Missing calendar support is UNKNOWN
and does not authorize an acquisition. Daylight saving is handled by actual
America/New_York session instants, not a fixed UTC opening hour. Half-days are
only compared with half-days of the same duration; a one-month response usually
does not contain ten such comparators, so a half-day will remain UNKNOWN.

``session_schedule(start, end)`` returns open/close columns and calendar ID/version
attributes. ``session_bounds(day, schedule=None)`` returns a dictionary with aware
UTC ``open``/``close``, ``duration_minutes``, session and calendar identity, or
raises ValueError for a closed/unknown/noncomparable day. It is not an execution
calendar replacement. Synthetic schedules in tests are explicitly identified.

Both frames require explicit recorded source dictionaries: Yahoo provider,
``auto_adjust=True``, ``actions=True`` and ``reported_shares_unscaled`` volume
basis. Current interval is ``1m``; historical interval is ``5m``. Yahoo/yfinance
OHLC auto-adjustment does not itself prove that volume units are comparable.
Missing action columns, unknown basis, or a recorded split in the comparison
range is UNKNOWN rather than a guessed split-adjustment of volume. Dividends do
not supply or substitute a volume denominator. This is a current observation,
not a claim that retrospectively obtained provider data were historically PIT.

Clock and provenance contract
-----------------------------

``evaluate`` is pure and requires aware decision, current-observation,
history-observation and completed-before clocks. No source observation or cutoff
may be after the decision. Each prior session must have completed before its
history snapshot. An optional row ``available_at`` must be no earlier than its
bar completion and no later than the snapshot clock. Required future/unavailable
rows are not silently used. Consumed row values, availability, source metadata,
clock fields and calendar version bind the evidence SHA256. Unconsumed future
suffixes cannot change the measured prefix or its content fingerprint.

Verified output includes ``as_of`` and ``completed_through`` (the same completed
five-minute UTC boundary), source clocks/hash, numerator, denominator mean,
ten session dates and sample volumes, exact coverage counts and calendar
identity. It is evidence only. A strategy consuming it must distinguish this
cumulative statistic from any versioned single-candle volume rule; reusing a
numerical threshold does not establish equivalence or historical performance.

``public_evidence(value, decision_at=..., completed_through=...)`` is a pure
allowlisted projection for the retained AI context. Its witness argument is an
exact completed five-minute end, not a request cutoff containing seconds. It
checks version, source identity, clock order/freshness, source-hash format,
calendar identity, ten distinct prior dates, complete-session/prefix row counts
and numerator/mean/sample/ratio arithmetic. No arbitrary nested keys are copied;
unknown reasons are fixed codes and expose a null statistic. It does not call
the calendar, cache or provider, and cannot independently re-prove raw source
rows or historical calendar truth from a hash. Original observation times remain
original; projecting evidence never refreshes stale timestamps.

Bounded optional acquisition and cache
--------------------------------------

``get_evidence(..., enabled=False, fetcher=None)`` performs no provider or cache
filesystem access. Enabling requires the literal boolean True; strings and
numeric truthy values are not authority. Acquisition also requires an explicit
existing-provider adapter; there is no new provider, worker, model or paid call.

When enabled, acquisition requests at most one Yahoo ``1mo``/``5m`` history
response per cache miss, with regular hours only, auto-adjust/actions enabled,
repair/rounding disabled and a fifteen-second timeout. History/current row caps
are 3,000/600. The caller enforces its existing per-scan budget of at most six
acquisitions; an additional in-process guard allows at most six in 300 seconds.
No blind retries occur: failures are negatively cached for five minutes.

Per-symbol receipts retain actual post-response observation clocks and exact
serialized payload hashes. Private atomic replacement writes use restrictive
permissions. Cache capacity is bounded; only an internally validated owned
receipt can be evicted, never an unrelated/corrupt file. Corruption or write
failure is UNKNOWN. A restart can reuse a valid durable receipt, but cannot
reinterpret an observation after the supplied decision as an earlier one.
The existing sole scanner lease remains responsible for cross-worker ownership.

``acquire=False`` is guaranteed provider-free and can evaluate an already
collected snapshot at a later ACTUAL decision clock. A fresh fetch received after
the caller's earlier decision clock correctly yields UNKNOWN on that first
call; callers may prewarm before their quote observation or explicitly perform
a second cache-only evaluation with the real later clock. No timestamp is
rewritten to manufacture availability. Quotes and entry guards remain separate.

Verification limits
-------------------

The implementation is tested with synthetic providers, session data and private
temporary cache directories, with external network and PostgreSQL access denied.
Those tests demonstrate arithmetic, provenance, safety and bounds; they do not
prove real provider completeness, natural Paper entries, win rate, expectancy,
profit factor or profitability. No real history/AI/Telegram request or Production
change is needed or authorized by these tests.
