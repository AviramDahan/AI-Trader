Truth relay public archive
==========================

The website and MiniApp NEWS route has a separate Truth Social relay archive.
It is not mixed with financial news, sentiment, tickers, materiality, trading
signals or the financial-news filters. No market-relevance filter is added.

Read contract
-------------

``trump_truth_public.payload`` opens one repeatable-read READ ONLY snapshot
(SHOW verification, 5-second statement and 2-second lock timeouts); SQLite uses
query_only and BEGIN. It never initializes data, translates, fetches a source,
dispatches outbox work, calls a model or writes a read mark. The existing public
dashboard gets an additive ``trump_truth`` page. ``GET /api/scanner/trump-posts``
permits 1..20 items, inspecting at most 60 retained source rows plus one lookahead
and their exact translation-cache keys. Pagination uses the public Truth post ID,
not the private outbox ID. The window is the last seven days of stored sent status.
Invalid/expired cursors fail closed. A response is capped at 256 KiB. A failed
projection is UNAVAILABLE, not an invented verified zero.

Eligibility is already-sent, explicitly ``presentation=hebrew_v1`` or the new
``presentation=bilingual_v1`` only. New bilingual rows additionally require the
dedicated ``trump_bilingual_delivery_v1`` complete receipt: every bounded language
and optional-media stage has a positive ACK tied to this exact source/plan. An
old ``sent`` status or old media ``complete`` record cannot substitute for it.
The old
original-language envelopes are excluded even if sent; therefore the 14 old
malformed notices deleted from Telegram and the nine older English notices are
not republished on the new website. This is a read-only archive, not authority to
send: a later source OFF switch, activation advance or cutover does not erase
good already-published Hebrew history. Frozen relay identity, exact author URL,
dedupe key, historic fence shape/boundaries and causal aware clocks are checked.
The source remains a pinned relay; original authorship/content/publication time
are NOT independently verified.

Only the exact bound validated translation cache is displayed as Hebrew. Missing,
working, corrupt or restored-without-cache data is ``not_retained`` with null text,
never English relabelled as Hebrew or a new inference. ``unavailable``, media-only
and link-only outcomes get concise truthful source-linked status cards. The same
whole Telegram wire-size rule is applied to legacy Hebrew-only cached notices,
not clipping their tail on the website. The new bilingual contract instead
retains a bounded multi-part plan and publishes only after every part's ACK;
the legacy single-message fallback must not discard an approved translation
just because the combined Hebrew+English exceeds one message.

Both approved Hebrew and the exact cleaned original-language/English relay
excerpt are visibly displayed by default in ONE card, under either UI language:
Hebrew RTL, English/source LTR, separately attributed. English is not generated
by AI and is not represented as the full primary post. A missing source body,
link-only repost, missing translation or unavailable media has concise notices
in BOTH languages, without inventing a caption/transcript/repost body. A missing
retained translation is not reconstructed from a delivery receipt. Historical
Hebrew-only Telegram posts remain readable with their real source excerpt on
the website; they are not resent or relabelled as past bilingual Telegram sends.
These are retained approved presentation inputs, not a historical phone-receipt
or byte-for-byte reconstruction of an earlier Telegram rendering version.

Public JSON is an allowlist: no raw envelope/cache, fence, activation, lease,
attempts, prompt, private row ID, destination, Telegram access hash, file reference,
bot URL, secret or local path. ``sent`` is stored outbox status, not proof of a
particular user's phone delivery. Relay-published, observed and recorded-sent UTC
timestamps are separate; original publication time is explicitly unknown.

Media
-----

The optional media component validates an actual attached asset and durable send
receipt before returning an opaque per-notice bound token. The cache still uses
the content hash; the public token is not an unscoped alias shared by posts. A text marker or webpage
preview alone never becomes an image/video. The public route uses an exact token
index and exact eligible sent-row lookup, then rechecks source binding, complete
media ACK and cached file hash. No public cache directory, Bot file URL, arbitrary
fetch, path parameter or source download is exposed. Responses are no-store with
nosniff and restrictive content policy; photo/video bounds remain 8/24 MiB.
Missing files/cache or unavailable assets show a source-linked limitation. A video
has controls with no autoplay and preload=none; image loading is lazy. This does
not establish that the current relay actually supplies downloadable attachments.

Display and scope
-----------------

The separate component is RTL/LTR/mobile responsive, escapes source strings, validates
fixed source links and media tokens and shows stale/error/empty states separately.
At most 100 cards can be loaded in one browser view. Existing financial news,
strategy controls, paper execution, AI model/budget and Telegram source gates are
unchanged. GET has no delete action. Any old-message removal is a separate explicit
human-authorized operation by the coordinator, not an implicit public endpoint.
