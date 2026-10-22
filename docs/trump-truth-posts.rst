Trump Truth Social relay notifications
=====================================

Scope and honest source identity
--------------------------------
The human selected Truth Social only, every new post (including non-economic
posts), not X. This opt-in path reuses the existing public Telegram reader and
durable bot outbox. It does not feed scanner news, change trading admission,
increase AI budget, translate text with a model, or create a worker/schedule.
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
The source-language excerpt is explicitly labelled; no AI interpretation,
translation, factual endorsement or automated trading signal is generated.

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
