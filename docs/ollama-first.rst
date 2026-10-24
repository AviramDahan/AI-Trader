Ollama-first inference (not local trading)
=========================================

Default ``AI_INFERENCE_MODE=cloud_only`` preserves the existing selection,
cloud writers, schemas, model, cap, pace, reviews and lifecycle. No migration.
``ollama_first`` selects approved ``gemma4:12b`` digest
``6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b``
for all active cloud AI transports: final review, canonical draft/editor,
position news, translation, market summary, optional community wording.
It does not enable community replies or any otherwise disabled feature.

The 10 small local compatibility fixtures are NOT confidence calibration,
live news quality evidence, profitability evidence or proof of cloud access.
The existing independent quality review, numeric grounding, deterministic
entry rationale repair, quote recheck and trading gates remain mandatory.
Valid HOLD/low confidence/quality rejection never causes provider shopping.

Attempt and spend policy
------------------------

Each caller retains its existing attempt allowance. A local generation consumes
one attempt. A transport/schema error can switch a remaining retry to Luna;
it cannot add a hidden third attempt. Canonical stages have one request each;
their existing shared repair/job policy owns subsequent attempts. A local
preflight failure consumes no generation, so that stage goes directly to Luna.
Canonical transport fallback consumes its ONE shared repair allowance, just
like schema repair; it is not another retry budget on every stage.
Technical failures cool down local selection for 60 seconds per process.
No concurrent hedge: a late local result is discarded and cannot create orders.
The local gateway holds one GPU slot until the upstream request has ended.

Every paid attempt still runs the existing budget/cooldown/credit checks and
shared OpenRouter pacing. The $25 cap and Auto Top-Up OFF are unchanged.
Local readiness bypasses only a *spend* precheck, never financial risk controls.
Once a local decision has completed and passed validation, losing PC readiness
must not re-block that decision on a paid-spend-only publication check. Optional
Hebrew wording uses the existing deterministic fallback if paid budget is
blocked; it never fabricates wording with an unpaid extra model request. Paid
and legacy decisions retain their existing publication budget checks.
If local processing and paid budget are unavailable, fail closed/defer under
the existing queue policy; price/TP/SL monitoring does not depend on inference.
Local API spend is known zero (not electricity amortization). Usage ledger
model names begin ``ollama/`` and include the digest; paid names are unchanged.
Canonical calls and final attempts also store actual provider/digest/latency
and fallback reason. A local failed attempt is not an unknown cloud charge.

Failed local truncation diagnostics
-----------------------------------

An incomplete local response still fails closed. In particular, a native
``done_reason=length`` never becomes a successful analysis or an extra retry.
The shared repair allowance, provider selection/cooldown, output and context
limits, quality checks and trading rules are unchanged by this diagnostic fix.

When a response with the expected native model/digest and completed-response
identity supplies valid token counters, those counters survive the truncation
exception and reach the existing ``ai_call_usage`` input/output columns and
canonical call metrics. Only bounded, nonnegative integer counters are retained;
missing or invalid counts remain unknown, not zero and not the requested limit.
The fixed ``local_finish_reason=length`` diagnostic is retained in the existing
failure JSON and canonical usage metadata. No response text, partial JSON,
prompt, message, tool arguments or arbitrary provider metadata is added to the
exception metadata or persisted diagnostic fields.

Known zero local API spend remains separate from unknown token usage. There is
still exactly one ledger record per actual attempt, with the original local
provider identity. Paid usage, successful local responses and final-stock-review
behavior retain their existing contracts. This change requires no migration,
new flag, PC gateway update or historical-data rewrite. Existing readers can
ignore the additive JSON diagnostic field; the database remains schema 7.

Synthetic length/stop controls prove metadata retention and terminal behavior,
not why a historical model generation stopped. The repair does not recover
previously lost counters, replay failed versions, prove that a longer limit
would help or establish a reduction in natural generation failures. After a
separately approved release, inspect only naturally occurring failures and
distinguish configured output limits from observed counters. Do not force an
inference, publication or trade to demonstrate diagnostic coverage.

Private connection and resource bounds
--------------------------------------

