System-team audit and focused correctness fixes
===============================================

Scope and operating contract
----------------------------

The coordinator owns the evidence register, file ownership, integration review
and final decision. Specialists cover trading, SEC/news data, infrastructure and
security, AI validation, UI/Telegram presentation, independent QA and improvement
proposals. At most three specialists run alongside the coordinator. This is a
bounded audit workflow, not a permanently running trading service or a new
scheduler. An agent's availability is not a prerequisite for cloud monitoring.

Production inspection is read-only. A specialist reports the reproduction,
impact and smallest proposed fix before receiving ownership of specific files.
Tests use isolated databases and mocked external providers. A different reviewer
checks the combined patch. Branch publication does not authorize merge, migration,
configuration changes or deployment. Release approval is a separate decision.

Confirmed defects covered by this patch
--------------------------------------

* Recovery previously treated a touched BUY limit as proof of entry even when
  the frozen V2 contract rejected that actual price and permitted a later retry.
  Recovery now uses the same contract and fill-price checks as execution. A
  subsequent missing eligible candle keeps the order blocked and reserved.
* A discretionary SELL close order could close a replacement long on the same
  ticker after its original position had closed. The retained close key now
  resolves only the original primary trade and its own paired shadow. Missing,
  closed or invalid links terminate the request without a new fill.
* SEC lookup filtered eligible rows before choosing the latest state and used
  a global row cap. A corrective unknown state could revive an older purchase;
  a busy issuer could crowd another out. Latest point-in-time state is now
  resolved per ticker before eligibility checks. Historical snapshots remain
  immutable, and unknown/expired states never fall back to older positives.
* Cloud final review accepted duplicate JSON keys and incomplete or refused
  envelopes. It now requires one completed, unambiguous text result and strict
  JSON, preserving the shared attempt budget, valid HOLD and billing provenance.
  Optional malformed provider identifiers cannot break ledger insertion or erase
  a known charge; unverified identifiers remain null.
* The Admin cursor query accidentally correlated an unqualified order ticker
  to the outer cursor. Active symbols are now resolved through linked signals;
  missing active cursors remain visible. Secondary warnings cannot hide a
  reported service failure or missing lease.
* Close-order presentation distinguishes a terminal or uncertain exit request
  from an entry request. Rendering tests do not send Telegram messages.

The recovery, close-order, SEC and parser defects have synthetic reproductions.
They are not assertions that those paths occurred in Production. The erroneous
Admin cursor cohort was also observed in a bounded read-only snapshot.

Unchanged boundaries
--------------------

No schema or backup format changes are introduced. Trading strategy, thresholds,
target levels, sizing, slippage, fees, models, providers, budgets and live flags
are unchanged. No existing orders, trades, balances, historical decisions or
automations are rewritten. Shadow remains paired analysis, not independent
capital. The patch does not guarantee additional trades or improved returns.

Verification and release gates
------------------------------

The focused suites are ``test_team_*`` in ``service/server/tests`` and
``service/server/tests_pg``. Existing lifecycle, retry, recovery, encrypted
restore, routing and Admin authorization suites also cover the affected paths.
PostgreSQL tests create disposable ``test_*`` schemas only. Encryption tests use
real age binaries and synthetic contents.

Run the existing CI and Cloud Readiness workflows on the final PR version:
full backend and PostgreSQL suites, Linux retention and Unix-socket tests,
frontend build/rendering, Linux image imports, backup-health and private-relay
harnesses. Do not substitute Windows platform skips for Linux evidence or treat
a skipped deployment workflow as a deployment verification.

Before any separately approved release, recheck the exact PR/release SHA,
unchanged scope, encrypted backup, all-role images, schema compatibility and
current rollback target using the existing release mechanism. Verify accounting,
holds, leases and completed candles after release without manufacturing events.

Separate outcomes and remaining evidence
---------------------------------------

Operational health, code correctness, retained-accounting reconciliation and
natural trading E2E are separate outcomes. A pending order is not a position; a
healthy endpoint does not prove a linked signal-to-exit lifecycle. Where absent,
use ``WAITING_FOR_NATURAL_EVENT``. Missing older opening-ledger evidence must
remain explicit rather than being reconstructed or labelled reconciled.

SEC discovery completion does not prove parsing completeness. Missing XML,
size limits and inaccessible external providers remain explicit coverage gaps.
The SEC streaming transport has inactivity timeouts but no total request
deadline; bounded transport cancellation is a separate resilience proposal,
not a claim of a fixed or observed Production stall in this patch.

Prioritize improvement proposals by retained evidence and risk. Model confidence
is not calibrated probability, increased candidates are not demonstrated edge,
and no retrospective weights should be optimized and judged on the same sample.
