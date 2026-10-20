Price-route news context (opt-in Paper policy)
===========================================

Scope and rollout
-----------------

``STOCK_SCANNER_PRICE_NEWS_CONTEXT_ENABLED=false`` by default. This change is
implementation and isolated validation, NOT authority to merge, deploy, enable
the flag, make model calls or create experimental Production transactions.
Ordinary deployment, encrypted-backup/compatible-Bridge verification and a
separate release/activation decision are required before running the policy.

When enabled, only enabled BUY detections from VCP/Base Contraction, Stockbee
Momentum Burst, Trend Pullback Reclaim and Relative Strength Leader qualify.
Baseline-only, PEAD and SHORT retain the existing mandatory-evidence gate.
The existing scanner, AI, ranking quotas, RR, entry plans, risk, exposure,
pending-order execution, emergency entry pause and TP/SL remain authoritative.
This is not a guarantee of more entries or profitability.

Evidence and AI
---------------

* Successful Yahoo/cache and existing canonical-evidence lookups with no eligible
  story permit ``NO_ELIGIBLE_STORIES``. It means no eligible story was found,
  NOT that no event exists, that news is positive or that every source is covered.
* A failed source with no eligible alternative evidence fails closed. A canonical
  query failure cannot masquerade as an empty successful lookup. Current eligible
  company/SEC evidence can still substitute for one unavailable source as before.
* Stale/future articles never become current evidence. A future-dated cache fetch
  cannot establish a successful empty lookup; the price route requests a fresh one.
* Relevant positive news is optional for a qualifying price route, including the
  prompt and the final relevance veto. HOLD/confidence and negative sentiment
  vetoes remain. Current verified SEC material conflicts retain their veto.
* The existing numeric AI wire schema is unchanged. With no articles the model
  must return zero news scores as explicitly labelled **NOT_MEASURED wire
  placeholders**, not neutral/irrelevant observations. Invented scores fail closed.
  Stored decision evidence and displayed score basis use nulls, not measured zeros.
* Ranking keeps the existing weights/quotas. Absent news contributes no positive
  news-score component; it does not earn a ranking or AI-capacity bonus.

Mixed detections and existing contracts
--------------------------------------

Every optional-news admission needs a fresh, still-valid enabled independent
trigger at both pre-AI and post-AI prices. A Baseline overlap cannot substitute.
At new signal admission the full source package is retained as
``technical_json.observed_entry_discovery`` and in the original discovery journal.
``news_context.observed_strategy_ids`` identifies all original routes, while
``entry_discovery`` on the signal/order contains only eligible price routes.
Those routes use the **unchanged** ``independent_entry_execution_v1`` contracts.
Thus a later fill below a price-route pivot cannot fall back to the Baseline.
Pullback fills retain their existing frozen reclaim/EMA execution policy.

Execution/performance attribution counts admitted price routes; the original
discovery journal remains the source for overlapping detections. Baseline-only
admissions remain the comparison cohort, not mixed optional-news executions.
No old order, trade, immutable level, contract or snapshot version is rewritten.
The existing minimal active-state recovery sanitizer deliberately omits the
new optional ``observed_entry_discovery``/``news_context`` history, just as it
omits candidate journals, articles and model explanations. It DOES retain the
executable price-only ``entry_discovery`` and v1 execution contract unchanged.
After a minimal restore, original overlapping detections and this news-policy
receipt are UNKNOWN unless separately retained in the original decision history;
do not reconstruct them, compare news-policy cohorts or claim full audit recovery.
Already-saved entries continue under their original rules when this flag or all
discovery flags are OFF. This flag is **not** an emergency kill switch: use the
existing durable emergency entry pause to stop new AND pending entries while
allowing position monitoring and exits.

Verification and release limits
-------------------------------

Run ``test_price_news_context.py`` plus the scanner, signal-input, refill,
independent-execution, emergency, snapshot/recovery and PostgreSQL suites, frontend
build and read-only activity/research rendering tests. All providers are mocked;
tests include actual scanner-to-order-to-fill-to-exit code, both TP and SL,
mixed-Baseline gap rejection, restart/bridge-role management and pause/resume.

Local bridge-role tests are NOT an actual Linux image/rollback or server test.
Before activation require existing CI/Readiness and image/recovery checks on the
final SHA, and verify the compatible image and latest encrypted backup on target.
No new recovery fields or capability claim is introduced. Existing compatible
readers receive only the established format8/9 execution fields, not this optional
decision-history metadata. As before, active-state backup covers open positions and uncertain
recovery holds, NOT every ordinary pending order or all closed-trade history.
No live/counterfactual AI decisions, historical fills or trading returns are
created by these fixtures. Measure actual results by admitted strategy and news
policy separately; do not combine overlapping memberships into extra trades.
