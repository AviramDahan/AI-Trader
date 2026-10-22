Trump Truth Social relay notifications
=====================================

Scope and honest source identity
--------------------------------
The human selected Truth Social only, not X. The23October clarification below
supersedes the earlier all-posts policy: original relay-classified publications
only, including non-economic originals. This opt-in path reuses the existing public Telegram reader and
durable bot outbox. It does not feed scanner news, change trading admission,
increase AI budget, or create a worker/schedule. An independently opted-in
local-only Hebrew presentation is described below; default source-language
mode does not invoke a model.
It is separate from PR97's low-impact MARKET brief policy.

Source: https://t.me/realDonaldTrump_Truth . It is a third-party relay, NOT an
official Trump channel or the primary Truth Social API. The public broadcast
ID2310477090 and username were checked through the existing authorized scanner
session on22October2026. Its sample contained both Trump and other authors.
An exact ``New Post by realDonaldTrump on Truth Social`` header AND one final
``Truth Social Post Link`` entity to that account are required. Both the
numeric channel ID and username are pinned. RT body links cannot substitute the
new post ID; other authors and ambiguous/malformed notices fail closed.

This establishes only what the relay claims. It does NOT independently verify
primary authorship, original text/time, completeness, edits/deletions or delay.
Each notification states this prominently. Primary publication time is UNKNOWN;
the relay timestamp is labelled separately, never substituted for primary time.
No licensed Truth API contract or additional account/credential is provisioned.
Source access is not itself a republication license. The operator must review
source/usage permission before enabling; only a bounded excerpt and source
links are sent, never a claim that the entire original text was reproduced.

Publication and coverage
-------------------------
No relevance, materiality or economic-topic filter applies to this dedicated
notification stream. These filters remain unchanged for ALL ordinary news.
One original Truth post ID has one durable outbox key even if the relay repeats
or edits it. By default media notices produce a notification with the original
post link. A separate default-OFF genuine-file capability is described in
``trump-truth-media.rst``: only actual attached relay Photo/MP4 Document files
can be boundedly acquired/reuploaded; markers and webpage previews cannot.
The independently observed latest20 relay messages on22October contained20
webpage previews and zero supported files. This sample does not establish
future coverage or a natural successful media delivery. Reposts, including
self-reposts with a distinct Trump account footer, are now excluded.
The source-language excerpt is explicitly labelled by default; the optional
Hebrew presentation is labelled as AI translation of the relay EXCERPT, not
the complete primary post or factual endorsement. Neither mode is a trading
signal or feeds scanner news.

Messages route to the existing MARKET/general-news topic, never trading or
General if a news topic is unconfigured. This event preserves the original and
relay links; ordinary news's operator-selected link cleanup stays unchanged.

The initial activation/re-activation/clean restore establishes a latest-ID
cursor without sending any old messages. Live events wait for that persisted
fence. Later catch-up reads the oldest50 unread per existing cycle and retains
the durable cursor, including posts older than the ordinary reader's six-hour
window. No promise of a complete primary timeline or zero missed posts is made.
Malformed Trump notices are counted in the channel checkpoint and mark coverage
degraded rather than being invented or reclassified as ordinary news. Provider
flood waits, bounded pagination and source outages mean coverage remains PARTIAL.

The outbox insert commits before cursor advancement; a crash between them is
safe to revisit through the same original-ID dedupe. A failed enqueue does not
commit the new reader cursor. Restart resumes the existing cursor. No outbox
history/cursor is invented after an active-state-only restore: the next initial
fence explicitly skips historical catch-up. Existing mode/epoch and BOTH
canonical/environment cutover fences are checked at enqueue and send time.

Telegram supplies no idempotency key for sendMessage. A definite connection
failure may retry with the same retained provenance envelope. Unknown delivery
(read timeout, connection ambiguity or stale sending lease after a crash) is
terminal/manual review, never automatically resent. Therefore database dedupe
and no blind resend are proven, not impossible exactly-once external delivery.
The version-specific ``trump_pending``, ``trump_retry`` and ``trump_sending``
states are ignored by the previous9c/compatible older dispatcher. A rollback
cannot accidentally send the JSON envelope or route it to trading. There is no
DB rewind, queue deletion, automatic replay or change to existing event states.

