Canonical market-news topical consistency
=========================================

Scope
-----

This change addresses contradictory topical relevance in new canonical MARKET
news analyses. It is not a quota, a model replacement, a new provider, a lower
relevance threshold, or permission to publish every rejected story.

Only canonical analyses whose existing scope is MARKET use the derived
MARKET_REVIEW_SCHEMA. Company analyses keep the original REVIEW_SCHEMA.
ANALYSIS_SCHEMA and the stored/public analysis result stay unchanged.

The draft prompt defines related as relevance to market news, not a trading
recommendation, a price-impact prediction or a requirement for high materiality.
The independent editor classifies original evidence with a required boolean
scope_related. It must not infer this from numeric scores or copy the draft.
Attributed/conditional reports retain their uncertainty. Promotional, unrelated
and non-news material can still correctly receive false.

Disagreement and request bounds
-------------------------------

The deterministic scope_related_consistent check compares the editor judgment
with draft.related. Disagreement does not flip either value automatically.
It enters the existing editorial repair lane, then all original quality checks
and the independent review run again. The repair receives the editor boolean
as market-only review_scope_related feedback alongside the original evidence.

A normal job still makes two model requests. At most one shared repair allowance
exists across schema, local fallback and editorial repairs; this change adds no
new retry loop. An ordinary editorial repair still uses at most four requests.
If the allowance was consumed by schema/fallback recovery, unresolved semantic
disagreement fails closed. Missing or non-boolean scope_related fails schema
validation; no default judgment is invented.

Fidelity, Hebrew, grounded numbers/terminology, unsupported-claim and duplicate
checks remain mandatory. A semantic repair that fails any of these cannot
publish. The fixed scope_related_consistent diagnostic is allowlisted for the
existing private Admin formatter; no raw editor/source text is added to alerts.

Integration and compatibility
-----------------------------

Routing, relevance/materiality requirements, identity/rights/freshness checks,
membership, deduplication and send-time revalidation are unchanged. No scanner,
order, position, sizing, TP/SL or accounting policy changes are included.

No new flag, migration or backup-format change is required. The added field is
a transient canonical market review contract, not a new public result field.
Existing saved analyses are not reinterpreted, requeued or replayed. Historical
terminal outcomes remain terminal; this patch cannot restore missed old news.

The approved schema-7 application and recovery formats are unchanged. This is
not a general rollback guarantee for unrelated contracts. Any separately
approved release must use the existing deployment, backup and rollback gates.

Verification
------------

Author and independent regressions first reproduce the contradictory accepted
draft and missing-review-field failures on the unmodified base, then check the
candidate. Synthetic cases include both mismatch directions, valid promotional
false, valid low-materiality true, conditional attribution, malformed reviews,
shared repair exhaustion and preserved company contracts.

The isolated PostgreSQL test exercises the actual canonical analyzer with
mocked completions, durable analysis/outbox creation, restart and deduplication.
It never dispatches Telegram and asserts no trades or fills are created.
CI and Cloud readiness run the existing full backend/PostgreSQL suites,
frontend tests/build and Linux container checks on the final PR commit.

These are code-contract tests, not live model-quality or increased-publication
proof. Draft and reviewer can still agree on a wrong semantic judgment; prompts
and agreement checks do not independently verify source truth. No real model
generation, provider fetch, Telegram test or historical replay is authorized
for these tests.

Release and observation
-----------------------

This PR does not authorize merge or deployment. After a separate reviewed
release approval, observe only naturally processed new analyses. Distinguish
new analyses from retries, editorial quality rejects from transport failures,
and outbox candidates from actual unique Telegram deliveries. Compare market
related flags and preserved quality checks with the same source-time windows;
do not assume all previously rejected stories deserve publication.

Index/commodity headline coverage and SEC extraction-reason diagnostics are
separate findings and are not implemented by this focused change.
