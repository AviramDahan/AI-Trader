# Investing RSS — operational UTC rule

User-approved operational assumption, not an independently verified publisher
timezone contract. Applies only to `https://www.investing.com/rss/*`.
Naive timestamps become UTC ISO-8601 `Z`; explicit offsets are respected.
No New York, Israel or machine timezone fallback. Source provenance records
`timestamp_source=investing_rss`, `source_timezone=UTC` and
`timezone_resolution=provider_specific_operational_rule`, plus the original
timestamp and activation boundary. The shared canonical store also represents
UTC as `+00:00`; other providers' serialization is unchanged.

Before canonical ingestion, the adapter rejects >now+10min, older than the
existing feed maximum age, invalid timestamps, and pre-activation items.
Pre-activation observations are counted in the durable provider checkpoint,
not replayed or enqueued for AI/publication. The existing canonical future-date
check remains stricter and unchanged. Repeated anomalous polls (two) terminally
hold this provider; no retry loop. A healthy provider remains independent.

Enablement requires both provider approval/enable settings and the protected
`NEWS_INVESTING_ACTIVATED_AT` UTC boundary set at activation, never backdated.
Restart preserves checkpoint, rejection counts, and terminal failure state.
Remove only `investing` from `NEWS_EVENTS_PROVIDERS` and recreate scanner for
provider-level rollback. Do not alter the global canonical cutover fence or
clear other providers' state. Existing canonical integrity/monitor safeguards
remain unchanged. No changes to final stock analysis, models, budget or trading.

Read-only cloud preflight on 27 September 2026 18:34 UTC: HTTP 200, 10 items,
newest-first, age 18–165 minutes, zero future/stale items (168h existing maximum).
This is a sanity test of the operational rule, not proof of a publisher contract.
