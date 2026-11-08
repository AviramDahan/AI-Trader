Verified backup startup checkpoint
==================================

The normal release still runs one complete managed predeploy backup and waits
for its verified off-server push before replacing any application writers.
CI, Cloud Readiness, the deployment lock, real image compatibility checks,
migrations and all five role checks remain required. This is an optimization of
backup daemon startup, not an alternative release process or a backup bypass.

Why this reduces deployment time
--------------------------------

During the manually observed PR123 release on 8 November 2026, the managed
predeploy job ran from 13:14:28 to 13:25:46 UTC. Starting the replacement backup
daemon then exported the same history again. Restoring the source configuration
recreated that daemon and repeated the export a third time. Each copy took
roughly twelve minutes with the existing resource limits. The long observer
timeout is a ceiling, not a mandatory sleep.

The new managed backup writes a versioned startup checkpoint alongside its
existing atomic status only after encryption, archive delivery, remote commit
verification and existing retention work finish. The replacement daemon may
reuse it once at startup when all of these conditions hold:

* The request is a completed managed predeploy from the exact running BUILD_SHA.
* The original capture is at most 30 minutes old, timezone aware, and is ordered
  between request start and finish, with no future timestamps.
* The saved runtime policy digest equals the current recovery runtime policy.
* The normal backup lock is acquired; another valid backup is never stopped.
* The private repository check succeeds and its configured origin is unchanged.
* Local HEAD and the remote main ref both equal the verified checkpoint commit.
* The bounded encrypted predeploy blob at that commit has the recorded size,
  age-encrypted header and SHA256. No server decryption key is introduced.

Health is seeded with the original capture time, not the restart time. Status,
snapshot contents, financial state and success timestamps are not rewritten.
The next full backup runs at the existing next UTC hourly boundary, or earlier
if necessary to stay within one hour of the original capture. Ordinary hourly
scheduling is unchanged after that first backup.

Missing, old, malformed, policy-mismatched or unverifiable checkpoints use the
existing complete startup backup. An interrupted first backup therefore never
grants health. Legacy backup images ignore the optional metadata; a rollback
continues its original full backup behavior. ``--once``, ``--predeploy`` and
managed request invocations never take the reuse path.

Evidence and limits
-------------------

Tests use synthetic ciphertext and mocked Git/HTTP/exports. They do not prove
faster real server execution or a new restore. The first release of this code
must still pass the existing complete release gates. Later daemon startups
should avoid up to two redundant exports within the freshness window; actual
savings must be measured from deployment timestamps. A slow required backup,
busy lock, incompatible image or failed check can still delay a release.

No safety timeout, CPU/RAM budget, cadence, CI gate, encryption/retention rule,
financial contract or rollback selection is relaxed by this change.
