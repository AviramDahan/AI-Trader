Bounded SINGLE breakout and explicit entry window
================================================

Scope and default state
-----------------------

This change implements the approved, measured research hypothesis, not a claim
of trading edge or a quota. Production activation is NOT part of implementation.
Both new server switches default false:

* STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED
* STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED

Existing V2 creation must also be enabled and the strategy must be SINGLE for
the breakout fallback to originate a BUY plan. SELL/SHORT, technical, news,
AI/confidence, budget, sizing and exposure rules are unchanged. PR #59's bounded
target refill/company-news selection is retained. AI candidate limit remains 6.

Policy and actual integration
-----------------------------

single_breakout_v1 is a separate immutable policy, never relabeled as V2:

* Only an exact no_forward_zone rejection can use it. No known resistance,
  unresolved entry zone, invalid source/pivot or distant stop can be bypassed.
* Entry must exceed the high of 20 completed sessions from the same technical
  snapshot. This is NOT an all-time/126-session high.
* The structural stop uses the unchanged .25 ATR buffer, 1.5 ATR/1% floors and
  4 ATR ceiling. A single projected 2R objective is rounded UP to a cent.
* It has one target, fraction 1.0, no synthetic TP2/TP3 and no fabricated Shadow.
* The stored source, zones, high, ATR, levels and decision time are rebuilt and
  validated at admission and fill. Actual slipped/rounded price must preserve
  the breakout, zones, stop distance and gross 2R. Levels never move to rescue it.

The real path is stock_scanner._candidate_target_plan (pre/post AI), _paper_order,
scanner_targets.validate_plan, scanner_engine.record_signal/process_bar,
position/exit accounting, dashboard/chart/Telegram rendering and recovery.
Telegram tests only render into isolated outboxes; they never send messages.

next_complete_5m_v1 freezes created_at, entry_eligible_from and valid_until in
scanner_orders.plan_json.entry_execution, then the trade settings. New SINGLE
BUY plans use the next complete five-minute opening (same opening on an exact
boundary). A candle before eligibility is not executable by contract; no
intrabar path is inferred. Partial expiry and missing eligible candles remain
uncertain. Validity is not extended. Retained orders without the window keep
their original contract. No holds are automatically resolved or released.

Turn either creation switch off to stop the associated new contracts. Stored
contracts continue to execute, exit, display and back up independently of flags.
This is NOT rollback compatibility with an older binary.

Schema, backup and return target
-------------------------------

No migration/DDL is introduced; existing schema 7 JSON and nullable target
columns hold the new contracts. Recovery format 5 is explicit whenever a
breakout or new window is retained. Formats 2/3/4 still apply to old-only state.
Format 5 can contain V1, V2, SHORT, Native, Shadow, Legacy and standalone expired
recovery_uncertain orders together. Order/window/levels/identity/hold coverage
validation is fail-closed. Unknown policies are not silently stripped.

Active-state backup coverage is unchanged: open positions and uncertainty holds,
not an automatic restore of every ordinary pending order or historical returns.
Clean destination/stopped-worker guards stay intact. Holds do not debit cash.
Real age encryption/decryption and isolated PostgreSQL restoration must pass.
An older binary (including 6429c42) cannot read format 5 and is NOT a safe return
target once new contracts exist. Never relabel the backup or rewind the DB.

Proposed future release, requiring deployment approval
-----------------------------------------------------

1. Deploy the compatible code with BOTH new switches false via existing gates.
   Verify all-role SHA/schema/health, accounting, holds and actual encrypted
   export/validate. Save the actual server image ID/build SHA, not a CI tag.
2. Keep that reader/executor-capable image available as the return target. Do
   not enable creation until every relevant service/backup uses capable code.
3. Only with activation approval, enable both new switches in the coordinated
   existing mechanism. No existing order/position is rewritten. No replay or
   synthetic trades/AI/Telegram calls are used for validation.
4. A failure first disables new creation. Binary return can only use the saved
   capable image on the current database. Old 6429c42 is unsafe after new state.

Compatibility is delivered as one capable binary with creation off; this avoids
a window with a new producer but an old backup/reader. The Linux image harness
uses separate processes for prepare, activation, a simulated process failure,
compatible return, restart, age restore, exits and forward return, plus an actual
previous image that refuses format 5. It does NOT claim CI/server image identity.

Evidence and bounded scheduled follow-up
---------------------------------------

entry_repair_audit is a READ ONLY, repeatable-read, timeout-bounded audit. It
rebuilds baseline/new structure using each retained decision's own source/time,
shows unavailable evidence explicitly, caps output, and links new Native
signal/order/trade/entry/exit IDs. It does not execute any historical order.
Use: python -m entry_repair_audit --since <UTC release/activation time>.
An unactivated release is NOT_ACTIVE, not a failed strategy experiment.

Production checks must separate:

* operational invariants: workers/leases/quotes/accounting/hold reservations,
  backup compatibility, no duplicate fills/orders/messages;
* selection change: paired target checks, unique ticker/source structures,
  pre/post-AI rejects and signal/pending/fill conversion;
* performance: Native independent signal results in net percentages and R,
  cost/stop/target behavior, separating Legacy and non-independent Shadow.

More candidates/fills is not proof of better performance. No meaningful outcome
sample or complete decision-time record means DATA_INSUFFICIENT, not success.
No new natural chain means WAITING_FOR_NATURAL_EVENT, not an outage. Scheduled
checks never deploy, activate, generate trades, call AI or alter thresholds.

Regression acceptance
---------------------

Required: same V2 outcomes, narrow no-forward recovery only, future source/pivot
rejection, high/anchor/zone/distance/2R boundaries, post-AI/actual entry changes,
full/incomplete/expiry/data-gap handling, stop priority and gap slippage, restart
dedupe, actual run_scan-to-accounting with mocked external providers, old lifecycle
regression, PostgreSQL/age format 5 round-trip and negative corruption/old-reader
tests, frontend build/RTL rendering and complete existing CI/readiness.

The historical research used 955 frozen checks from 48 of 60 scans (5-9 October):
BUY structural passes 8 -> 68, with 60 additional observations/10 source structures/
8 tickers. Conditional zero-latency AI approval with reconstructed vendor bars
gave 46 valid touches, 12 price rejects and 2 no-touches under the full-bar
contract. These are NOT 46 missed trades, historical AI approvals or returns.
