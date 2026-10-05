Automatic paper SHORT (disabled until a controlled release)
===========================================================

Policy chosen by the user
-------------------------
Use the existing ``structure_plan('SELL', ...)`` without changing its numerical
policy: three confirmed forward support zones, structural overhead stop, the
existing ATR bounds and minimum RR, SINGLE full exit at TP2. Do not mirror Long
V2 or skip a nearer zone. Technical selection, news, AI inputs/confidence,
candidate cap/refill, Long/V2, Legacy and existing Shadow remain unchanged.

``STOCK_SCANNER_SHORT_ENABLED`` defaults to false. New automatic short admission
also requires active strategy SINGLE. An approved SELL still closes an existing
Long; otherwise the scanner can publish a distinct SHORT signal. Admission
atomically blocks a second entry of either direction while a primary trade or
pending/recovery_uncertain entry exists. It never flips a Long to Short. BUY does
not automatically cover a Short: the short exit contract is TP2/Stop. The original
generic immediate-execution API is NOT used. Signal approval is not a fill.

Stored short_structure_v1 includes the bearish plan, decision/source timestamps,
strategy and captured execution settings on the order. Source candles and zone
confirmations must be available at decision time. At fill, levels, original risk,
ATR bounds, unresolved zones and actual RR are checked without moving levels.
SELL LIMIT fills cannot be below the limit; TP2 is a BUY LIMIT. A gap Stop has
adverse slippage and no guaranteed price. Stop wins a same-bar TP/SL ambiguity;
an entry bar cannot receive a favourable TP. Only complete, in-validity candles
can execute. Missing/boundary evidence follows the existing uncertainty hold.
Turning off creation does not disable existing orders, holds, positions or exits.

Only the selected SINGLE short is created, not an unapproved STAGED short/Shadow.
The three structural levels remain stored; TP2 alone is the operational 100% exit.

Paper accounting limitations
----------------------------
The original generic paper short convention is retained: entry notional plus
commission is deducted as collateral, not credited as sale proceeds. Cover
returns ``(2 * entry - cover_price) * quantity - fee``. Unrealized/gross P/L is
``(entry - mark) * remaining_quantity``. Cash plus marked collateral is equity;
do not add realized P/L or fees twice. Severe adverse gaps may make cash negative;
do not clip losses or claim a guaranteed Stop. No real borrowing, borrow fees,
locates, recalls, margin/forced liquidation or broker execution are simulated.
Displayed net results include simulated commissions, NOT unmodelled borrow costs.
Percent/R measures are position results, not portfolio returns or proved edge.

Recovery and release boundary
-----------------------------
No database migration: schema 6 already has plan_json and side/action fields.
An active Short or a standalone uncertain short order requires Recovery-State
format 4. Formats 1/2/3 retain their existing reader rules. New readers retain
the short contract; old readers reject format 4. Validation covers linked
signal/order/trade, descending targets, side, reservation manifest and fills.
Exports remain read-only consistent snapshots; restore requires an empty isolated
DB and stopped workers. Pending order auto-restore is NOT added by this work.
Creation flags are not automatically enabled by restore.

Do NOT roll back to a Long-only binary after any Short data has been created,
even if the position is now closed: its accounting readers do not understand the
short collateral flow. A creation kill switch is not binary compatibility.
Future release order (not executed by implementation/tests):

1. Run full Linux backend/PostgreSQL/real-age restore tests and review the diff.
2. Deploy the short-aware code with new creation OFF; verify all roles, backups,
   accounting and leases. Pin the actual deployed image as the compatible return
   target. Before any short data, the previous Long-only image is still usable.
3. Only after the compatible image is active/retained, enable the flag in the
   existing protected runtime configuration with coordinated restarts. No trades
   or public messages are fabricated to prove readiness.
4. On activation trouble, disable creation and keep the short-aware manager
   running. Any binary rollback must use the retained short-aware image/current
   database. No DB rewind, status conversion or release of uncertainty holds.

This branch has no deployment authorization/action. No live settings, providers,
AI budget, historical records or positions are changed by these tests.