Local transport diagnostics
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The cloud preserves six fixed, cloud-observed transport categories: HTTP
rejection, excessive response bytes, invalid JSON, timeout, socket failure and
HTTP protocol failure. An observed HTTP status is retained only as a true
integer from 100 through 599. These diagnostics do not identify why the PC or
Ollama failed; a gateway 503 is not proof of a broken tunnel or model crash.
No response body, exception text, URL, prompt or output is retained.

Only local failures receive this additive metadata. Shared completion attempts
store ``local_transport`` in the existing failure JSON in ``ai_call_usage``;
final stock reviews store it in that failed attempt's existing ``attempts_json``.
The final-review ledger rejection string is unchanged. Existing readers may
ignore this optional field; no migration, flag, backup format or PC gateway
update is required. Missing historical metadata remains unknown and is not
reconstructed. No production failure is forced to demonstrate coverage.

Exception type/message, timeouts, byte limits, capacity-413 semantics, cooldown,
paid fallback, repair allowance and Telegram notifications are unchanged.
A valid HOLD remains final. A failed fourth canonical stage after editorial
repair remains terminal; this change does not authorize another model call.

The inference gateway uses only loopback Ollama, pinned weights and an 8192
context. It has one GPU slot/no generation queue, eight HTTP handlers, bounded
input/output bytes, native no-truncation context rejection and a bounded
real-request budget including metadata, loading and generation. The
30-second metadata observation uses GET tags/version/running-models only;
neither it nor GET health loads, unloads or renews a model lease. Compatible
cold metadata is ready to accept work; resident weights are not a prerequisite.
Busy, asleep, disconnected, changed weights, a wrong resident context or
oversized context remains unavailable, not an opportunity to invent data.
Large prompts may use paid fallback; "local when ready" includes capacity.

Demand-only model lifetime
~~~~~~~~~~~~~~~~~~~~~~~~~~

Only a validated, nonempty real completion sends POST chat. The same existing
nonblocking single GPU lock covers metadata validation, native demand loading,
generation and result identity validation; competing requests do not queue or
start another preload. There is no empty-message warmup. The native request's
``keep_alive=2m`` allows Ollama to release weights after two idle minutes.
The gateway never sends a periodic or timer-based unload, so it cannot unload
an active request. Native expiry follows request completion; metadata polling
does not extend that lease. No global Ollama/Windows/pagefile setting changes.

Protocol1 health identity, model/digest, context policy and capacity1 are unchanged. Additive
health fields ``model_loaded`` (last fresh metadata observation, or null),
``load_policy=on_demand`` and ``keep_alive_seconds=120`` distinguish admission
from residency. Health remains a fast200 response with identity even when busy
or unavailable. Protocol1 completions keep their45s gateway budget. Version2
is negotiated only for exact ``completion_policy=bounded_cold_start_v2``,
``supported_completion_protocols=[1,2]`` and ``completion_timeout_seconds=120``
with the pinned identity/context. No arbitrary advertised timeout is trusted.
Missing or malformed capabilities retain legacy client behavior.

Version2 observes native residency under the same GPU slot: a cold request has
at most120s including metadata/load/generation/post-validation; a warm request
still has45s. Both clients bound one version2 request to125s INCLUDING health
(at most2s) and all response reads; POST receives the remaining budget, not a
fresh125s. The gateway overrides ``gateway_protocol=2`` and the actual45/120s
budget in the result. A result reporting a warm budget is still rejected after
the original50s envelope. A rolling rollback cannot cause a hidden second POST
or protocol downgrade after an ambiguous attempt. Existing attempt counts,
deferral, circuit behavior and paid protections are unchanged. A whole research
run can contain several separately bounded calls;125s is not its lifetime limit.

One additive ``last_request`` health observation contains only protocol,
cold/warm classification, fixed phase/outcome, budget and elapsed milliseconds.
It retains no request ID, prompt, response, native error or checkpoint data.
The120s cold budget is a finite application transport bound, NOT a Windows
memory/pagefile limit change or a guarantee against active-research pressure.
Actual cold completion and native idle eviction must pass separate live proof;
green source tests alone are not release acceptance.

