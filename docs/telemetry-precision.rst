On-demand AI health and research telemetry precision
====================================================

Scope
-----
This release changes diagnostics and presentation only. No Technical, target/RR,
news, AI/model, cadence, retry, sizing, execution, accounting or Position Monitor
policy changes. No schema, recovery format or live data migration is required.

* The historical ``ollama`` service key describes on-demand AI attempts, not a
  continuously running Ollama process. Absence of a request is not stale-worker
  failure. Explicit error status still alerts; periodic scanner/monitor/backup
  freshness thresholds are unchanged. Calls retain their existing timeouts and
  failure reporting. No artificial paid call is used as a heartbeat.
* An old inactivity incident clears once through the existing incident protocol.
  The Admin message says that the alert was removed, not that a new AI call
  succeeded. Genuine success after an incident retains the recovery message.
* Candidate summaries use a retained detail only when it belongs to the same
  rejection. A resistance-buffer overlap is distinguished from price rounding.
  Missing detail falls back to a neutral invalid-level label. Existing historical
  records are not rewritten. V1 structural reasons have Hebrew labels as well.
* History diagnostics report completed-session coverage, bounded gap lists and
  sanitized refresh failure type/code. Current cached data is not labeled stale
  solely because a different symbol failed refresh. The existing download list,
  coverage gates, cache writes, fallback limit and per-symbol observation times
  are unchanged; no failed download is declared successful or retried differently.
  The scanner status page renders this information without new fetches.

Verification and release
------------------------
Regression tests first reproduce the stale on-demand alarm, ambiguous summary and
whole-cache stale label. Tests use isolated state/provider mocks; none deliver
messages, perform trades or call an AI. Full CI and Cloud readiness must pass on
the exact release commit before the existing pull deployment. The regular
encrypted predeploy backup and current-schema image rollback remain unchanged.
After deployment validate actual builds/health, natural incident transitions,
read-only account reconciliation and diagnostics from a natural scanner cycle.
No signal is created merely to prove natural trading E2E.
