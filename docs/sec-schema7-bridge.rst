SEC schema-7 compatibility bridge
=================================

This release is a prerequisite for SEC decision intelligence. It does not
collect filings, change candidate selection, or publish SEC alerts. Its normal
migration target stays 6, so the existing guarded deployment can install it
over schema 6. It can also start on a *complete* schema 7 after migration 007.
Readiness rejects missing migration history, missing SEC tables or required
columns. The normal deployment script must continue to reject a schema-version
change; an explicitly approved transition is required for 006 -> 007.

If the SEC activation binary fails after migration 007, stop all writers and
return to this bridge image against the **current** database. Never return to
an older schema-6-only binary and never rewind the database. The bridge does
not produce SEC decisions. Any SEC alert it encounters in the durable outbox
is cancelled rather than falling through to the public General topic. This
means a cancelled alert is not automatically replayed after recovery.

Record the actual deployed bridge image ID and build SHA before transition;
keep the image available to the release mechanism. Verify encrypted backup,
accounting, recovery holds, single-role leases and readiness before and after
each step. A schema-7 migration and SEC activation are **not** authorized by
this bridge release itself.

Isolated release evidence
------------------------

``SEC schema compatibility images (no deployment)`` runs on the activation
PR and builds this exact bridge, the exact activation HEAD and the prior
schema-6 application. It requires this bridge to be an ancestor of activation.
The bridge PR's skipped image job is not evidence; the executed activation
run and its ``images.json`` identify both tested code SHAs and image IDs.

The internal-only PostgreSQL test covers the actual migration role CLI,
failure immediately after 007, compatible rollback/restart, retained V1/V2,
Legacy and Shadow positions plus an expired recovery hold, real age recovery
to an empty isolated database, continued exits and duplicate protection.
Both binaries reject a schema-7 database missing a required index. A separate
test invokes the actual Bash transition script with command doubles and
proves failure/rollback/resume without repeating DDL. Only filtered phase
results and image metadata are uploaded; temporary identities and snapshots
are not artifacts. No production worker or external provider is involved.

SEC companion archive
---------------------

On a complete schema 7, the existing encrypted backup also exports the six
SEC tables into a separate version-1 companion archive. This bridge can read
and restore that archive into empty SEC tables with all worker leases free.
It does not run SEC history cleanup. ACTIVE-state recovery formats and the
portfolio restore boundary are unchanged. Archives are chunked, ciphertext-
only, and deduplicated in the existing private backup repository; index files
contain only paths/checksums, never source facts. No full database/credentials
or unrelated news history are uploaded.
