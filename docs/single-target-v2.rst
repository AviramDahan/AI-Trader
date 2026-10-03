SINGLE Target Policy V2 (review only)
====================================

Scope
-----
Only new BUY plans when SINGLE is selected AND the default-OFF environment flag
STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED=true use single_target_v2. The bridge
additionally has CREATION_CAPABLE=False. Disabling creation never disables
handling of stored contracts. See single-target-release.rst for release order.
Technical ranking, News, AI input, candidate cap/refill, SELL, sizing and existing
positions are unchanged. Source-only provenance is stripped from the AI payload.
V2 uses completed daily source candles/ATR and pivot confirmation timestamps.
The nearest overhead zone supplies the only target, 0.15 ATR before its low.
The stop is structural (0.25 ATR buffer), with existing 1.5 ATR / 1% minimum
distance and 4 ATR maximum. Raw and stored rounded gross RR must both be >= 2.
No ticker exception, projection or skipping nearer resistance is permitted.

Durable contract and lifecycle
------------------------------
scanner_signals.technical_json.target_plan is immutable admission evidence.
scanner_orders.plan_json contains its exact copy plus captured execution settings.
scanner_trades.settings_json.target_plan retains the same plan after entry.
The contract includes policy version, BUY/SINGLE, levels, all source zones,
source-data timestamp and decision timestamp. Fill validation uses the actual
slippage-adjusted price without moving either level. Gaps into an unresolved
zone, changed nearest resistance, invalid stop distance or RR < 2 fail closed.
Incomplete candles cannot advance a V2 ticker cursor. Existing expiry/recovery
uncertainty and conservative same-bar stop-first rules remain in force.
The active target is stored in tp1; tp2/tp3 and rr2/rr3 are NULL, not fabricated.
Fractions [1,0,0] mean one 100% exit. There is no synthetic STAGED contract;
comparison is unavailable, not a zero-return trade. Existing pairs are untouched.
The comparison aggregate excludes unpaired trades.

Display
-------
Signal eligibility is separate from simulator execution status. RISK_BLOCKED
does not revoke quality qualification or claim an activated position. Existing
cash/risk checks are preserved. Results are position-weighted percentages and R:
realized net includes fees paid; open gross excludes hypothetical exit costs.
They are not portfolio returns. Telegram transport is unchanged; tests render
messages and charts without delivering them.

Compatibility and release limitations
-------------------------------------
Migration 006 relaxes unused legacy target slots and adds order plan_json.
It does not rewrite historical rows. Production PostgreSQL requires this numbered
migration before these binaries can pass readiness. Existing SQLite databases
with NOT NULL target slots require an explicit offline schema upgrade; this PR
tests fresh isolated SQLite and PostgreSQL, not a live SQLite migration.

Snapshots with V2 contracts use version/recovery_format 3. Readers here validate
1/2/3; restore permits 2/3 with explicit hold coverage, and format 3 requires
schema 6. Older readers reject 3. V1-only snapshots stay format 2. Sanitization
retains only the V2 plan, not news, AI prompts or unrelated candidate metadata.
Backup scope remains open positions plus recovery_uncertain orders, not all
normal pending orders. A held V2 order retains its plan and reservation.

Rollback to pre-V2 binaries is NOT safe immediately after migration 006, even
before any V2 signal/order/trade exists:
they assume three targets, lack the order contract and require schema 5. Do not
retag backups, drop NULL levels, rewrite old orders or restore an older database
to force compatibility. The codex/single-target-v2-compat prerequisite supplies
the complete compatible rollback binary; see single-target-release.rst.
No migration, merge or deployment is performed by this PR.

Existing sample comparison (not execution/performance evidence)
--------------------------------------------------------------
Cutoff 2026-10-03T07:30:51.083599Z, 59 regular-session scans, 1475 shortlist
appearances; 21 existing no-news exclusions. Among 507 BUY appearances:
V1 PASS / V2 PASS = 0; V1 FAIL / V2 PASS = 12;
V1 PASS / V2 FAIL = 0; both FAIL = 495.
Unique (ticker, daily source date, daily reference price) configurations:
0 / 1 / 0 / 59 respectively. The 12 recovered appearances are one historical
SMCI configuration: entry reference 43.2599983215, stop 39.77, active target
51.05, gross RR 2.232093245. SELL's 947 appearances (112 configurations) remain
unchanged, all structurally rejected in this sample. No V2 trade was executed.

Historical pivot rows lack exact confirmation timestamps. Their known two-later-
completed-bar producer contract allows a conservative confirmation upper bound
at the saved source cutoff; it does not prove the exact confirmation instant.
147 BUY rows have an uncompleted source date at the historical decision and are
rejected, not reconstructed from future data. Fresh V2 candidates now store a
separate completed source structure rather than borrowing an unfinished quote
date. The historical matrix is daily-reference structural eligibility only,
not fill eligibility, a current signal, predicted return or proof of profitability.
A synthetic regression explicitly covers V1 PASS / V2 FAIL at nearer resistance.
