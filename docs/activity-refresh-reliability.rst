Public activity refresh reliability
===================================

Scope: transport and display reads only. No scanner, trading, quote freshness,
research snapshot, provider, Telegram delivery, database or schema changes.

The decoded public dashboard and research projections were each about 1 MB;
the dashboard took 6.4 seconds on one diagnostic connection and 8.2 seconds on
another. Caddy already compresses the dashboard to about 171 KB over the wire;
no redundant backend compression is added. Slow response generation/mobile
connections can exhaust the former 12-second display timeout. These are
measurements, not proof of the exact failure on every handset.

Display reads have a 20-second total request/JSON deadline, one request in
flight, unchanged 30/60-second dashboard/research cadence, and immediate refresh
on return to the foreground. Background cancellation and unmount do not raise
a service error. Real timeouts, HTTP and JSON errors retain the last data and
show the existing failed/delayed status until a read succeeds. Retained or stale
research is never retimestamped or counted as new live activity. A manual
post-settings refresh queues one read after any in-flight request. These two
display reads no longer require AbortSignal.timeout/any, which are unavailable
in some older embedded browsers. Quote handling remains unchanged.

Validation: read-poller fixtures exercise slow reads, deadline, errors, late
results, recovery, visibility races and cleanup. Existing scanner
read-concurrency tests remain required. Live transport/UI validation is
separate from unit tests. No backend routes or deployment configuration change.
