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

Root-cause follow-up, 2 November 2026 (NOT deployed)
--------------------------------------------------

This supersedes any reading of the initial containment as a proven root fix.
The exact running gateway is on-demand-gateway-5a68918.py. It selects45 seconds
for resident weights even on protocol2; residency is not an inference-speed
measurement. The deadline is NOT increased in this patch. Context8192 and all
output budgets, source/quality checks and publication thresholds are unchanged.

Measured retained evidence: the native daemon0.40.13 discovered CPU only, with
zero detected VRAM. Logs show CPU_REPACK weights and roughly6-7 generated tokens
per second. Sample failed tasks reach the45-second HTTP500, then native cancel,
slot release and idle. This supports deadline cancellation for these tasks, not
a general guarantee for every disconnect. Prefill also takes around23 seconds
for roughly886 uncached tokens; both prefill and generation consume the budget.
DLL presence alone is insufficient: model-free llama-server --list-devices
reported no devices by default, including with CUDA folders only on child PATH.
The same installed runner with child GGML_BACKEND_PATH pointing to cuda_v12 or
cuda_v13 ggml-cuda.dll detected RTX3080Ti, with about11100MiB free. No model was
loaded by those probes. This localizes a backend-discovery/loading defect; it
does not prove the exact daemon discovery implementation or GPU generation.

scripts/ollama_gpu_environment.py prepares a scoped environment for the EXISTING
shared daemon owner's reviewed next startup. It enumerates devices without a
model, preserves parallelism/cache/device restrictions, refuses conflicts and
fails rather than silently claiming CUDA success. It does NOT start/restart the
daemon or alter Windows/user environment. It is NOT installed into Dahan's live
guard. A coordinated idle startup and one bounded native canary are still needed;
changing a gateway deadline cannot repair CPU-only backend discovery.

Historical maximum events stored only the validator, not values, contract digest
or field paths. Neither news nor canonical call links exist for the39-attempt
window. The installed build wasc3fb262 with evidence enrichment disabled. Its
news-analysis relevance field is number[0,1], a candidate, NOT retrospective proof
that each failure was this field or a0-100 scale error. Original responses cannot
be recovered from absent records. No value is divided, clamped or accepted.
Future provider validation records the full supplied schema digest plus a static
allowlisted field name, without the output/value. Repair guidance can name this
trusted field. A number schema's successful transport/JSON parse is not proof of
numeric-bound compliance; application validation remains authoritative.

Code-level repeat-work defect reproduced before correction: a valid source
analysis was regenerated after a later-stage transport failure. Final-result
cache alone cannot preserve partially completed review chains. Cloud analyze_one
now owns article context even when enrichment is disabled. Each completed local-
only schema-validated stage is saved in existing news_review_cache, keyed by exact
source revision, stage, entire prompt/payload/schema/output budget and pinned
model/configuration/policy. New peers, facts, prompt, model or schema get another
key. Failed/invalid results are never saved or normalized; saved results validate
again on read. Review/grounding/Hebrew/publication checks still run. This reuses
completed exact steps after process restart, not a stale final publication or
an approval bypass. Existing article serialization remains authoritative.
The underlying39 historical attempts cannot be assigned to repeated articles;
this is an executable code regression, not an invented historical attribution.

Live inference performed by this investigation: ZERO. A future SINGLE canary,
after safe idle startup by the shared daemon owner, should use a synthetic
source-only news request with the unchanged actual schema, context and output
budget; record physical GPU residency, prompt/eval durations, strict schema and
Hebrew/source checks and cancellation outcome. It cannot prove historic maximum
values, long-run quality or production throughput. Do not run a replay/batch,
modify Dahan control or terminate another user's active request for this test.

Release remains BLOCKED: root causes of historical bound errors and daemon GPU
startup, actual GPU generation, PG checkpoint integration and final-head CI are
not all proven. The new environment helper is a prepared startup correction,
NOT a deployed shared-runtime fix or a justification for merging this Draft.
