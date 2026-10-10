Public activity refresh reliability
===================================

Scope: transport and display reads only. No scanner, trading, quote freshness,
research snapshot, provider, Telegram delivery, database or schema changes.

The measured public dashboard and research projections were each about 1 MB;
the dashboard took 6.4 seconds on one diagnostic connection. This can exhaust
the former 12-second display timeout on slower mobile connections. These are
measurements, not proof of the exact failure on every handset.

Large GET dashboard/research responses now negotiate gzip (minimum 1 KB,
compression level 5). Private endpoints, writes, health, images and quotes are
unchanged. JSON content, status codes and source timestamps are preserved.

Display reads have a 20-second total request/JSON deadline, one request in
flight, unchanged 30/60-second dashboard/research cadence, and immediate refresh
on return to the foreground. Background cancellation and unmount do not raise
a service error. Real timeouts, HTTP and JSON errors retain the last data and
show the existing failed/delayed status until a read succeeds. Retained or stale
research is never retimestamped or counted as new live activity. A manual
post-settings refresh queues one read after any in-flight request.

Validation: read-poller fixtures exercise slow reads, deadline, errors, late
results, recovery, visibility races and cleanup; backend ASGI tests check gzip,
identity/q=0 negotiation, payload/timestamp equality, CORS, errors and exclusion
of private/write/health/quote routes. Existing scanner read-concurrency tests
remain required. Live transport/UI validation is separate from unit tests.
