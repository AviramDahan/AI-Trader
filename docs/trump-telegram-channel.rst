Trump channel replacement and mandatory Hebrew
===============================================

The operator selected https://t.me/real_DonaldJTrump on25October2026.
This is a Telegram source, NOT X or the Truth Social API. The authorized
read-only observation pinned public broadcast1462338131 and username
real_DonaldJTrump. Telegram did not mark it verified. Primary authorship,
completeness and primary publication time remain NOT_VERIFIED. The latest20
observed posts had no Hebrew and no Truth links; the latest observed timestamp
was23October20:05UTC, about45hours before observation. A source replacement
does not promise freshness or fix historical translation failures.

The separate selector TELEGRAM_TRUMP_SOURCE=telegram_channel_v1 requires
TELEGRAM_TRUMP_CHANNEL_ENABLED=true, the OLD TELEGRAM_TRUMP_TRUTH_ENABLED=false,
and TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED=true. Both source flags true fails
closed. Defaults retain the previous source contract and keep the new flag OFF.
Unknown selectors never fall back to ordinary financial news. Keeping the OLD
flag OFF is required for rollback: an older binary ignores the new selector
and cannot resume its old relay when its original flag is false.

The new source reuses the existing reader, translation loop, local-only model,
outbox, Telegram destination and media ACK mechanism. It does not create a
worker, increase actual model attempts/budgets, call a paid provider or affect
scanner/news trading eligibility. Every eligible body is translated regardless
of economic topic. Raw forward/reply/RT/ReTruth/quote-post markers and hidden
Truth-status links are conservatively excluded before cleaning. This is a
channel-message classification, not verified official authorship. Unknown or
long source text cannot be guessed: text above2400 UTF16 units is excluded
without clipping. Model/context limits and numerical/fidelity checks remain.

Versioned channel-only items use source_kind=trump_telegram_channel_v1 and
publication_policy=telegram_channel_original_v1. For storage compatibility,
the legacy field truth_post_id holds the unambiguous tg:1462338131:<messageID>
namespace, and truth_url holds the REAL https://t.me/real_DonaldJTrump/<ID>
URL. These are NEVER a fabricated Truth post or proof of primary publication.
The channel ID/message ID dedupe survives reconnect/restart and edits. Old
numeric Truth IDs and their retained URLs/history are not reinterpreted.

The new source always prepares hebrew_v1, even if an old bilingual flag remains
set. Its body must pass existing exact numeric/unit/date checks and same-model
editor checks plus Hebrew-dominant script validation. These are guards, not a
guarantee of semantic accuracy. English is never a fallback public body. Two
failed generation attempts terminal-cancel the notice with a fixed reason;
no original-English publication, public unavailable alert or untranslated media
send is substituted. Genuinely textless media can use a factual Hebrew-only
caption, never an invented transcript. Complete final UTF16 wire is bounded;
an oversized message is blocked, not clipped or silently replaced by English.

Before reserving a new-source generation attempt, existing local health and
capacity are checked. Busy/unavailable defers60seconds without spending an
attempt; it does not load the model or bypass concurrency. Races after this
check still use the existing two-attempt crash/lease rules. No completed work
is regenerated for delivery retry. Active source items expire after24hours,
so indefinitely busy/stale work cannot later flood the destination. Uncertain
external sends remain terminal/manual review; known ACKs never resend.

A controlled release must set a NEW real UTC
TELEGRAM_TRUMP_TRUTH_NOT_BEFORE across producing/sending/API roles together
with the selector/flags above. The existing first-observation fence establishes
the new channel's latest message ID without publishing history. Old-source
queued items are rechecked and cannot send after the switch. Do not reset old
cursors, replay history, bulk translate/requeue or delete prior messages.
No Telegram test send or synthetic Production event is needed for acceptance.

Telegram notices for the new channel omit the source URL and the source label;
the channel-only authorship caveat remains visible. Media fallback captions
also omit that URL. The exact source identity and link stay in the retained
envelope and the read-only archive for attribution and deduplication.

Website/MiniApp archives retain old classified Truth history unchanged. New
Telegram rows have Telegram labels and exact source links; nonempty new-source
rows without a bound successful Hebrew cache are excluded. A read never
generates translation or retrieves media. A missing cache after restore stays
unavailable, never reconstructed. Legacy bilingual ACK requirements still
apply only to their actual historical format. Public cursor validation accepts
only the old numeric IDs or the exact new channel namespace.

Verification must separate synthetic source/dedupe/lease/translation/dispatch/
archive regressions, actual deployed build/config/health, and a natural new
channel post -> prepared Hebrew -> known ACK -> visible Hebrew publication.
No new eligible event means WAITING_FOR_NATURAL_EVENT, not end-to-end success.
The earlier six unavailable translations have no retained precise cause; source
analysis of readiness consuming attempts is not proof it caused all six.
