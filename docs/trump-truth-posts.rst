Trump Truth Social relay notifications
=====================================

Scope and honest source identity
--------------------------------
The human selected Truth Social only, every new post (including non-economic
posts), not X. This opt-in path reuses the existing public Telegram reader and
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
or edits it. Media notices produce a notification with the original post link;
images/videos are not downloaded or reuploaded. Reposts are eligible only when
the relay supplies a distinct Trump account post footer, labelled as such.
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

Controlled activation (not performed by this PR)
------------------------------------------------
Defaults:

* ``TELEGRAM_TRUMP_TRUTH_ENABLED=false``
* ``TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED=false``
* ``TELEGRAM_TRUMP_TRUTH_NOT_BEFORE=``

After release review, set a real aware UTC activation time and enable the flag
consistently in scanner and Telegram roles through the existing controlled
release process. The existing reader/session and news topic must be configured.
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
coverage guarantees or a media download/upload capability.

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