The rollout retains the exact previous gateway and launcher for return. Stage
compatible clients before activating the version2 gateway; while the old gateway
is active they retain legacy behavior. Use the existing release process for
the affected transport components only, with no queue or trading-setting edits.
Do not interrupt active research merely because a health snapshot looked idle.
Check current source/process ownership and retained job state, account for the
existing application supervisor, and preserve client retry/checkpoint behavior.
No model/quality change is required. Dahan hashes its transport module as part
of its research engine signature: its separately reviewed exact-source transport
compatibility bridge is required to preserve saved-call reuse. Unknown source
or research-logic changes must still get a new signature; never relabel saved
records or assume that a transport-only edit automatically preserves progress.

Final-review capacity correction
-------------------------------

The original byte-as-token upper bound rejected complete stock inputs before
generation, even when their tokenized prompt could fit. Final input JSON is now
compact UTF-8, without deleting fields, zones, candles, timestamps, news, SEC
facts, unknowns or negative evidence. System instructions, decision validation
and all trading gates are unchanged. The paid fallback sees the same facts.

The pinned Ollama 0.34.4 API supports ``truncate=false`` and ``shift=false``.
The gateway explicitly uses BOTH on every actual request,
retains context 8192, output/deadline/transport bounds and one GPU slot, and
delegates actual token/template fit to that runtime rather than confusing bytes
with tokens. Over-context error or incomplete output must fall back/fail closed;
it must not return a successful decision from a cropped prompt. No context-size
increase, tokenizer approximation, evidence truncation or parameter sweep.

Only exact allowlisted capacity errors become private ``413`` /
``local_context_capacity``.
The native runner's JSON-string error envelope is also accepted only when its
400 code, capacity type, complete key set and token/context counts agree with
the exact message and pinned context. Duplicate keys, unrelated errors and
inconsistent envelopes remain technical failures, without leaking raw errors.
Capacity errors do not start the healthy local provider's
60-second technical-outage cooldown. Actual transport/schema failures retain
that cooldown. Capacity consumes the existing request/repair allowance; there
is no additional model-shopping attempt. Every paid fallback still checks cap
and pace. Valid HOLD/low confidence is never retried with another model.
The canonical ``local_fallback:`` stage explicitly selects its existing paid
provider for that request only, rather than relying on a global outage timer.
The following independent stage can use the healthy local model again; the
canonical job's shared repair allowance is neither reset nor expanded.

The new health capability is ``context_policy=no_truncate_no_shift_v1`` with
``context_length=8192``. During a rolling update, a new client must retain the
original conservative guard for an old/unverified gateway; it never sends that
gateway a large prompt. A capacity fallback does not poison subsequent smaller
jobs. An old client can use the new gateway's unchanged protocol 1.

Deploy the reviewed PC gateway and cloud application as a coordinated release,
through existing readiness/backup/rollback gates only. No schema, saved trading
contract, live flag, model or strategy change is required. Keep the previous
gateway file/actual application image for return; never rewind the database.
Synthetic/mocked tests prove the code contract, not actual native token fit,
model quality parity or a natural trade. Before declaring local coverage fixed,
verify a synthetic full-input and an intentionally over-context request against
the exact installed runtime, without DB/paid AI/public Telegram, and audit the
next natural final-review provider/decision. Missing natural BUY is not a
release failure or permission to loosen confidence/news/risk gates.

Frozen primary contract:
https://github.com/ollama/ollama/blob/v0.34.4/api/types.go
and runtime forwarding / refusal paths:
https://github.com/ollama/ollama/blob/v0.34.4/server/routes.go
https://github.com/ollama/ollama/blob/v0.34.4/llm/llama_server.go

Cloud apps use ``/run/ollama/relay.sock`` mounted read-only. The PC opens a
dedicated outbound SSH Unix-socket reverse tunnel to this socket. No host TCP
port is exposed, no GatewayPorts change, no HTTP redirects/proxies, and no
OpenRouter/DB/Telegram credential is placed on the PC gateway. Monitor and
backup have no relay mount or group access. The app remains the sole writer.

Provisioning requires separately approved production release/operator access:

