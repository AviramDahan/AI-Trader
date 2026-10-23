Private local-capacity diagnostics
==================================

This is an observability repair, not an increase in local capacity. The pinned
model/digest, 8192-token context, 450-token final-review output request, complete
messages, native ``truncate=false``/``shift=false``, transport bounds, deadlines,
one GPU slot, cooldown, two shared attempts, paid budget and trading gates are
unchanged. A valid HOLD is final. No request is generated to test these metrics.

Boundary and compatibility
--------------------------

The standalone PC ``scripts/ollama_inference_gateway.py`` already recognizes
strict native over-context errors. Previously it discarded validated counters.
It now optionally includes bounded JSON in the private HTTP response header
``X-AI-Local-Capacity``. Its status and body remain exactly the same protocol-1
413 / ``{"reason":"local_context_capacity"}`` JSON contract. An old cloud client
therefore continues to recognize capacity; no new request key or header is
required. An old PC gateway supplies no new header: the new cloud client keeps
the capacity outcome and leaves the additional facts unknown.

``ai_routing`` accepts this header only after the exact allowlisted 413 body,
then revalidates it. Malformed/missing/oversized headers do not change routing.
``final_ai.review`` revalidates the exception metadata again and adds
``local_capacity`` only to that failed local attempt's existing ``attempts_json``.
It never assigns those refused-prompt counts to generated/billed usage tokens
or carries them into a later paid attempt. No migration or new flag is required.
The shared news-completion telemetry is not extended by this narrowly scoped
final-review change.

The optional version-1 object has exact allowlisted keys:

* ``native_token_limit``: ``context_tokens=8192`` and the exact validated
  ``prompt_tokens`` reported by the pinned native runner.
* ``native_capacity_unspecified``: ``context_tokens=8192`` only; an exact
  recognized native error supplied no usable pinned-context count. Unknown is
  not zero and is not a tokenizer estimate.
* ``legacy_guard_upper_bound``: ``context_tokens=8192`` and
  ``legacy_guard_units``. These units are the existing UTF-8 content bytes plus
  per-message overhead, requested output and safety reserve. They are NOT
  measured tokens. This remains only the old/unverified-gateway safety path.
* ``gateway_request_bytes``: ``request_bytes`` and
  ``request_byte_limit=131072`` from the existing gateway byte check. This is a
  transport-size observation, not native context usage.

Each shape also has ``version=1`` and its literal ``source``. An optional
``requested_output_tokens`` is a true integer1..2048 from the actual request,
not output generated or a new limit. Diagnostic counters are true integers
bounded at ten million; booleans, extra keys and inconsistent units are rejected.
The HTTP header is at most512 printable ASCII characters. No prompt, response,
raw native error, URL, news text, arbitrary provider field or account amount is
retained in it. Source identifiers describe the refusal producer, not a verdict
that its configuration was wrong.

Deployment and evidence limits
-------------------------------

The PC gateway is outside the cloud application image. Observing new native
token counters requires a separately reviewed update of BOTH that running
gateway and the cloud client. A backend-only release can record its own legacy
guard evidence but cannot recover previously discarded gateway counters. A
gateway-only update is backward compatible but old cloud readers ignore the
new header. No gateway installation, restart, runtime change or remote inference
is authorized by the tests or this document.

Earlier retained capacity outcomes without these optional fields remain
UNKNOWN as to actual requested local token counts and refusal source. The
diagnostic change cannot recover those historical facts. Cloud billing tokens
cannot substitute for a different native tokenizer/template.
Final-review JSON was already compact lossless UTF-8; no serialization fix,
evidence deletion, context increase or trading-policy relaxation was justified.

Synthetic tests exercise the real mocked native-error -> gateway handler ->
private relay -> final-review trace chain, backward compatibility, privacy and
unchanged fallback allowance. They establish engineering behavior only: not
native model fit, natural failure cause, cost reduction, quality parity or a
new paper entry. Future natural evidence must distinguish these outcomes.
