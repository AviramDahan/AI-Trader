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
