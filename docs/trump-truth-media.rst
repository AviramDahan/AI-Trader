Trump relay media: bounded optional delivery
===========================================

Scope and honest availability
----------------------------

``TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED`` is separate and defaults OFF. Enabling
the source or Hebrew presentation alone does not enable file acquisition.
The source remains the pinned public relay, not verified primary authorship.
No model, OCR, transcription, inferred image caption, external asset URL,
Truth Social scraping or new account is used.

Only an actual ``MessageMediaPhoto``/``Photo`` or an attached
``MessageMediaDocument``/``Document`` with an MP4 MIME type and a video
attribute qualifies. A webpage preview, thumbnail, ordinary document or body
marker is not a downloadable original asset. The independently observed
22 October sample of20 relay messages contained20 webpage previews and zero
supported attached files. Synthetic tests therefore prove capability, not
natural media delivery or full source coverage. Marker-only/unsupported/missing
assets retain truthful text and source links; no file is fabricated.

Existing reader and resource bounds
----------------------------------

Acquisition runs only on the existing authenticated reader connection, after
strict source/header/footer/activation validation. Capture re-extracts the
literal message and compares its source fields before downloading. No Telegram
access hash, file reference, session credentials or private path enters the
durable envelope or public projection. The session file must be an owned regular
file with0600 permissions on Linux. Its parent must be an owned directory with
no group/other write authority (0755/0750 are acceptable), with no symlinks.
This does not change any target permissions; the private asset cache remains
strictly0700/0600 rather than reusing the session-parent permission rule.

The producer permits at most two downloads and48MiB of declared files per
minute; one file per post; photo8MiB, MP4 video24MiB and30seconds per download.
An in-memory bounded writer enforces the actual byte limit, not only metadata.
JPEG/MP4 signatures are checked without interpreting their content. A failed
download returns a fixed unavailable code, never raw provider text.

The private ``.runtime/trump-truth-media-v1`` cache is capped at64 files and
128MiB. Files are content-addressed, owned0600 under an owned0700 directory,
atomically written and fsynced on Linux. There is no blind deletion or eviction
of unknown files. A full, corrupt or unavailable cache yields no usable asset;
operators must not claim an existing marker is a file. Availability cannot be
promised indefinitely or after restoring a DB without its optional file cache.

Capture records its actual completion/observation time. The Trump-only ingest
path uses the actual post-fetch clock for available media packets, while
ordinary news and text-only snapshot clocks remain unchanged. Future packets
are still rejected; there is no backdating to a pre-download cycle timestamp.

Queue, presentation and side-effect safety
-----------------------------------------

Only successfully captured files acquire ``media_version=trump_truth_media_v1``
and the new ``trump_media_pending/preparing/ready/retry/sending`` states.
Previous binaries do not select these states. Existing Hebrew preparation
handles media rows when Hebrew is enabled; a no-AI preparation path handles
media rows without Hebrew. There is no new worker or generation on dispatch.

A full approved notice is a single caption only when the entire final bidi
wire fits1024 UTF-16 units. Otherwise media carries a short factual source-label
caption and the complete existing notice is a separately tracked text stage;
the accepted translation is not cut to fit. Media is sent first. A media-stage
failure never triggers a fallback or resend of text.

Each external stage has a durable write-ahead state and strict Bot API ACK ID
bound to its row, immutable envelope, asset/text hashes and destination. Every
stage/WAL also requires the exact current claim deadline and an unexpired
lease; a changed or expired batch claim cannot start a later external call.
Production uses a fresh real clock at each check; isolated fixtures inject one
consistent explicit clock. Every stage rechecks source/fences, media authority and the exact existing
Hebrew presentation/cache. Revoked, missing or changed presentation cannot be
sent after a known media ACK. Known media ACKs are not resent when a safely
retriable text stage resumes. Only a confirmed429 rejection or connect timeout
is retriable. Ambiguous responses, unknown IDs, crashes with a sending WAL,
receipt/cache conflicts and other uncertain outcomes stop for manual review.
Telegram has no remote exactly-once token: two-stage delivery can be partial,
and no end-to-end exactly-once guarantee is made.

An expired outbox send lease is terminal unknown, not reclaimed for another
send. A retained receipt does not authorize replay after a flag/cutover change.
Cache loss is not permission to recreate or resend a previously accepted post.

Public historical archive
-------------------------

The public archive is separate from live dispatch permission. Only validated
already-sent Hebrew rows are eligible; old original-language rows are not
retroactively translated. Historical source/fence/activation/sent clocks and
the exact presentation binding remain validated even after current flags turn
OFF or a later cutover advances.

Available media additionally requires a complete durable media ACK receipt and
the exact content hash. An opaque SHA token hashes the publication binding AND
content hash, so identical media in another incomplete post cannot overwrite
an existing published asset's index. It has a single constant-bound index
to its accepted outbox row; GET never scans the filesystem, calls Telegram or
fetches an external URL. The response exposes kind, MIME type, size and token,
never transient references or paths. The same-origin asset endpoint reads and
hash-checks the bytes. Card checks may reuse a bounded verification memo only
while device/inode/size/mtime/ctime are unchanged; any change forces rehashing.
Missing files stay unavailable, not reconstructed. Stored-sent/known API ACK is
not proof that a human device displayed the message.

Release and recovery
--------------------

Repository defaults do not activate Production. Exact-source CI, independent
QA, reviewed rollback compatibility, final-build/runtime/role-start-bound backup
and a separately reviewed activation plan remain required. Runtime source,
Hebrew and media flags must be verified in each owning role; prior two-key
Hebrew activation approval is not media activation approval. Recovery preserves
durable receipts and unknown stages; it must not retry an uncertain send or
pretend a missing file cache was restored from the database. No public test
message or test asset download is required or authorized by unit tests.