1. Create a dedicated ``ai-inference`` user with NO sudo/Docker/trading group,
   dedicated group ID 20001 (abort if already used incompatibly). Its only
   writable relay directory is ``/opt/ai-trader-ollama``, owner ai-inference,
   group 20001, mode 0750. Socket mode must be 0660; never world writable.
2. Generate a dedicated Ed25519 key on the PC with protected ACLs. Do not reuse
   the administrative key. Install ONLY its public key in this user's
   authorized_keys with ``restrict,port-forwarding``. Preserve known-host pins.
3. Install reviewed ``deploy/ollama-sshd.conf`` as an SSH Match drop-in. Test
   ``sshd -t`` and ``sshd -T -C user=ai-inference,host=localhost,addr=127.0.0.1``.
   Confirm TCP/sessions/password/agent forwarding denied, remote stream-local
   allowed. Reload (not restart) SSH without interrupting existing connections.
   Do not proceed if the effective policy differs.
   OpenSSH 9.x needs ``AllowTcpForwarding remote`` for its shared remote
   permission set even for Unix sockets. ``PermitListen none`` denies ALL TCP
   listeners and ``PermitOpen none`` denies TCP destinations; the real harness
   tests the denial, not just a configuration string. Never omit those rules.
4. Deploy the exact CI/Readiness-approved app SHA using the existing release
   path, encrypted backup and compatible actual server-image rollback. Keep
   cloud_only until loopback gateway + restricted tunnel + container health
   are verified. All other runtime.env settings remain untouched.
5. Run ``scripts/start-ollama-inference.ps1`` with dedicated identity, pinned
   known-host file and Python with requests/jsonschema. This starts inference
   ONLY, not start-ai-trader.ps1. No new automation/scheduled task is installed.
6. Verify denied shell/TCP, socket permissions, cold/busy/offline fallback,
   model/digest/version, actual scanner/telegram health and a synthetic isolated
   request without signals, public messages or paid AI test calls. Then change
   ONLY AI_INFERENCE_MODE to ollama_first and coordinate inference-role restarts.

Stop and rollback
------------------

Private connectivity notifications
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The existing cloud Telegram operations worker observes the private gateway
with one bounded GET /health per minute while ``ollama_first`` is enabled.
There is no generation, paid request, local trading worker or new scheduled
task. Monitoring therefore works even when the PC is powered off. Missing AI
jobs do not indicate stale connectivity.

Three consecutive failed connection/identity checks spanning at least two
minutes enqueue one private Admin failure. Two ready checks spanning at least
one minute enqueue one recovery. Episode state and Admin outbox insertion
commit together and persist across worker restarts; unchanged failures do not
repeat. Busy/cold but reachable does not mean disconnected and cannot by
itself trigger either message. A recovery verifies the pinned model and ready
gateway, not a successful new inference. Raw errors/URLs/credentials are not
included, and no public chat fallback exists.

``cloud_only`` stops the observer without claiming a local recovery. No schema
migration, model/sizing/trading/TP-SL/budget/routing change is required. The
observer does not change local routing cooldowns. Existing outbox delivery
rules, including ambiguous-delivery handling, remain unchanged. A full cloud
or Telegram outage still cannot be reported by this in-process observer.

The PC connector is session-scoped unless an operator separately configures
Windows logon startup. It reconnects after a transient network/sleep break,
but a PC reboot terminates that process; do not claim logon autostart exists.

Kill switch ``cloud_only`` stops local selection for NEW calls; it does not
undo previous decisions or stop positions/TP/SL. Preserve current data and
schema 7. A compatible previous actual server image is the binary rollback,
with its previous Compose file. Never rewind DB or downgrade saved contracts.
No auto top-up or automatic threshold reduction during fallback. Do not call
availability of this Codex session a requirement for cloud trading operations.

Verification gaps must be explicit: local fixtures are not a live private
tunnel, a native JSON schema is not a forced OpenRouter function envelope,
and a model's score has not been calibrated to Luna's score. Audit actual
providers/costs and quality rejects separately after an approved activation.

Primary transport references: https://docs.ollama.com/api/chat and
https://man.openbsd.org/sshd_config.5; OpenSSH 9.6 implementation of the shared
remote forwarding permission set:
https://github.com/openssh/openssh-portable/blob/V_9_6_P1/session.c
