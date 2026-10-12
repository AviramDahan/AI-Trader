Time-correct evidence for final stock review
==========================================

Finding and scope
-----------------
Natural scans after the entry repair reached final AI review but returned HOLD.
The scanner substituted the fresh quote into candidate.entry while retaining
candidate.price_as_of and volume_ratio from the previous completed daily session.
The prompt did not explicitly distinguish those time bases, and the existing
one-minute quote response's completed price-action observations were discarded.
Retained explanations consequently described missing breakout confirmation or
weak breakout volume. This is an input/provenance limitation, not proof of a
profitable false negative or evidence that the model must return BUY.

The two input-contract regressions fail before this correction: daily volume
appears as an unqualified candidate field, and the current entry still shares
the previous daily price-date field. Historical AI decisions are not replayed
or reconstructed. The correction changes evidence presentation, not the model,
decision schema, score/confidence thresholds, direction, target or exit policy.

Real integration
----------------
``current_intraday_quote`` makes the same single, existing Yahoo 1m request.
Its two-value tuple-compatible quote now carries bounded evidence derived from
that response. At most six completed, regular-session five-minute bars are
assembled from exactly five distinct valid minute rows each. Unfinished/future
minutes, duplicates, gaps, prior sessions, missing volume and invalid OHLCV do
not become completed bars. Completion is bounded by request START, with response
receipt recorded separately, so a request straddling a bar boundary cannot
retroactively turn an earlier in-progress response candle into a completed bar.
No provider request, price-cache refresh or AI call
is added. This evidence is not an execution replay or a prediction of intrabar
order. The order executor still requires its own subsequent eligible full bar.

Before the existing provider call, ``run_scan`` freezes ``review_evidence_context``
into the existing pre-AI ``target_check`` observation. It contains:

* Completed-daily metrics and session date, compared to the existing completed
  session calendar; a correctly current previous session is not called stale.
* Current entry quote with its own timestamp and age.
* Bounded completed intraday OHLCV, their availability timestamps, gap coverage
  and freshness; each close can be compared factually to the saved breakout high.
* Target policy provenance, distinguishing a projected 2R target from a confirmed
  resistance level. No stop/target/RR is changed.

The AI-only projection moves daily metrics out of ambiguous flat price fields.
The prompt forbids treating completed-day volume as current breakout volume.
There is no fabricated same-time-of-day relative volume: a comparable prior
session denominator is not available from this request and remains UNKNOWN.
Six observed bars do not automatically constitute confirmation, and no minimum
volume threshold or mandatory BUY is introduced. HOLD remains valid.

Failed evidence capture is best effort and cannot introduce a new trading block.
The snapshot is numeric/provenance data, not prompts, raw model output, news text,
credentials or chain of thought. It is bounded to 8KiB inside the original bounded
observation and is persisted once before IO, even if the subsequent review fails.

Safety and compatibility
------------------------
Existing news/technical/target/quote/session/confidence/sentiment/budget/risk,
duplicate protection, six-review cap and paper lifecycle gates remain intact.
The original candidate, signal/order plan and existing positions are not rewritten.
Nothing is initialized from a UI request and the monitor has no new IO dependency.

No migration, live configuration change or recovery-format change is required.
Schema remains 7. New optional data resides in the existing candidate journal;
old readers can ignore it. Binary return to the current compatible application
uses the current database and existing release mechanism, never database rewind.
No merge or Production deployment is performed during preparation/testing.

Verification and limits
-----------------------
Synthetic clocks/providers exercise missing/incomplete/future/duplicate/old data,
quote signature/freshness invariance, explicit daily-date separation, a valid HOLD
despite positive observations, pre-call durable evidence and BUY through actual
signal/order/entry/exit/accounting/restart on disposable SQLite/PostgreSQL.
Existing lifecycle/refill/quote/budget guards are also regression-tested.

Fixtures and parser tests do not prove a live provider works or that AI will
approve more entries. No new historical AI decision, future candle, fake fill
or retrospective profitability is asserted. Already discarded intraday evidence
cannot be reconstructed from retained single-price quotes; new snapshots are
prospective only. Observe natural final decisions and linked entries after any
separately approved release, without paid test calls or forced scans.