Original-only relay publication policy (23October clarification)
----------------------------------------------------------------
``original_relay_v1`` is a deterministic, conservative relay-marker policy,
NOT primary authorship verification. Only pinned-channel extraction assigns
``publication_policy`` after the existing exact Trump header/final footer and
clock checks. Before source truncation or URL sanitization it inspects the
entire bounded raw body and hidden TextUrl entity targets. RT, ReTruth,
self-reshares, explicit quoted-post/repost markers and body Truth status links
are excluded. Telegram forwarded/reply metadata also fails closed. Unicode
compatibility normalization and removal of concealed format/control characters
are used ONLY for classification, never to rewrite the visible source.
An ordinary article quotation or non-Truth article link in an original comment
is not by itself a platform quote-post. Markerless misclassification by the
third-party relay remains possible; this does not certify official authorship,
complete source text, complete coverage or all true original posts.

Known policy exclusions advance the existing source cursor and have a bounded
checkpoint rejection count; they are not provider errors or a reason to fetch
history again. No channel switch, new provider, account, model, budget or
schedule is introduced. Hebrew and literal retained original/source English
remain displayed together; ordinary financial-news/trading gates do not change.

Live validation requires the exact new policy and ``is_repost=false`` and
rechecks retained markers. This existing validation path is used before
translation, after preparation, for media capture and before EVERY external
bilingual/media stage. Old unclassified queued notices are not grandfathered:
they fail closed and become cancelled/terminal under the existing dispatcher
semantics, without inference or a send. A known ACK is never resent and unknown
delivery is never converted to permission to retry. No cursor/activation reset,
source replay, DB migration, queue deletion or synthetic Production post occurs.

The READ ONLY public feed additionally requires this policy, including on each
frontend row, so a newer website cannot show unclassified rows from an older
backend during rollout. Shared/unclassified old records are hidden from this
feed; the immutable historical-envelope validator, original outbox text,
translation/receipt audit rows and existing asset evidence are NOT rewritten
or deleted. Previously published classified originals remain readable with the
live source OFF. Public requests still never generate or retrieve source data.

An older binary, including PR99, does NOT implement this originals-only policy.
Its financial/schema compatibility is not policy compatibility: a rollback
must keep the Trump source OFF across its producing/sending roles unless a
policy-compatible binary is used. No automated rollback or flag change is
performed by this change. Release review still requires exact CI/Readiness,
independent QA, normal backup/recovery checks and explicit scoped approval.

Controlled activation (not performed by this PR)
------------------------------------------------
Defaults:

* ``TELEGRAM_TRUMP_TRUTH_ENABLED=false``
* ``TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED=false``
* ``TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED=false``
* ``TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED=false``
* ``TELEGRAM_TRUMP_TRUTH_NOT_BEFORE=``

After release review, set a real aware UTC activation time and enable the flag
consistently in the API, scanner and Telegram roles through the reviewed controlled
release process. The existing reader/session and news topic must be configured.
These are independently reviewed flags, not permission to activate all features
from an earlier source-only/two-key Hebrew approval. The final runtime, actual
role starts, encrypted backup binding and exact-source gates must be verified.
The pinned source is appended to at most five ordinary configured public
channels; no join, private-dialog enumeration or personal-account send occurs.
Check the first cursor fence, subsequent natural source observations, actual
outbox status and public news-topic readback; do not manufacture a source post.

Setting the flag OFF cancels claimed queued notifications at dispatch; no
trading positions, exits or other news are changed. Every reactivation MUST
advance NOT_BEFORE to a new real timestamp, so prior pending work remains fenced
even if the sender was unavailable during OFF. Do not reuse an old boundary,
reset cursors or replay history to fill a quota. PEAD and all trading/AI/News
policies, portfolio values, provider budgets and other flags remain unchanged.

Tests use synthetic posts, mock clients/senders and isolated databases. Real
source access/read-only format observation is evidence of access only, not a
synthetic/public test send or proof of a future natural notification.

Optional Hebrew presentation (hebrew_v1)
----------------------------------------
The separate opt-in flag translates every eligible topic, not just market
posts, using ONLY the already pinned local Ollama model/relay. Local readiness,
capacity and existing context/deadline checks remain authoritative. There is
NO OpenRouter/paid fallback, new model, account, API key or budget increase.
Local unavailability is not permission to contact a different provider.

