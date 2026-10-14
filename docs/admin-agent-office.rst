Private control room: systems and agent office
=============================================

Two separate views share the existing authenticated, GET-only Admin endpoint.
The systems view retains its thirteen components and all health/freshness rules.
The office view shows eight audit responsibilities, with large selectable desks
and a single details area. It is not a capital-allocation tool or worker control.

Cloud services are continuous workers. The Codex audit team runs bounded tasks,
not continuous autonomous agents. Completed means the reported audit ended,
not that all findings are resolved, all services are healthy or live E2E passed.
The packaged historical report references the public PR74 audit and preserves
its publication time. It is not updated to the current time on each UI refresh.

Coordinator report contract
---------------------------

The optional file ``/app/.runtime/agent-team-status.json`` is shared operational
metadata, separate from trading/SEC/recovery data. It contains version1, an opaque
run_id, UTC reported_at, an optional allowlisted repository PR URL and at most
eight unique role records: id, state, task code and UTC observed_at. No prompts,
names, credentials, private chat IDs or free-form documents are exposed.
Blocked reports may include an allowlisted blocker_code; missing reasons are
explicitly unknown, not invented. A stale blocker is labelled historical.

``python -m agent_team_status`` validates bounded JSON from stdin without writing.
An explicitly authorized coordinator can use ``--publish`` to atomically replace
that fixed report file. This command does not run jobs, inference or deployment,
and does not write the database or change trading settings. Updating a report is
not an authorization to start another audit. The UI has no publication action.
No report was published to Production as part of this feature implementation.

Active/queued/blocked observations older than180seconds are labelled stale. A
completed report remains historical. Invalid, duplicate, oversized or future
reports fail closed without reviving a previous positive report. Missing roles
remain unknown. If the optional file is absent, the dated, published PR74 audit
is shown; without valid provenance, no current activity is asserted.

Limitations and release
-----------------------

This adds the report display and explicit ingestion contract; it does not create
an automatic connection to Codex agent events or a new automation. A coordinator
must report actual task changes in an authorized audit workflow. No independent
live agent heartbeat is inferred from the API's own timestamp or cloud leases.

No migration, model, provider, budget, strategy, order, fill or recovery-format
change. Existing reader versions ignore the optional agent_team field. Binary
rollback leaves the operational report file untouched and does not stop cloud
monitoring. Deploy through the existing approved release mechanism only, after
separate approval; the PR itself is not deployment authorization.

Acceptance uses synthetic reports, controlled clocks, existing Admin permission
tests and read-only PostgreSQL projections; no real AI/Telegram/trading actions.
Test responsive layouts at320/360/390/430px and desktop, including keyboard tabs,
missing/stale/corrupt reports, authorization loss and no horizontal overflow.
