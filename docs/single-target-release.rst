SINGLE V2 release contract (prepared, NOT executed)
==================================================

Why a prerequisite PR
---------------------
Main requires schema 5 exactly. Failure after committing 006 cannot return to
it even with zero V2 rows. The prerequisite bridge contains the complete V2
reader/executor/presentation/format-3 recovery capability, but CREATION_CAPABLE
is False. It cannot originate V2 even if the environment flag is set. Normal
cloud migration targets 5; readiness accepts actual schema 5 OR 6 and checks
006 columns/nullability on 6. SCHEMA_VERSION denotes normal migration/floor,
not a claim about the actual DB. Migration history is never relabelled.

PR #27 stacks on the bridge. Its activation delta changes CREATION_CAPABLE=True,
SCHEMA_VERSION=6 and SUPPORTED_SCHEMAS=(6,). Creation still defaults OFF until
the operator explicitly enables STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED.
The researched target policy is unchanged.

Activation is not binary rollback
---------------------------------
Disabling the flag stops new V2 plans and record_signal admission (including an
in-flight decision). It never cancels/converts a saved order, frees holds, moves
levels or stops V2 entries/exits. New V1 plans remain possible. The bridge
handles single targets, NULL unused slots, plan_json, Legacy and held orders.
Validate formats 1/2/3; restore 2/3 with hold coverage, and format3 only to schema6.
No format retagging, downgrade migration, DB rewind or automatic hold release.

Exact future release order (requires release approval)
-----------------------------------------------------
1. Merge bridge only; exact main CI/Readiness then existing normal deployment
   (schema5 -> 5), encrypted backup and readiness. Verify every role including
   backup has its actual image, accounts/holds/leases. Preserve full image ID,
   build SHA and tag, no prune. Returning to f837daa is conditional on schema5
   and no V2 state; never after 006.
2. Merge activation PR #27 after approval; require exact main CI/Readiness.
   Normal auto-deploy MUST refuse 5 -> 6: hetzner-deploy.sh is unchanged.
   Operator command, installed through the existing protected release channel:
   deploy/migrate-single-target.sh SHA --approved-schema-5-to-6 BRIDGE_IMAGE_ID
   This narrowly follows the existing numbered migration scripts, sharing the
   release lock/root/compose/build/backup/health mechanism, not an autonomous
   alternative deployment service. It verifies main, latest exact push checks,
   identical all-role bridge images, compatibility capability, actual schema5,
   and candidate creation OFF in the real compose environment. Both images
   exist BEFORE migration. Backup must pass; retain old compose and pinned
   bridge ID; stop writers/API; transactional 006; readiness; start OFF. Failure
   immediately after migration restores the bridge on the CURRENT DB. The pull
   gate shares the lock and cannot invoke this special migration command.
   If 006 committed and deployment failed back to the bridge, use the explicit
   retry command (under the same future release approval):
   deploy/migrate-single-target.sh SHA --approved-resume-schema-6 BRIDGE_IMAGE_ID
   The original mode still requires 5; there is no automatic mode selection.
   Resume verifies the bridge's capability and image availability, exact main
   checks, disabled creation, complete migration history 1..6 with applied_at,
   all six nullable target fields and plan_json TEXT NOT NULL DEFAULT '{}'.
   Catalog/history are read in one REPEATABLE READ, READ ONLY transaction.
   The bridge preflight is re-run from the pinned image after writers stop.
   Both modes require validated/encrypted predeploy backup; resume NEVER calls
   migrate or writes migration history. A second failure returns to that same
   bridge on the current schema6 database. A broken schema is rejected, never
   repaired by this script. The normal deploy schema guard is unchanged.
3. Verify all-role build/deployed SHA, health, leases, accounting/reservation,
   no duplicate fills, encrypted backup coverage and rollback image. Only then
   enable the environment flag under explicit rollout approval. A closed-market
   health check is not live-trading proof.
4. To stop new V2 only: disable flag and approved coordinated scanner restart.
   For binary rollback: select the pinned bridge ID (not f837daa), stop/recreate
   role services with existing compose and validate current-DB state. Preserve
   deploy/single-target-compatible-image and the pinned tag
   ai-trader:single-target-rollback-BUILD_SHA. Normal deploy never prunes images.

Installing/running this script is a FUTURE approved release action. Nothing in
this PR installs it, changes the root-owned normal gate or migrates Production.
Do not assume CI and server builds are byte-identical; record and retain the
actual server image ID/revision/build SHA before activation.

Proof, not a skipped workflow
----------------------------
Single target compatibility images (no deployment) builds baseline f837daa and
exact bridge/activation heads. Internal-only network and synthetic PostgreSQL;
only a probe is mounted, never replacement application modules. Uses real
migrations, role schema/lease checks, engine and recovery; market transport and
decision clock alone are mocked. No providers, paid AI or Telegram delivery.

Sequence: baseline5 V1+Shadow+Legacy -> bridge5 -> baseline rollback check ->
migration6 -> simulated failure -> bridge6 restart BEFORE ANY V2 -> activation ->
V2 position + real missing-bar hold + pending V2 -> disable -> pending V2 fills ->
bridge rollback/restart -> real age export/encrypt/decrypt -> empty schema6
restore -> restart/duplicate-entry block -> V1/Legacy/V2 exits, holds retained ->
activation-image restart. Old binary explicitly refuses schema6. Upload only
phase results/build SHAs/image IDs; no keys, snapshots or plaintext artifacts.
Both final heads require full CI/Readiness and this new image workflow. A skip
of the older Recovery compatibility images workflow is NOT evidence.

The script harness runs the actual Bash file with only three filesystem roots
relocated, strict Docker/Git/HTTP/lock doubles and unmodified Python preflights.
It reproduces the reviewed script's dead end and the normal guard rejection,
then tests 006 -> failed start -> bridge -> failed resume -> bridge -> successful
resume with exactly one migration call. It rejects incomplete schema/history,
unsafe/missing bridge, creation ON, stale SHA, failed checks/backup and a busy
release lock. These are shell control-flow proofs, not real Compose health.
Real PostgreSQL tests independently check every 006 field, ledger and read-only
isolation; the full-image workflow retains the application/age/hold proofs.

Scope of backup remains active positions and recovery_uncertain holds, NOT all
pending orders. The probe fills its extra pending before round-trip. No silent
claim of broader pending-backup coverage or a complete natural trading E2E.