The existing scanner translation loop prepares at most one post per cycle,
outside a database transaction and outside the shared Telegram dispatcher.
The existing legacy news translation cadence remains ten minutes. Optional
preparation cycles sleep fifteen seconds after work; one attempt comprises at
most two bounded local requests (draft and bilingual editor). These use the
same pinned model, NOT independent models or human verification. Existing
local capacity is shared: this adds bounded local compute demand and can
defer other local work. No local-generation priority guarantee is claimed.
Actual native token counters and known zero API cost use the existing sole
``news_translation`` ledger; missing usage is not estimated.

Only the bounded, cleaned relay excerpt is sent to the model as untrusted
data. Account identity, timestamps, original/relay links, dedupe key and
warnings are deterministic, never chosen by AI. No media captions are invented.
An empty/media-only excerpt yields a Hebrew link notification without AI.
A link-only RT/ReTruth is not the quoted post's body: it also bypasses AI and
is explicitly labelled as a repost whose text was unavailable in the relay.
Neither English ``Image/Video`` boilerplate nor an isolated RT link is sent as
a purported source excerpt. The post/translation is placed before the compact
source/time disclaimer; original publication time remains unverified and the
relay's timestamp is displayed as a clearly labelled human-readable UTC time.
Mechanical guards reject changed numbers, currencies, magnitude/percent units,
unsafe scripts/controls and model-added link/contact forms. A second same-model
pass must accept fluency, completeness and fidelity. These are negative guards,
NOT proof of semantic accuracy, primary truth or complete source coverage.
Real translation quality remains unverified until natural reviewed examples.

New outbox states are ``trump_hebrew_pending``, ``trump_hebrew_translating``,
``trump_hebrew_ready``, ``trump_hebrew_retry`` and ``trump_hebrew_sending``.
Preparation uses a five-minute lease and records each attempt before generation;
at most two attempts survive crashes/restarts. A prepared cache is bound to the
exact outbox row, excerpt, source identity, activation/fence and version, in
existing ``scanner_settings`` keys ``trump_truth_hebrew_v1:<row_id>``. Source,
epoch, cutover, ownership and expiry are checked before EACH local request,
after preparation and again before sending. An already in-flight request cannot
be recalled, but cannot authorize a later request or a revoked publication.
Malformed/stale caches are blocked, never silently trusted or regenerated in
the sender. Definite send retry reuses the approved translation; ambiguous
delivery remains terminal/manual review, never blind resend.

If both bounded attempts fail, send an explicitly labelled Hebrew
``translation unavailable`` notice and original/relay links, not an English
excerpt masquerading as Hebrew. The final rendered message must fit Telegram's
4096 UTF-16 limit INCLUDING the final Telegram bidi-control expansion; neither
serialized provenance nor a translation is sliced to fit. If the complete
validated translation cannot fit, a whole explicitly unavailable notice and
both links are used, without another model request. The shared formatter for
other news/trade messages is unchanged. This is presentation only, not source
coverage guarantees. Optional file acquisition is a different, separately
gated capability and never changes these translation/model budgets or guards.

Enable consistently in scanner and Telegram through a separately approved
release. Advance the existing ``TELEGRAM_TRUMP_TRUTH_NOT_BEFORE`` to a real new
UTC boundary when enabling/re-enabling this presentation; do not reset reader
cursors or translate/replay previously queued source-language posts. Such old
rows are cancelled by the Hebrew sender. Turning either source/Hebrew OFF
blocks queued Hebrew delivery. Re-enabling MUST advance that boundary, so old
work cannot spring back after an OFF interval with an unavailable sender.

The previous deployed 2d72146 binary ignores all five Hebrew states and cannot
send their JSON or bypass mandatory preparation. It does not implement this
new flag: after rollback it could create source-language notices for FUTURE
posts if the original source flag stays enabled. For Hebrew-only continuity,
leave the source OFF on such rollback until a compatible binary is available.
There is no DB rewind, deletion, automatic queue replay or financial mutation.
A full database restore preserves row/cache together; an active-state-only
restore does NOT promise historical outbox or translation cache reconstruction.
Missing cache means blocked/cancelled, not invented historical translation.

Optional complete Hebrew and original/source publication (bilingual_v1)
-----------------------------------------------------------------------
The explicit bilingual goal is a separate default-OFF opt-in requiring BOTH
the source and existing Hebrew flags. A requested bilingual mode with missing
authority fails closed; it never silently falls back to an English-only or old
Hebrew-only notice. The fourth flag must be included in the reviewed API,
scanner and Telegram runtime activation together with the real new cutover.
Old one-language queued work is not replayed or retroactively translated.

