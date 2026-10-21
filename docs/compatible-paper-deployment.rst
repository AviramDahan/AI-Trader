Compatible Paper deployment and format10 recovery
=================================================

Scope
-----

This is an explicit controlled-release path for a version whose active-state
readers exceed the actually running previous image. It does not make an old
format9 reader compatible with format10, alter trading policy or authorize live
broker execution. Both new acquisition/intraday flags remain OFF in the initial
release. PEAD, AI, News, RR, sizing, exposure and TP/SL retain their existing
authority. New settings require a separate activation decision.

Actual old runtime and supported rollback are different identities
----------------------------------------------------------------

The normal direct-compatibility path still verifies the actual previous image
across all five healthy roles and probes both real binaries. An incompatible
old image cannot be silently relabelled, substituted by a tag, or used after
new state may have been written.

The narrowly scoped alternative uses a protected, bounded
``compatible-rollback-v1.json`` certificate. It binds the exact final candidate
commit/tree, the actual previous identity, unchanged runtime configuration,
durable paused entry-control revision, the actual tested and loaded Candidate
and immutable creation-OFF Bridge identities, and protected source/archive and
target-proof hashes. Config digest, platform manifest, index/runnable reference
and source SHA are distinct domains and are verified as such.

The normal deployment process may select the already tested Candidate binary
only through this exact certificate. A normal rebuild is not represented as
the tested binary. Missing, malformed, expired, changed, unsupported or mismatched
proofs fail closed. No mode skips verification of the actual running old roles.

The deployment journal preserves the actual old image separately from the
supported rollback image. Before writers are replaced, cleanup uses only the
actual old service. After replacement, a failed transition converges every role
to the certified Bridge on the same current DB; it cannot fall back to an
incompatible old reader. Original holds/reservations remain; no DB rewind or
automatic entry resume is permitted. An uncertain rollback is reported for
operator intervention, never assumed successful.

Bridge and Candidate can have the same BUILD_SHA but different image identities
and immutable build roles. A healthy Bridge after rollback must not be reported
as successful Candidate deployment. Journals, selected identities and completion
checks must distinguish those states; a failed-release latch is not cleared by
source-SHA equality or a rollback marker.

Backup coordination
-------------------

The managed-backup proof reader recognizes strict integer formats1..10, not
booleans, unsupported future numbers or a schema-label guess. Request, source,
canonical image, snapshot, remote commit, command/mount ownership, timestamps,
freshness and detached no-restart job validation remain mandatory. A valid
writer is never killed, force-unlocked or silently replaced on timeout.

An initial new-flags-OFF production snapshot may legitimately remain format9.
Use its content-derived format; never relabel it10 or manufacture a live order
to force coverage. Actual synthetic format10 encrypted restore proof complements
the real current encrypted snapshot. Active-state recovery still omits ordinary
pending orders and full history; compatible version support does not expand
that coverage or repair older opening-ledger gaps.

Required release sequence
-------------------------

1. Freeze and independently review the final PR source, regression, PostgreSQL,
   frontend and actual binary proof. The normal deployer certificate/forward,
   pre-writer failure and post-writer rollback branches need their own isolated
   proof, not only the sixteen trading/recovery phases.
2. Under the reviewed serialized operator procedure, observe an idle deploy
   service and temporarily quiesce only its timer before merging. Existing
   financial workers and continuous monitors keep running. Do not alter the
   separate Codex team schedule, a valid backup writer or an unrelated timer.
3. Merge through the approved repository process. The final main SHA receives
   its own exact CI/Readiness and actual image proof. Retain both tested image
   archives: each at most250MiB, combined at most500MiB, CI retention one day.
   Keep a verified private copy. A PR-head archive is not silently substituted
   for a later final-merge build.
4. Transfer/hash/stage the exact final binaries and confirm their availability.
   Existing target files/pins require strict conflict checks, not force.
5. Using the existing durable emergency control, pause new and pending entries
   with a frozen revision. Preserve exits and open positions. Verify a fresh
   real encrypted backup in RAM and off-server delivery. Then load/prove the
   immutable target source/config/platform identities and the sixteen isolated
   lifecycle/format10 restore phases with no Production DB, provider, model or
   Telegram test calls, and create the exact protected final-candidate certificate.
   Its selection authority is short-lived;
   already selected rollback uses the vetted journal, not a newly substituted
   or expired mutable certificate.
6. Install only the exact reviewed final-source release helpers under the same
   deployment lock, verify their ownership/hashes, then restore the prior timer
   state. Normal exact-main gates, backup coordination and writer replacement
   remain responsible for deployment. No parallel operator/deployer is allowed.
7. Verify every actual role/image/source, committed markers, monitor, retained
   accounting/holds/duplicates, rollback availability and encrypted backup. Only
   after successful Candidate release and checks may the authorized operator
   explicitly restore the previously running entry-control state. Rollback never
   performs that resume. Full-bar resume eligibility prevents retroactive fills.

Evidence limits
---------------

Synthetic candle/model doubles, disposable PostgreSQL and actual Docker images
prove engineering behavior, not naturally occurring entries, live data coverage,
AI decision quality, calibration, win rate or profitability. A pending order is
not a position. Missing evidence remains NOT_VERIFIED; natural entry/exit evidence
is not created by this release process.
