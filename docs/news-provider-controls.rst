Provider disable/resume and company-news classification
======================================================

Scope
-----
This patch fixes two reproduced application defects and a misleading disabled
reason. It does not resolve the separately observed GlobeNewswire HTTP 403,
enable a provider, reset a live checkpoint, change news/trading thresholds or
declare RSS availability to be a license. No migration or backup-format change.

Corporate grants versus market employment
-----------------------------------------
A headline explicitly describing inducement grants is a business update, not
macro employment evidence merely because its excerpt mentions employment.
Stronger existing company classifications and explicit macro headlines retain
their precedence. The rule is provider-neutral and has no ticker exceptions.
Unverified/out-of-universe issuers remain identity-blocked before AI. Verified
issuers still use the existing stock materiality/relevance/quality gates; grants
are not universally banned. Market recall thresholds are unchanged.

Disable is a reversible configuration overlay
--------------------------------------------
The disabled provider row retains its collector fields and a single exact
``disabled_resume_state`` snapshot. Repeated disabled polls do not nest/reset
that snapshot. Visible status is disabled, error is the current configuration
reason, HTTP is absent and terminal is true. Archived failures are historical,
not a newly observed request or payment demand.

On enable, the collector restores that snapshot before applying its existing
lease, next-at, terminal denial and one-probe recovery rules. It does not extend
a replay fence, reset attempts, clear a consumed probe or change publication
time. HTTP/LLM work stays outside transactions; notices remain existing private
Admin transitions, not public news or a new sender.

An explicitly captured empty snapshot means a genuinely uninitialized provider
and can follow normal first-use approval/activation checks. A legacy disabled
row without a snapshot, a malformed snapshot or an unknown status fails closed
as ``provider_resume_state_unavailable``. It needs legitimate operator access
verification and a documented fresh activation boundary, not a fabricated
history. Missing historical checkpoints are not reconstructed by this patch.
Repeated disable/enable of that hold neither nests archives nor renews a probe.

Configuration reasons distinguish ``provider_not_enabled`` from
``approval_reference_missing`` and an adapter's unsupported configuration.
A retained local approval reference is not independent proof of provider rights;
the old generic timeout/license message must not imply a vendor subscription
requirement. This patch does not contact a provider or buy access.

Verification and release boundary
---------------------------------
Synthetic fixtures reproduce checkpoint loss, renewed exhausted recovery,
backoff loss, misleading notices and corporate grants reaching market routing.
Controls cover known-new providers, old/corrupt resume state, repeated restart,
normal verified stock eligibility, true macro news, company earnings/M&A and
opinion rejection. PostgreSQL tests invoke the same application path in a fresh
test schema. No test sends Telegram, requests a live feed or generates AI.

Run:

* ``python -m pytest service/server/tests/test_news_provider_controls.py service/server/tests/test_press_feed_recovery.py service/server/tests/test_news_events.py service/server/tests/test_news_recall_policy.py -q``
* ``python -m pytest service/server/tests_pg -q`` with an isolated test database.
* Existing full CI/Cloud Readiness on the exact PR head; no deployment.

Production stays unchanged until separately approved release. Keep a denied
provider disabled until legitimate access succeeds and its activation/replay
boundary is verified. Never reset its terminal state to manufacture success.
Existing disabled rows whose metadata was discarded remain explicitly unknown.

Older binaries can read the unchanged JSON storage but do not implement the
overlay restoration/preservation contract. Rolling back to the old buggy
collector is not proof of preserved checkpoints: it can discard the overlay on
its next disabled poll. Keep providers disabled during any such return and do
not enable them without a compatible collector and operator verification. No
database rewind, source replay or historical-message change is part of rollback.

SEC excerpt failure diagnostics
-------------------------------
The canonical SEC evidence adapter preserves ten fixed local extraction/URL
failure codes in its existing per-evidence state and enrichment metric instead
of collapsing them to ``EvidenceError``. Examples are ``invalid_xml``,
``issuer_mismatch``, ``excerpt_too_large`` and ``tabular_layout_unsupported``.
Unknown/non-string reasons and other exception types keep the generic path;
document text, exception messages and URLs are not added to diagnostics.

This is observability only. The same inputs remain rejected and terminal,
with unchanged attempts, retry timing, HTTP metadata, cache keys, identity,
publication timestamps and restart protection. Fetch/429 retry handling is
unchanged. No old states are cleared, retried, reclassified or reconstructed.
It does not add a parser, loosen extraction/size/security/AI/trading gates,
promise more news, or change Telegram formatting/delivery. Schema and backup
contracts are unchanged; older readers can read the existing JSON fields, but
an older adapter will again lose the detailed reason on new failures.

Synthetic SQLite and PostgreSQL regressions exercise the real adapter/engine,
terminal-state restart, unknown-reason privacy, unchanged rate-limit handling
and successful cached extraction. Tests use fixtures only; a deployment and a
new naturally occurring failure would be separate evidence, not implied here.
