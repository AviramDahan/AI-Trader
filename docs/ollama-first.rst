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

Private connection and resource bounds
--------------------------------------

The inference gateway uses only loopback Ollama, pinned weights and an 8192
context. It has one GPU slot/no generation queue, eight HTTP handlers, bounded
input/output bytes, native no-truncation context rejection and a 45-second generation
deadline. Warmup is separate and bounded (90 seconds); health remains false
until the exact model is loaded. Busy, asleep, cold, disconnected, changed
weights or oversized context is unavailable, not an opportunity to invent data.
Large prompts may use paid fallback; "local when ready" includes capacity.

Final-review capacity correction
-------------------------------

The original byte-as-token upper bound rejected complete stock inputs before
generation, even when their tokenized prompt could fit. Final input JSON is now
compact UTF-8, without deleting fields, zones, candles, timestamps, news, SEC
facts, unknowns or negative evidence. System instructions, decision validation
and all trading gates are unchanged. The paid fallback sees the same facts.

The pinned Ollama 0.34.4 API supports ``truncate=false`` and ``shift=false``.
The gateway explicitly uses BOTH, including its first bounded empty warmup,
retains context 8192, output/deadline/transport bounds and one GPU slot, and
delegates actual token/template fit to that runtime rather than confusing bytes
with tokens. Over-context error or incomplete output must fall back/fail closed;
it must not return a successful decision from a cropped prompt. No context-size
increase, tokenizer approximation, evidence truncation or parameter sweep.

Only exact allowlisted capacity errors become private ``413`` /
``local_context_capacity``. They do not start the healthy local provider's
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
