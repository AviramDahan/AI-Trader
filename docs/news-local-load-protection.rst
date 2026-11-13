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
900 seconds. The streak resets only after an entire news item passes its
existing checks and at least one live local stage has validated since the last
failure. A successful intermediate stage, cache-only completion or health
response alone does not reset it. Context-capacity rejection does not poison smaller stories.
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

Follow-up discovery control: a fresh isolated Ollama 0.40.13 daemon, started
with an empty disposable model directory and no inference requests, discovered
CUDA both with its default environment and with an explicit CUDA backend path.
An independently launched llama-server not finding CUDA by default therefore
does NOT prove that setting GGML_BACKEND_PATH fixes daemon startup. The old
long-running shared daemon had detected only CPU on its 1 November startup;
the condition that caused that historical failure remains unknown. No backend
override is included or installed. A coordinated idle restart and one bounded
native canary remain necessary; changing a gateway deadline cannot repair
CPU-only backend discovery.

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

Active canonical path follow-up
-------------------------------
The earlier checkpoint implementation covered the legacy analyzer only. The
deployed scanner has the canonical runtime environment enabled, but a read-only
check on 3 November found the effective database mode is ``phase1``; it is not
currently publishing through the canonical path. A synthetic regression
reproduced the same repeated source call on the optional canonical path. Canonical
completion now uses the same schema-validated checkpoint, bound to the event
and evidence version as well as the full prompt, payload, schema and model.
A cache hit is not counted as a second provider invocation or charged as one.
Changes to the source, review inputs, model or contract invalidate the checkpoint.
The news quality and publication checks still execute for resumed work. The
regression is synthetic; it does not establish how many historical requests
repeated the same stage. A real model and the resulting sustained host load are
still unverified; this change alone does not make CPU inference meet the deadline.

Live isolated GPU control, 3 November: a single synthetic source-stage request
used the unchanged canonical schema, 8192 context and 1000 output budget. A new,
separate Ollama daemon loaded a hash-verified independent model copy and observed
GPU residency. The request completed in 34.19 seconds including cold start;
model evaluation was 1.57 seconds. The structured schema, Hebrew presence and
deterministic grounding checks passed. This does not test independent factual
review, historic maximum values, production throughput or the shared daemon.
The effective deployed publisher uses phase1, so that canonical-schema control
does not validate the exact live publisher prompt or its output schema.
The isolated process was stopped after the test; no shared daemon was restarted.

Release remains unverified: the historical bound values and the condition that
caused the shared daemon to miss GPU discovery are unknown. The checkpoint and
cooldown changes passed offline and PostgreSQL CI, but their impact on natural
production traffic is not measured. A coordinated transition must protect both
projects' active requests and be followed by real post-release observation.

Strict-news output contract mismatch, 4 November
------------------------------------------------

The effective phase1 company-news producer calls ``analyze_strict`` with its
existing output budget of2400. The exact installed gateway source, equal to the
repository gateway after newline normalization, rejects ``predict>2048`` before
any metadata or model call. An offline producer-to-gateway regression reproduced
``invalid_predict`` using the real producer's requested budget. This proves an
independent fast-failure path; it does not assign historical HTTP503 attempts to
that path or explain ``maximum`` output validation failures.

Protocol2 now supports that existing2400 ceiling. Protocol1 keeps its2048 bound;
smaller requests keep their exact requested limits. Health advertises the new
optional capability without changing protocol negotiation. Context8192, pinned
model, no truncation/shift, single-slot concurrency, memory protections and45/120
second deadlines remain unchanged. There is no larger default output budget or
score normalization. Boundary and on-demand lifecycle tests use a mocked native
runtime, not an actual2400-token generation. The running shared gateway must be
updated separately through a coordinated idle transition before this correction
can be claimed active; a cloud application deployment alone does not update it.
