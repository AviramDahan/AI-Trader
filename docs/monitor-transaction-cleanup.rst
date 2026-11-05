Monitor write transaction cleanup
================================

Confirmed code defect
---------------------

``scanner_engine.process_bar`` closed its connection on success and its two
early-return paths, but not when transaction acquisition, SQL, validation or
commit raised. A retained connection/traceback could consequently retain an
uncommitted transaction and transaction-scoped advisory write lock. Cleanup
must not depend on garbage collection. A synthetic failing regression proves
the prior function did not call close with a retained failed connection.

The narrow correction puts existing processing in ``try/finally`` and closes
exactly once for success, rollback returns and exceptions. Commit points, OHLC
and freshness checks, entry emergency fencing, accounting serialization lock,
orders, TP/SL and cursor atomicity are unchanged. An uncommitted PostgreSQL
transaction is discarded on connection close. No lock is forcibly released,
no retry is added and no timeout or health gate is relaxed.

Evidence limits
---------------

Historical retained service status showed ``LockNotAvailable``; it did not
identify the original holder. This cleanup defect is NOT proof of that incident's
root holder or of every later Monitor failure. A more recent observation showed
``stale_or_missing_bars`` rather than lock timeout. Those are separate findings.
Do not merge/deploy this as a claim that the missing/stale bar source is fixed.

Validation
----------

Isolated Mock tests check failure propagation, immediate close with a retained
reference, and replay rollback/close once. A disposable PostgreSQL regression
injects a failure after acquiring the ordinary transaction-scoped write lock
and writing a synthetic marker. It checks connection closed, marker rolled back,
and the lock available to a separate test connection. No provider, AI or Telegram
call is performed. Production diagnosis stays read only and does not acquire
locks. Existing lifecycle and CI/Readiness regressions remain release gates.

This PR is preparation only. Independent review and actual PostgreSQL results
must be recorded separately; do not replace them with Mock success or force a
release through existing Monitor/deployment failure guards.
