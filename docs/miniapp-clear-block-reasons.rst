Mini App: clear retained blockers
================================

Scope
-----

Presentation explanations in the existing public Mini App, stock journey,
website station cards, signal research and paper Telegram notifications.
No scanner gates, thresholds, strategy, execution rules, AI calls or refresh
cadence changes. The existing Telegram outbox delivers state updates.
No migration, new storage or production configuration is required.

Each of the eight stations explains what it checks and what passing it does
not establish. Stock lists show a specific retained blocker without opening
the stock. Details explain its meaning, other blockers from the same decision,
the relevant saved values and thresholds, and what progression would mean.

Evidence rules
--------------

* A repeated ticker is not a linked decision. Orders must match the exact
  signal ID; target detail must match the retained rejection in the same scan.
* Only retained scores, thresholds, reference prices and target geometry are
  shown. Current defaults and newer scans never fill historical gaps.
* HOLD, processing failure, session wait, selection allowance and allocation
  blocks are distinct. Allocation failure is not a signal-quality rejection;
  its cause is not presumed to be cash when no cause was retained.
* Pending is not proof of a price touch or fill. Recovery uncertainty and an
  unlinked reported fill are not active positions. Terminal orders are not
  revived by this read-only view.
* Missing values say "Not retained". Unknown codes say that detailed evidence
  is unavailable; the code remains in the technical disclosure. Missing is
  neither zero nor a passed gate.
* Retained model explanations are escaped and bounded. They remain in their
  retained language, are explicitly not verified facts, and trigger no new
  translation or model calls.

The read-only research API adds only minimum_rr, completed_high and
completed_high_sessions from the existing target-check allowlist. Private
source fields and prompts stay excluded. Old API payloads remain readable;
they simply lack the additional numerical facts.

Verification
------------

Frontend: npm run test:activity, npm run test:research,
node test-signal-presentation.cjs and npm run build.
Backend: tests/test_signal_research.py and tests/test_entry_rejection.py.
PostgreSQL: tests_pg/test_signal_research_pg.py in an isolated test schema.
Existing CI/Cloud Readiness run the full Linux backend/PostgreSQL suites.

tests/miniapp-harness.html is a development-only synthetic fixture. Its
"reasons" mode covers RR, rounding, breakout high, HOLD, multiple AI gates,
timeout, unknown cause and market-session wait. It is not a live provider or
Telegram test and is excluded from the production Vite entry.

Responsive manual checks cover 360/390/430 pixel phones, short-sheet vertical
scrolling, all eight station sheets, stock/journey navigation, desktop,
Hebrew/English, and loading/empty/error/stale states. Publication still uses
the existing protected release mechanism; creating a PR does not deploy it.

Paper Telegram clarification
----------------------------

Signal alerts explicitly distinguish pending entry, allocation/duplicate blocks,
pending exit, HOLD and bearish-only indications, without raw status enums.
Validity/entry-window times are shown in Israel time from aware retained times.
Only an actual entry fill produces the existing active-position entry alert.
The open-position status card excludes pending orders and explains this.

An actual order transition to invalid, risk_rejected, recovery_uncertain or
expired queues one signals_status update through the existing outbox, routed
to the existing signals topic and gated by the existing entry-alert switch.
The key is order-status:<order ID>:<stored status>. Restart/repeated processing
cannot queue a second copy. Initialization/restore do not backfill old failures.
No Telegram message is sent by the monitoring transaction itself. Existing
fills, quantities, fees, reservation and TP/SL calculations are unchanged.
Rejections use only allowlisted reasons, never arbitrary exception content.
Unknown historical causes stay explicitly unavailable; no fill is guessed.
The existing signals_status event/route is understood by the previous binary;
no new event type, topic, provider, schema or dispatcher is introduced.

tests/test_paper_execution_alerts.py and its isolated PostgreSQL counterpart
cover a full pending-to-rejected chain, valid entry, expiry, uncertainty,
unchanged balances/reservation, restart/dedupe and mocked delivery/switches.
