Target decision evidence (observability only)
============================================

This change does not enable or modify a strategy. No production deployment is
authorized by this PR. It does not change targets, RR, ranking/refill, the six
candidate cap, AI inputs/calls, sizing, entry/fill rules, exits, news or Telegram.

Recorded facts
--------------

The existing ``scanner_candidates`` journal gains ``stage=target_check`` rows
with ``status=observed``. They do not count as business rejections. The JSON
envelope is version 1, with review/scan/ticker/phase identity, build SHA, policy,
source ATR/zones/pivot confirmation timestamps and source date, decision time,
actual checked price and provider timestamp (Yahoo one-minute close), outcome,
unchanged rejection reason, accepted levels and diagnostic geometry. No news
body, prompt, model response, credentials or account allocation is recorded.

``pre_ai`` and ``post_ai`` are distinct observations. The latter is the second
quote used when creating a signal/order, NOT an entry fill. The fill engine and
its stored contracts are untouched. ``NOT_EVALUATED`` explicitly covers missing
quotes, cooldown and failures before a target check; it is not a target rejection.

For V2's existing ``invalid_rounded_levels`` rejection, additional conditions
distinguish a buffer already reaching the entry, rounding a positive target gap
to zero, non-positive/invalid stop, and rounding into resistance. Original errors
and decision order remain unchanged. Diagnostic arithmetic cannot accept/reject
a candidate. Accepted plan data remains the authoritative decision output.

Signal/order links are resolved read-only through the persisted scan ID and
ticker, then ``scanner_orders.signal_id``. Multiple links are returned, never an
arbitrary first match. A missing signal is not an error or an activated position.
Evidence never enters an AI prompt or the persisted trading plan.

Durability and bounds
---------------------

Observations are flushed by the existing final-review telemetry transaction:
before the first AI call after a successful precheck, and in the existing final
persist on rejection/completion. Its unique review-row upsert serializes same-
review writers; repeated persists/reconstructed callers do not append duplicates.
A savepoint rolls back only evidence on failure and logs a sanitized warning;
the existing trading/AI telemetry path continues. Failed capture may leave an
evidence gap and must not be treated as an absence of candidates.

There is no DB/network operation while constructing diagnostic geometry. Snapshot
payloads are bounded to 64 KiB; an oversized record retains an explicit gap and
source digest instead of silently pretending full replay is possible. At most
two phase records per selected candidate are produced, not universe-wide dumps.
This follows the existing candidate-journal retention; it does not create a
background collector, retention policy, or an all-history report in a worker.

No migration or backup-format change. Candidate research telemetry is intentionally
not added to Recovery-State trading backups. Old binaries ignore these rows in
their rejection dashboards and can read all existing trading state unchanged.
Their separate V2/Short/schema compatibility requirements still apply: this PR
does not make an old, incompatible trading binary a safe rollback target.

Research use
------------

``scripts/target_evidence_report.py --since <UTC-ISO-timestamp> --limit 1000``
reads a bounded consistent read-only snapshot, reports clipping and links the
evidence to signals/orders. Use the existing protected diagnostic execution
path; no initialization, migration, external feed fetch, AI or Telegram call.
The script is not a scheduler. Do not sum repeated scan observations as independent
setups/trades, and do not call missing historical evidence a measured zero.

Evidence is forward-only. No historical quote reconstruction, data rewrite,
counterfactual fills, or profitability claim. New durable source snapshots make
the checked geometry reproducible; they do not establish whether a rejected
candidate would have become a profitable trade.

Release review
--------------

Require full CI and Cloud Readiness on the final PR SHA (backend, real PostgreSQL,
frontend build and Linux image). Targeted tests compare exact accepted plans and
error strings to the unchanged policy, test price changes between checks, failed
capture/persistence, duplicate flushes/restart, and unchanged six-candidate/AI/
publication behavior. No production run, merge or deployment in this task.
