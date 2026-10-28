Ollama and paid fallback
=======================

With ``AI_INFERENCE_MODE=ollama_first``, ``AI_OPENROUTER_FALLBACK_ENABLED`` defaults
to ``false``. Local health failures, transport errors and context-capacity
rejections cannot select OpenRouter. Schema repair may still use Ollama within
the existing attempt limit. Local outage before a job is claimed blocks that
job; an in-flight failure follows the existing bounded failure handling.

To restore the previous fallback behavior, set the flag explicitly to ``true``
through the existing runtime configuration/release process. The configured model,
credentials, paid budget and retry limits are retained. Explicit ``cloud_only``
mode remains a separate operator choice, not a fallback from local inference.

Public market paraphrases
=========================

The existing bilingual quality review can compare a market story with up to four
recent actually-sent market notices. Previous context comes from immutable
``ne_versions`` evidence and the actual saved outgoing text, within six hours.
Token overlap selects context only; it does not decide duplication. Peer facts
are never supplied to source analysis. No additional model call is introduced.

Only a valid reviewer reference with no new material fact may suppress a public
repeat. New quantities, explicit periods, measurement variants, corrections and
negation/modality changes retain a deterministic publication veto against
suppression. The original event and analysis stay available; the publication
reason and a metric record the decision. Restart/unchanged ingestion preserves
the reason. New evidence versions are assessed anew.

This is bounded publication dedupe, not a claim that every semantic duplicate
can be recognized. Large/old/unmatched notices are excluded from comparison;
separate metrics and genuinely new information must remain publishable. No
historical notices are deleted or replayed.