The Hebrew block appears first, followed by the actual cleaned relay source
excerpt, generally English but never assumed universally so. The source is
not regenerated, translated into English or represented as the complete
primary post. Media boilerplate and link-only repost placeholders are not
invented bodies. Translation-unavailable, no-source/media-only and link-only
statuses have truthful explanations in both languages and original links.
Existing draft/editor numeric/fidelity checks and the same bounded local model
calls remain unchanged; this introduces no new provider, model or paid call.

One complete combined notice is preferred when the exact final UTF-16 wire
fits4096 units. An available genuine asset can use one combined caption only
when that entire wire fits1024 units. Otherwise complete language blocks are
separate ACK-tracked parts; an asset uses a short factual bilingual caption,
then one combined text or complete Hebrew and source parts, at most three
external stages. Approved Hebrew and the retained source excerpt are NEVER
clipped to fake completeness. Whole-block directional isolates bound bidi
overhead rather than expanding every number and then dropping qualifiers.
The legacy shared formatter and existing Hebrew/media contracts are unchanged.

New ``trump_bilingual_pending/preparing/ready/retry/sending`` states are
invisible to previous2d/74b/5b411 selectors. The existing preparation loop owns
translation preparation; no new worker is created. A ``bilingual_v1`` cache is
bound to the literal envelope version, source and row; legacy ``hebrew_v1``
archives/caches retain their original validation. Separate
``trump_bilingual_delivery_v1`` receipts bind the exact ordered part hashes,
language coverage, destination and known ACK ID for EVERY part. An old media
or Hebrew complete status cannot certify that the source/English part was
sent. JSON object-key ordering is not interpreted as ACK order: the ACK set
must equal an exact prefix of the ordered plan, with only its next stage active.

Every external stage/WAL checks the exact unexpired claim, current source and
four-flag authority as applicable, and the exact unchanged prepared cache/plan.
Unknown ACK/crash or lost authority stops further parts without guessing or
resending accepted ones. Safe retry resumes only unacknowledged parts. Partial
two-/three-stage delivery is possible; exactly-once external delivery remains
impossible to promise. A later flag/cutover change does not erase already-sent
valid bilingual history or authorize a resend.

The public archive requires the exact new COMPLETE receipt before labelling
a bilingual publication. When its valid translation cache remains, its entire
plan must match the sent hashes; a later valid-but-unsent substituted draft is
not shown as published. A missing cache is explicitly NOT_RETAINED, never
reconstructed, while literal retained source may remain visible. Asset access
also requires this new proof, not a legacy media receipt. Old already-sent
Hebrew history remains separately readable without reinterpretation.

Optional genuine media and published website archive
-----------------------------------------------------
Available media uses ``trump_truth_media_v1`` descriptors bound to literal relay
identity, original post ID, activation, source clocks and cleaned source text.
No access hash, Telegram file reference or private cache path is public. Actual
acquisition happens only in the existing pinned reader with owned private
session/cache permissions and strict file/count/byte/time limits. Marker-only,
unsupported and failed acquisitions remain truthful ordinary link notices;
they do not enter media-pending states or trigger invented captions.

The new media pending/preparing/ready/retry/sending states are invisible to
previous74b dispatchers. Long approved Hebrew is not clipped into a1024-unit
caption: a short factual media caption and full notice use separate durable
write-ahead/ACK stages. Each stage rechecks the exact prepared presentation and
current authority. Missing/revoked cache, unknown ACK or an expired sending
lease cannot authorize blind resend or text fallback after media failure.
Partial two-stage delivery remains possible; exactly-once external delivery is
not guaranteed.

The website archive validates only already-sent Hebrew rows and their retained
source/cache provenance. Current switches/cutover advancement do not erase past
good published history and never authorize another send. A media endpoint uses
an opaque content token bound by a complete known-ACK receipt to an exact sent
row; no public request downloads from Telegram/Truth Social or generates text.
Neither website stored-sent status nor Bot API ACK proves a phone displayed it.

The optional file cache resides on the private runtime volume; it is NOT part
of the encrypted application/database snapshot. A DB restore may retain media
descriptors/receipts while the actual optional files are absent. Such media is
unavailable/UNKNOWN, never regenerated, refetched or claimed restored. Cache
loss and full-cache bounds may prevent file availability; original links remain
the honest alternative. See ``trump-truth-media.rst`` for limits and recovery.
