Signal admission repair: scope and evidence
=========================================

This is a retrieval-correctness patch, not a change to trading policy, a promise
of new positions, or a reactivation of legacy imported entries.

Confirmed defects
-----------------

* The canonical signal-news reader applied a global 1,000-event limit before
  company selection. A synthetic fresh, verified company story was lost when
  1,001 newer market events were present. Selection now uses exact membership
  in the structured ticker array before applying the per-company limit.
* A malformed string ``tickers`` field could pass Python substring membership.
  Both SQL selection and observation verification now require an array/list.
* An empty shortlist no longer opens an unnecessary database connection.

All existing status, factual evidence, primary subject, rights, conflict,
collection/publication time and freshness checks remain in place. The reader
still returns at most five distinct stories per ticker. Corrupt JSON is
isolated, PostgreSQL transactions remain read-only with an eight-second
statement timeout, and database writes, provider requests and AI analysis are
not part of this reader. No migration or configuration change is required.

Isolated acceptance proof
-------------------------

The scanner test seeds the crowded news snapshot, supplies synthetic completed
structure and quotes, and mocks external providers, AI, API projection and
Telegram. It runs the real ``run_scan``, target-plan construction,
``record_signal``, ``process_bar`` and accounting verification paths:

* Recovered evidence reaches the review and creates one pending order, not an
  immediate position.
* A later completed bar creates one position; a subsequent target bar closes
  the entire SINGLE position.
* Restart/reprocessing does not create another fill. A repeat scan respects
  the saved cooldown and does not create another order/review.
* HOLD, insufficient confidence, missing quote, closed session and invalid
  target geometry still create no order or position.

The same positive chain and candidate-scoped query are exercised by the
PostgreSQL readiness suite in disposable schemas. These are synthetic
acceptance tests, not evidence of a new natural Production trade.

Interpretation and release limits
--------------------------------

A bounded read-only current-snapshot check found 436 rows eligible for the old
status/time query, so the global cap was not clipping that snapshot. This
defect is reproducible but is not established as the cause of the historical
absence of entries. Mutable current canonical bodies cannot reconstruct the
original historical AI inputs or prove counterfactual fills.

Target/RR selection, the technical shortlist, confidence/sentiment gates,
position admission, execution rules, AI candidate limit, cost cap and exits
are unchanged. In particular, this patch does not admit editorially rejected
stories, increase the shortlist or bypass HOLD to force a trade. Those are
separate policy questions, not implicit parts of this repair.

Publish/review this branch only. Production deployment requires its own
explicit release authorization. CI and Cloud readiness run on pull requests;
the existing server pull-deployment and deployment workflow only select
successful push releases on main. No merge, deployment or live replay is
part of preparing this patch. Binary rollback requires no database restore
because the persisted contract/schema are unchanged.
