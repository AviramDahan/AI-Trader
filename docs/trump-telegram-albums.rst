Telegram channel album delivery v1
=================================

Problem and scope
-----------------
The reader previously discarded Telegram grouped_id. A captionless three-photo
group became three individually deduplicated notices. Two media captures could
be budget-exhausted and still publish identical text with no attachment. This
fix is for the pinned real_DonaldJTrump Telegram source; channel identity is not
proof of primary Trump authorship. It changes no ordinary-news selection,
translation fidelity, trading, AI model, risk, budget or publication threshold.

Acquisition and coverage
------------------------
The existing 60-second catch-up owns source media. Live album and standalone
media events do not independently download/publish. New grouped messages retain
their exact positive signed-64-bit identity. A bounded 21-ID neighbor lookup
validates every member against pinned peer, activation, original-only policy,
source times, supported Photo/MP4 and exact asset identity. A group must be
settled for60seconds and have the same source manifest at two observations
at least60seconds apart. Telegram exposes no album-complete marker: this is
bounded supported coverage, not proof of complete primary-account history.

Supported groups have2–10 contiguous message IDs, publication span at most2s,
one unique source caption (or none), and at most64MiB declared aggregate media.
Noncontiguous, multi-caption, unsupported, changing, oversized or unverified
groups defer the Trump cursor with a fixed reason. They never partly publish or
become standalone notices. Other channels continue. No caption/OCR is invented.
The representative is the sole caption-bearing member when there is one;
all media members remain in original ID order.

Existing per-file limits,2files/48MiB per minute and128MiB/64file private cache
are unchanged. Partial acquisition and an additional durable album minute budget
live in existing scanner_settings. The cursor stays before an incomplete group.
Captured source revisions, actual observation times, SHA256 and private bytes
are reused next cycle/restart; no re-download of the first two files to get the
third. A lost/untrusted file blocks rather than sending an empty placeholder.
Observed source edits revoke the frozen group. An unseen external edit/deletion
after the last source observation cannot be ruled out by local state checks.

Queue and sends
---------------
One bounded envelope references the frozen persisted manifest. In the same
transaction it reserves every old per-message dedupe key in a non-dispatchable
member state. Any existing pending/sent/failed/unknown member prevents takeover.
New versioned preparation/ready/retry/sending states are invisible to old queue
selectors. Existing Hebrew translation/editor validation is reused once for
the source caption; captionless media needs no AI or warm-model health.

One sendMediaGroup request uploads all members and puts the Hebrew caption only
on the first. A long caption uses the existing bounded caption plus one full
Hebrew text stage. Every stage has a durable exact-lease/CAS write-ahead receipt,
source/fence/manifest/cache/destination rechecks and strict ACK validation. All
returned member IDs must be distinct, in the exact target topic/chat and same
nonempty media group. Known ACKs are never resent. Explicit429/ConnectTimeout
can retry; timeout, malformed/partial ACK or a crash in a sending stage remains
UNKNOWN/manual review. There is no generic-text fallback.

Bot API protocol reference: https://core.telegram.org/bots/api#sendmediagroup

Compatibility and release limitations
------------------------------------
No database migration or financial-state contract changes. Existing single-post
and legacy relay contracts remain. The public website/MiniApp historic archive
currently supports single assets only: new album envelopes are explicitly
excluded, rather than projecting their first photo as a complete album. This
PR does not implement a multi-asset web gallery.

IMPORTANT:475bf51 and earlier producers ignore grouped_id. Their old queue
selectors cannot dispatch the new states and member reservations prevent a
fully queued album from being re-enqueued. However, an INCOMPLETE acquisition
has not yet reserved members: rolling an old source-ON producer back across
that phase is UNSAFE. Before any future release, retain a compatible image
with this reader/queue contract, or disable the existing dedicated channel
source before rolling back to475bf51. Do not automatically toggle it here.

Active-financial-state backups do not retain news acquisition/translation/WAL
settings or media cache. A restore's existing activation/cutover fence prevents
replay; missing historical delivery information stays UNKNOWN. Do not rebuild
receipts, delete reservations, rewind the DB or replay history to reconstruct it.
No claim of uninterrupted album continuity after such a restore is made.

Acceptance
----------
Use synthetic files, mocked Telethon/Bot API/model callbacks and disposable DBs.
Cover source group identity, page edges, simultaneous live/catch-up admission,
budget deferral/restart, captions, existing member collisions, expired/revoked
claims, exact-array ACKs,429, ambiguous ACK and post-ACK restart. PostgreSQL tests
exercise atomic member claims, real queue lifecycle and concurrent WAL CAS.
CI/Readiness and independent QA are engineering evidence only. No Production
send/replay/deletion, live model call, merge or deployment is part of this task.
Natural complete-album proof remains WAITING_FOR_RELEASE_AND_NATURAL_EVENT.
