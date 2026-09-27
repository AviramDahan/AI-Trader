# Approved feed activation — 2026-09-27

User confirms usage approvals for PR Newswire, Benzinga and Investing.com.
This change does not purchase access or change the canonical architecture.

## Technical findings from production host

- PR Newswire `https://www.prnewswire.com/rss/news-releases-list.rss`:
  DNS/TLS/HTTP 200, 20 RSS items, 20 valid explicit-offset publication dates,
  20 excerpts. Existing RSS adapter used; Dublin Core publisher is preserved
  when supplied, otherwise the configured publisher remains the fallback.
- Benzinga: no credential in production environment. `/news/feed.xml` and the
  official Free Stock News RSS product link returned 404. `/latest?feed=rss&page=1`
  returned HTML, not RSS. No manufactured endpoint, subscription or paid trial.
  News API credential can be requested at https://www.benzinga.com/apis/data/
  (Get API Key / Stock Market News API). Free continuing access is not confirmed.
- Investing: official all-news and stock-market RSS feeds both have naive
  `pubDate`, no alternate per-item timezone metadata. Official article HTTP 403;
  no bypass. RSS documentation does not establish a timezone contract.
  Remains disabled: `timestamp timezone unresolved`.

## Production control

Server-only `NEWS_EVENTS_PROVIDERS` enables approved adapters.
`NEWS_EVENTS_PROVIDER_APPROVALS` retains the user's approval reference.
Only PR Newswire is ready to enable. Preserve any existing provider configuration.
No migration needed (schema 5). Backup before rollout; normal exact-commit CI,
readiness and deployment gates apply. Disable only a failing new adapter by
removing it from the enabled list and recreating scanner; other providers and
the position monitor retain their state. Canonical integrity failure uses the
existing pipeline safety rollback. Provider state transitions use the private
Admin outbox and its Israel timestamp formatter, never public news topics.

Existing checkpoints and cutover fence must not be reset. Historical observations
are auditable but are not replayed publicly. The isolated tests cover publisher,
explicit/absent timezone, missing Benzinga credential, Yahoo/direct URL dedupe,
single analysis/delivery after restart and Admin transition dedupe. Existing
pagination, failure isolation and PostgreSQL outbox tests remain in the suite.
Real Telegram E2E requires a natural qualifying event, not fixtures in production.

The scheduled PR Newswire poll intermittently returned HTTP 301 while direct
probes returned 200. RSS transport permits at most one same-origin HTTPS hop,
with fresh public-IP validation, no credentials, no HTTP downgrade and no loop.
This is not an unrestricted redirect or proxy workaround. Cross-host redirects
remain blocked. Existing checkpoint must survive recovery from that failure.
