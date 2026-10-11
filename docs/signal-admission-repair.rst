Signal admission repair: scope and evidence
=========================================

This patch corrects company-evidence selection and the separately authorized
target-failure refill. It does not relax trade eligibility, promise new
positions, or reactivate legacy imported entries.

Confirmed defects
-----------------

* The canonical signal-news reader applied a global 1,000-event limit before
  company selection. A synthetic fresh, verified company story was lost when
  1,001 newer market events were present. Selection now uses exact membership
  in the structured ticker array before applying the per-company limit.
* A malformed string ``tickers`` field could pass Python substring membership.
  Both SQL selection and observation verification now require an array/list.
* An empty shortlist no longer opens an unnecessary database connection.
* The original top-25 technical shortlist could exhaust its target checks
  without examining a structurally valid deeper candidate, even with unused
  AI slots. A synthetic rank-26 candidate was unreachable before the fix.

All existing status, factual evidence, primary subject, rights, conflict,
collection/publication time and freshness checks remain in place. The reader
still returns at most five distinct stories per ticker. Corrupt JSON is
isolated, PostgreSQL transactions remain read-only with an eight-second
statement timeout, and database writes, provider requests and AI analysis are
not part of this reader. No migration or configuration change is required.

Bounded target-failure refill
----------------------------

The original shortlist and its news ranking are processed first, unchanged.
Only a pre-AI target-plan rejection creates a replacement credit. News failure,
HOLD, low confidence, missing quote, cooldown and allocation rejection do not.
The deeper technical/SEC-ranked population remains subject to the same minimum
technical gates. In the refill phase fresh quote/cooldown/target validation
precede news enrichment. A valid target consumes one credit even if its news
or final review subsequently fails. Failed replacement targets retain, but
never multiply, the credit.

Extra work is limited to 64 deeper candidate checks and a 120-second monotonic
start-work budget per scan. No new quote/news operation starts after that
deadline or market closure. A bounded provider operation already in flight can
finish after the deadline; this is not a hard cancellation timer. Final AI
review/retry and localization keep their existing transport timeouts. The
budget includes time spent reviewing replacement candidates, so not every
structural candidate can be guaranteed examination in a particular cycle.
Extra news lookups cannot exceed original target-failure credits (at most the
configured initial shortlist size). Original plus refill reviews share the
same configured AI cap, currently six; the signal cap and monthly cost guard
remain unchanged.

An additive ticker cursor in the existing runtime state resumes the bounded
tail on the next scan. Initial top-ranked candidates still go first every
cycle. Changing membership invalidates a missing cursor safely; one tail pass
per cycle is the maximum. The cursor never persists a target approval or
bypasses the next scan's quote/news/target checks. Refill summaries include
checks, credits, target passes, news lookups, AI selections, elapsed time and
stop reason in runtime state and ``scanner_candidates`` at stage
``admission_selection``. The scan-wide record is anchored to an existing
technical ticker, not a new stock, and does not inflate inventory counts.

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
* Twenty-five invalid initial targets can lead to the synthetic rank-26
  candidate and the same real pending/entry/exit/accounting chain.
* A synthetic rank-195 candidate is reached over bounded cursor cycles;
  each scan revalidates it. No ticker-specific exception exists.
* AI cap sharing, deadline/check bounds, market closure, cooldown, news
  failure, timeout and post-AI price deterioration remain fail-closed.

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

Target/RR rules, the initial technical shortlist size, confidence/sentiment gates,
position admission, execution rules, AI candidate limit, cost cap and exits
remain strict. The intentional selection change is limited to replacing
target failures with bounded deeper checks, not raising the initial shortlist
or admitting editorially rejected stories or bypassing HOLD.

The existing October 5-9 retrospective covers 60 regular-session starts and
22,041 repeated technical observations across 501 tickers. Reconstructed
completed-minute references produced 12 structural passes inside the original
25 and 17 additional observations outside it: two tickers, four distinct
configurations. A cap of 50 recovered no extra passes. These are structural
opportunities, not 17 additional AI approvals or trades. The reconstruction
disagreed with 19 of 871 original comparable target outcomes and had missing
prices; full versioned news enrichment, historical final AI decisions, and
refill quote/request latency are unavailable. Therefore the bounded refill's
historical AI/trade yield is NOT VERIFIED. No historical AI decisions, fills,
or expected returns are manufactured. Pending orders are not positions.

Publish/review this branch only. Production deployment requires its own
explicit release authorization. CI and Cloud readiness run on pull requests;
the existing server pull-deployment and deployment workflow only select
successful push releases on main. No merge, deployment or live replay is
part of preparing this patch. Binary rollback requires no database restore
because the persisted contract/schema are unchanged.
