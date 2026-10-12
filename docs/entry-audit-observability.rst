Entry audit and execution-rejection presentation
===============================================

This is an observability-only follow-up to PR60/61. It changes no target policy,
entry/fill/exit rule, creation flag, budget, provider, reservation or schema.
No migration or Production activation is needed for these reader/UI changes.

The old audit used a correlated LATERAL technical lookup for every target
observation, before discarding non-evaluated rows. On the live journal it hit
its existing 10-second statement timeout. The replacement selects relevant
pre-AI BUY checks before the 2,001-row cap and performs one bounded batch
technical lookup, preserving the earliest technical id for each scan/ticker.
Invalid observations are explicit NOT_VERIFIED, not passes. Truncation remains
explicit; 2,000 checks and 100 linked chains are the processed bounds.
Repeatable-read/READ ONLY, the 14-day CLI limit and timeout remain unchanged.
No new index or migration is introduced.

Execution rejection details are projected from the retained entry order, not
inferred from price movements. The public research reader includes the order's
signal_id and only an allowlisted reason code, never plan_json or arbitrary
exception text. The dashboard and stock-evidence view show the reason in
Hebrew/English, or explicitly state that the detail was not retained/recognized.
A different signal's order cannot supply the selected signal's explanation.
Pending signals are not labeled as failed entries or activated positions.

Checks include synthetic bounded-query/decoding tests, real PostgreSQL with
30,000 unrelated technical rows and 2,500 non-evaluated checks before the valid
record, earliest-source identity, malformed JSON, public-readback linkage and
allowlisting, and isolated React rendering. Existing entry/lifecycle and
frontend suites must also pass. Mock results are not live trading evidence.

Deployment, if subsequently authorized, uses the existing exact-SHA CI and
readiness gates and encrypted prebackup. Current PR60/61 capable code remains
a state-compatible binary return target; no database rewind or policy change
is needed. Until deployed, the existing scheduled checks must report an audit
failure honestly or use bounded read-only diagnostics; this branch is not
automatically installed by publishing a pull request.
