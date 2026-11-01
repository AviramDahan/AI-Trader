News-only local inference load protection
=========================================

Observed failure
----------------
Read-only audit of 2026-11-01 23:09 through 2026-11-02 00:09 Israel time
found 39 AI-Trader usage attempts: 31 news analyses, six repair attempts and
two translations. Native Ollama logged 33 generations, with 20 HTTP failures.
Eight schema failures were ``maximum`` violations, not proven malformed JSON.
Only five attempts produced validated application results. Metadata-only health
requests were not counted as generations. No prompts or responses were retained.

Change
------
Local news prompts now describe numeric schema bounds, including nested batched
fields. An existing schema-repair attempt receives the violated bound category
and the same trusted bounds. The original source payload, strict schema,
output/context budgets, quality checks and attempt allowance are unchanged.
Invalid scores are never divided by 100, clamped, accepted or published.
The audit does not retain offending values, so a percentage/scale confusion is
a hypothesis addressed by guidance, not an established cause of every violation.

When paid fallback is disabled, consecutive local-news transport failures or
exhausted schema repairs defer news admission for 120, 240, 480, then at most
900 seconds. A validated news completion resets this streak. Health responses
do not reset it. Context-capacity rejection does not poison smaller stories.
The gate runs before either legacy or canonical queue handling, so waiting does
not claim an item, increment attempts, delete an article or publish an alert.
Actual attempted failures retain their existing queue retry accounting and
retention limits. Sources continue collecting independently.

The state is process-local and resets on restart. It is not a distributed lock
or a durable queue. The existing single news analysis lock remains in place.
Other AI tasks, provider failover settings, shared gateway and Ollama settings,
trades, Telegram delivery and Dahan are unchanged. No schema migration or new
configuration flag is needed. Cloud-only and paid-fallback repair prompts retain
their previous behavior.

Validation and limits
---------------------
Offline tests cover numeric ranges, unchanged source facts, rejection of invalid
output, one bounded repair, transport failure without immediate regeneration,
progressive/capped waits, isolation from shared route admission, and a real
SQLite queue retaining a pending item and resuming after cooldown.
No model, paid API or production write was used. A skipped existing test requires
Unix-domain socket support unavailable on Windows.

This limits repeated wasted work; it does not make valid CPU inference free or
guarantee a zero backlog. The observed native warm timeout remains unchanged.
Prompt guidance has not been benchmarked against a live model. After deployment
approval, observe natural traffic and compare validated outcomes, native failures,
news age and cooldowns before considering any host/GPU changes. No historical
replay or synthetic production canary is required or performed here.

Prepared only: no merge, deployment, service restart or production configuration
change has been performed. Rollback after an approved rollout uses the existing
pinned-image release procedure; there is no data migration to reverse.

Local results: 260 targeted regressions passed, with the existing Linux private-
socket integration skipped on Windows. The final ten-test fix-specific suite
also passed, including one additional nullable-schema compatibility regression
added after the broader run (261 distinct local passing tests in total).
The full backend run was intentionally stopped while narrowing the patch; it
is not reported as a successful full-suite result. Mandatory Linux CI remains
required before merge/deployment.
