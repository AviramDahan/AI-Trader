Entry price facts and constrained explanation repair
===================================================

Confirmed finding
-----------------
Natural final reviews for MSFT and V claimed quote above planned entry although
the retained quote and accepted-plan entry were equal. Existing validators checked
shape/action/direction/scores, not this factual comparison. This does not establish
that HOLD should have been BUY or that more trades would be profitable.

Focused correction
------------------
``entry_price_contract_v1`` compares the current review quote with the validated
plan entry using exact decimal representations, not the completed-day close.
Both prices, quote time, relationship and provenance are frozen in the existing
bounded pre-call context. Missing, inconsistent, future or stale inputs remain
UNKNOWN. This is not a new price/entry/risk threshold.

The AI-only candidate projection removes duplicate flat entry/reference/plan
fields. The completed-day reference remains under completed_daily; quote facts
remain under entry_price_facts; the original validated plan is supplied separately.
Original candidates, signal/order contracts and existing positions are untouched.

Final review requires structured ``entry_price_relation`` and
``entry_price_concern`` fields. They must agree with the deterministic facts.
A narrow supplementary check recognizes the observed explicit English claim
that the quote/current price is above/below planned entry. Negated/conditional
claims, target price, missing relative volume and unrelated HOLD grounds are
not treated as that assertion. This is NOT a general prose fact checker and
does not guarantee all unsupported model claims will be detected.

Repair and safety
-----------------
A contradiction uses the EXISTING total two-attempt budget in final_ai, shared
with timeout/HTTP/schema repair. There is never a third attempt. The repair locks
action, confidence, sentiment, relevance and horizon from the original valid
decision. It may correct only the factual assessment/explanation. A complete
original HOLD cannot become BUY, including when only the new structured fields
were missing. Changed locked fields or an exhausted repair fail closed.
Malformed JSON/core fields cannot provide a decision to preserve; none is invented.
Direction conflicts remain non-repairable. Valid HOLD needs no repair.

Nothing in the comparison authorizes an action. Every existing technical, news,
direction, confidence, quote/session, budget, target/RR, risk/duplicate/admission
and subsequent full-bar execution gate remains in force. Model, token cap450,
six-review limit, strategy, sizing, stop/target/exit and monitor IO are unchanged.
Natural contradictory responses can cause an extra call within the pre-existing
two-call bound, charged through existing budget/usage controls. No paid test calls
or forced scanner/provider/Telegram work are needed to test this correction.

Trace and compatibility
-----------------------
Known mismatch type and expected relationship are stored in attempts_json.
Successful validated/repaired/unverifiable assessment is stored additively in
the existing ai_decision observation. No prompt/raw response retention, new
schema/migration/configuration or recovery-format change. Historical decisions
are not rewritten or replayed. Old journal readers ignore optional metadata;
existing pending orders and position contracts are unchanged. Compatible binary
rollback uses the preceding deployed image on the current database, never a
database rewind. The recovery exporter intentionally does not archive research
journals; no new backup contract is implied.

Verification
------------
The missing authoritative-contract and constrained-repair regressions fail on
the previous release. Mocked-provider tests cover equal/above/below/unknown,
known contradiction, legitimate/conditional HOLD, unchanged action/scores/horizon,
missing fields, shared retry exhaustion and cloud schema/cost bookkeeping.
Actual scanner/admission tests on disposable SQLite/PostgreSQL prove corrected
HOLD and attempted HOLD-to-BUY repair create no order/fill, and existing valid
BUY follows the full pending/entry/exit/accounting/restart chain without duplicates.
These tests do not demonstrate live model output, new natural entries or profit.
