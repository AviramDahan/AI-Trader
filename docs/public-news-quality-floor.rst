Public news quality and routing repair
=====================================

Scope
-----

``STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED`` defaults false. When
enabled, public General and broad-stock publication require a concrete
development in the exact original source headline/excerpt. Opinion/listicles,
earnings previews/transcript-only recaps and generic launch marketing are held.
Unknown importance stays unknown; no fabricated relevance/sentiment is stored.
This is deterministic editorial filtering, not verified investment importance.
It can miss differently worded material events and needs bounded sample review.

Scored General relevance has an effective floor .55 (previous default .30),
broad-stock .80 (previous default .70); higher configured floors remain higher.
Low-materiality General supplementation is disabled under the strict flag.
Unscored public translations retain NULL scores and pass the source-fact gate
instead of pretending to meet a numeric score. Source fidelity, Hebrew checks,
rights, freshness, dedupe, version and epoch fences remain authoritative.

Queue and send both recheck policy, including retained pending legacy rows.
Rejected pending rows are cancelled, never replayed on restart or after disabling
the flag. Sent history and durable publication keys are not rewritten. Personal
position/watchlist, SEC, Trump, trading, report/weekly specialist notices remain
under their existing policies. Broad company-results notices still need source
importance, then use Reports. No extra model/provider calls are added.

Direction repair
----------------

Legacy ``news_pipeline._event_version`` is SHA256 truncated to 20 hex; evidence-
enriched analysis uses 64 hex. The former direction reader accepted only64/v1,
so valid source-version stock notices fell through to General. Both explicit
domains now work with the original exact authoritative-version check: audit
content_version when present, otherwise scanner row content_hash (or explicit
v1). Arbitrary lengths, stale audit mismatches and unknown analyses cannot gain
a direction. Analyst routing and exact peer convergence use the same domains.
No rehash, new identifier, backfill or replay is required.

Verification and rollout
------------------------

``TELEGRAM_COMPANY_REPORTS_RESULTS_ONLY_ENABLED`` defaults false. Under the
human-approved results-only definition, generic news can enter Reports only
when the exact original source AND the visible bulletin contain actual financial
values and a stated report period. Expected values alone, publication dates,
share-price reactions and qualitative "beat/miss" headlines do not qualify.
Existing typed company-report producers keep Reports, including their honest
missing-consensus labels. The weekly calendar stays pinned there. Actual
earnings facts can remain eligible stock news without being a results bulletin;
topic selection does not suppress the internal trading/news analysis.

Strict retained dispatch supplies an explicit source-bound report decision so
old presentation prefixes or model summaries cannot override that decision.
Canonical presentation and destination-bound keys apply the same rule even
when the directional and analyst flags are disabled. Changed prepared keys
cancel without rewrite/replay. No new model call or fabricated number is added.

Tests use synthetic source facts and isolated databases with mocked transports,
including the real legacy version generator, queue/send, restart, invalid/stale
versions, personal preservation and translation NULL fields. These do not prove
natural Telegram delivery after release. The private dated production cohort
is observational evidence only, not a precision/recall benchmark.

Create/verify the dedicated analyst topic before enabling its separate flag.
Deploy through the existing reviewed release procedure; enable the strict news
flag only with approved news configuration. Check actual flags in sender roles,
new-event destination receipts and bounded rejection samples. Do not replay
pre-release notices or manufacture news. A disabled analyst destination blocks
delivery rather than spilling to Market. Keep Codex automations paused.
