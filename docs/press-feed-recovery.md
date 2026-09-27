# PR Newswire / GlobeNewswire recovery

Only these adapters use the identifying `AI-Trader/1.0` User-Agent. Investing and
all other transports retain their existing behavior. No proxy or HTML scraping.

Cloud probes on 2026-09-27 found both official feeds returning 20 RSS items,
explicit publication offsets, HTTP 200 and XML. GlobeNewswire timed out reading
response headers with the old sandbox User-Agent (including a 20-second probe),
but returned RSS in 0.17 seconds with the standard identifying User-Agent through
the same pinned-IP transport. IPv4 and IPv6 HEAD also returned 200.

PR Newswire's recorded 404 was followed by successful reads from the unchanged
official URL. The historical response body/redirect destination was not retained;
the remote cause of that response is **not established**. One 404 previously
caused permanent suspension. A previously successful press feed now gets at most
two delayed recovery probes (minimum 300 seconds, respecting Retry-After); a
third consecutive 404 is terminal. Unverified 404 endpoints remain terminal.

Required server settings:

- `NEWS_PRNEWSWIRE_ACTIVATED_AT`
- `NEWS_GLOBENEWSWIRE_ACTIVATED_AT`
- Existing `NEWS_EVENTS_PROVIDERS` and `NEWS_EVENTS_PROVIDER_APPROVALS`

Activation must be the actual UTC enable time, never backdated. Items preceding
it are counted as replay-blocked and never submitted to AI or public Telegram.
Keep the boundary on restart. Existing canonical identities and checkpoints are
retained. This requires no database migration.

Provider rollback: remove only the affected provider from
`NEWS_EVENTS_PROVIDERS`, recreate the scanner with the existing Compose mechanism,
and verify its disabled status. Do not restore old databases or restart local
workers. Other providers, monitor and accounting remain unchanged.
