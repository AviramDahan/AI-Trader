Target / RR diagnosis and accurate explanations
==============================================

Scope and unchanged behavior
----------------------------

This repair fixes misleading explanations and incomplete attribution of retained
target checks. It does NOT change opportunity detection, ranking, AI quotas or
prompts, news, risk, exposure, entry/fill contracts, RR thresholds, stops/targets,
retry/recovery, emergency entry controls or exits. No deployment is implied.
It is not a claim of improved profitability or additional eligible entries.

The four independent price detectors still use the common completed six-month
history for the shared target planner, while their separate longer histories
support discovery. A strategy-specific trigger is not a strategy-specific stop.
The existing known-resistance policy must not skip the nearest resistance, and
the projected-target fallback remains restricted to no-forward-zone cases with
its existing completed-high requirement. Changing these is separate policy work,
not a rounding repair. At least 3.15 ATR raw resistance headroom is necessary
when the existing 1.5 ATR risk floor binds; this is not sufficient for admission.

Correct retained explanations
----------------------------

``invalid_rounded_levels`` remains the unchanged machine rejection code. Its
generic Hebrew/English description no longer asserts that rounding caused the
failure. A retained ``target_buffer_reaches_entry`` subtype leads the displayed
explanation when the unrounded target was already at/below entry. A true
``target_rounds_to_or_below_entry`` remains distinct. Missing/oversized/unknown
evidence never establishes either cause.

Pre-AI summaries cannot borrow geometry or subtypes from a matching post-AI
failure. The mini-app evidence view and research view use the same pure display
projection. They show the retained entry, stop, target, raw/rounded gross RR,
policy threshold and nearest resistance, not new executable levels. Multi-target
policies label their separate ratios and middle/mean threshold rather than
comparing target1 with a target2 requirement.

New observational metadata
--------------------------

Existing V2 diagnostic geometry additionally retains ``risk_breakdown`` version
``single_target_risk_v1``: the structural, ATR-floor and price-floor distances,
selected raw risk and all exactly tied binding constraints, raw reward distance,
required raw reward and nonnegative raw shortfall. A zero raw shortfall is not
approval: rounded-level and all other checks still apply. The diagnostic is
computed after the real planner and cannot change its return or exception.

The target journal also freezes a tiny validated ``discovery_context`` with
version, contributor IDs, primary ID and detection time. Unknown/missing context
is explicit, never assumed to mean Baseline. Contributors can overlap; counts
must not be added as independent opportunities. Detection time must not be later
than the checked decision time. Public readback permits only these fields and
known IDs; arbitrary nested metadata, future or malformed context is withheld.

The existing 64 KiB journal bound, JSON freezing, savepoint failure isolation and
idempotent persistence are preserved. No migration, recovery snapshot change,
extra DB query, external provider call, polling interval or background worker.
These optional fields do not enter order contracts or AI inputs. Older journal
records stay readable without invented historical constraints or contributors.

Validation and limitations
--------------------------

Synthetic tests first reproduce the misleading heading and wrong-phase lookup.
Regression covers exact planner returns/errors, all three risk floors and ties,
unknown/future context, hostile extra metadata, invalid numeric values, source
immutability and duplicate persistence/restart without trading/message writes.
PostgreSQL uses disposable test schemas only. Existing integration tests cover
all four detector paths, shared gates and entry/exit lifecycle with mocked inputs.
No fabricated Production trade or historical AI decision is used as proof.

The dated operational diagnosis is private. Saved arithmetic and detected-route
overlap are not vendor-data validation, historical return evidence or a guarantee
that these candidates should be admitted. A future strategy-specific target or
stop proposal needs isolated comparison with unchanged controls and explicit
review; it must not silently replace this repair.
