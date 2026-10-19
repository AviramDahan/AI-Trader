# Backend release gate

`hetzner-deploy.yml` runs only after the main-branch Cloud Readiness workflow
succeeds and separately verifies CI success for that exact commit. A root-owned
systemd timer checks main and both successful workflows every five minutes via
outbound HTTPS. It needs no GitHub credential and no public SSH access. GitHub
then checks HTTPS build_sha and the all-role deployed_sha readiness marker.
The source/image is built from the public commit archive, never from the live
directory containing secrets. Server source scripts are installed by an operator,
not replaced by a repository release. A failed commit is latched in failed-release
to prevent deployment loops; an operator may clear the latch after diagnosis, or
push a corrected commit. Unauthenticated GitHub API limits defer a poll safely.

The read-only GitHub observer has a 112-minute monotonic polling ceiling: five
minutes for the pull timer, the reviewed unit's 85-minute start ceiling,
20-minute termination/rollback backstop, and two minutes of margin. This is a
safety ceiling, not the expected deployment duration. The script separately
bounds forward work to 3600 seconds and reserves 1200 seconds for rollback.
Each request uses at most ten seconds (or the remaining window) as its socket
timeout and reads at most 16 KiB plus one overflow byte.
Only HTTP 200 with an object containing both exact commit fields before the deadline
passes. This is not a hard DNS/TLS or whole-request deadline; the 113-minute
observer step is the backstop. The observer step has 113 minutes, the exact-CI
step has 11 minutes, and the job has 125 minutes.
An observation failure never initiates a deployment or changes server gates.

The server verifies the current main SHA, obtains a deployment lock, builds an image
tagged with the full commit and runs Compose using its immutable image ID. A
Recovery-State predeploy backup is required. Writers stop before migration; API,
monitor, scanner, Telegram and backup start sequentially with readiness gates.
No old/new writers overlap. This is a brief stop/start deployment, not zero downtime.

On readiness failure the previous Compose file/image is restored, preserving the
current database (never rewind fills). Automatic schema-version changes are blocked
until an operator has reviewed compatibility and rollback; same-schema migrations
run idempotently on every deployment. A failed rollback requires operator recovery.
Before any backup or writer replacement, network-isolated probes of the actual
old and candidate images must prove that the old binary supports every advertised
candidate snapshot format and the same audit/execution/emergency versions.
Unknown/older readers abort rather than becoming an automatic rollback target.
In this repair the actual prior runtime is733 (formats1..9), **not** the stale
last-release1d61 marker. The separate Bridge16 test intentionally keeps1d61 as
the unsafe-reader fixture; that is not authorization to roll back to it.
The last release records commit/new/previous image IDs. Keep previous images and
source temporarily; review disk use before pruning. CI and host locks prevent
concurrent releases. Production remains provisional until live-market validation.

## Versioned deployment and backup coordination

Install the reviewed `hetzner-pull.py`, `hetzner-deploy.sh`,
`docker_image_identity.py` (beside both helpers in `/usr/local/sbin`) and
`systemd/ai-trader-deploy.service` together through the protected operator path.
The timer remains five minutes (`systemd/ai-trader-deploy.timer`). A repository
merge does not install root-owned helpers or units. During a controlled repair,
quiesce only that existing deployment timer after verifying no running deployment;
preserve its original enabled/active state and restore it after verification.
Never edit a Codex schedule, stop application monitoring, or clear a failure
latch simply to make a release proceed.

The actual 19 October failure was a 1200-second unit deadline while two cold
encrypted backups each took approximately eleven minutes, followed by a genuine
backup-lock collision on a timer retry. Increasing health grace alone cannot
solve the whole-operation deadline. Current bounds are:

| Operation | Bounded seconds |
| --- | ---: |
| Forward deployment | 3600 |
| Separate rollback reserve | 1200 |
| One managed predeploy observation | 1800 |
| Waiting for the shared backup lock | 900 |
| Cold backup health/start period | 1200 |
| Unit start / stop backstops | 5100 / 1200 |

`KillMode=mixed` lets the pull process forward TERM to deployment clients and
record a truthful attempt. Detached backup containers belong to Docker, not the
observer's process group. A client deadline or cancellation never kills/removes
a valid backup. If rollback cannot safely drain the backup within its reserve,
it records `ROLLBACK_DEFERRED`, leaves that backup running, and requires an
operator. No readiness or encrypted off-server proof is waived.

The pull process owns the shared deployment flock and passes its descriptor to
the shell. Direct shell invocation locks the same file. Every privileged helper
validates the inherited descriptor's device/inode and obtains the real flock;
an environment boolean cannot bypass serialization. Lock files are never
unlinked, replaced, or forcibly unlocked.

`deployment-attempt.json` is an atomic, fsynced, root-private journal, bound to
the exact SHA, immutable image IDs, attempt ID and source work directory.
`COMMITTING` is not success: all five actual roles must be healthy on the exact
image and build before atomic deployed/last-release markers are committed and
read back. SIGKILL leaves an incomplete attempt requiring review. Only explicit
pre-writer `DEFERRED_PREDEPLOY`/`DEFERRED_DRAIN` states can be rejoined, after
revalidating that the old runtime is unchanged and healthy. A failed-latch
no-op is reported `BLOCKED_FAILED_RELEASE`, never `VERIFIED_COMPLETE`.

Exit75 is temporary contention/pending observation and never creates a failed
source latch. Genuine nonzero deployment failures remain latched per SHA.
Historical latches for other SHAs are preserved, not overwritten or blindly
cleared. A repaired release's marker is never handwritten by an operator.

### Reusable managed backup

The root-only controller can also observe the paused format9 backup required
by a separately approved entry activation:

```sh
/usr/local/sbin/ai-trader-pull --backup-only \
  --sha <exact-build-sha> --image <actual-full-image-id> \
  --request-id <stable-32-hex-id> --wait-seconds 30
```

The activation wrapper must enforce its own fresh pause revision, compatibility,
configuration and source guards before and after calling this generic operation.
It must not hold an independent deployment flock; the controller owns it (a
properly validated inherited descriptor is also supported). Do not use older
one-off wrappers that remove a still-running container on timeout.

The immutable request is retained in `backup-requests/<id>.json`. A deterministic
named container uses the exact source image, command, request labels, service
mounts/networks and a `restart: "no"` override **before** creation. It is not
`--rm`. A pending-request index prevents a different request from queuing a
duplicate snapshot. Rejoining validates the saved full container ID; a missing
or altered existing job is not silently recreated. Only a terminated lock-busy
job (exit75, no backup work) may be restarted by its same request.

Exit75 returns canonical pending/busy metadata while a valid backup continues;
use the same request ID on a later bounded call. Exit0 requires the actual
container to have exited successfully and its correlated, fresh proof to name
the exact request/source, snapshot, recovery format and verified remote Git
commit. The previous successful status is not overwritten by a lock contender.
No success comes from a stale `/tmp/backup-ok` file alone. Independent real age
decryption and snapshot validation in memory remain a separate activation gate.

Before stopping either hourly backup version, the controller resolves the exact
Docker volume and holds its real `backup.lock` across the stop. Thus it stops
only an idle service, without the check/release/stop race. It never kills a
valid running backup to speed deployment or rollback. Existing trades, holds,
entry contracts, TP/SL and trading/AI settings are outside this repair.

### OCI and legacy runtime image identity

Docker's image index, selected platform manifest and config digest are distinct.
On19October the running containers retained an uninspectable legacy handle,
while their authoritative `ImageManifestDescriptor` still exactly matched the
available, hash-verified733 linux/amd64 image. Equal source labels or a mutable
tag alone do not establish that relationship.

The shared identity module freezes a version1 record with `kind`, immutable
`runnable_ref`, `platform`, `platform_manifest`, `config_digest`, `build_sha`
and `user`. For OCI images it checks the exact raw-byte hash graph
index→selected platform→config, including descriptor sizes and platform/source/
nonroot user. A bounded export is read without extracting image files, with a
120-second export-client watchdog, at most256 members/2GiB declared content and
512KiB per retained metadata blob. Only the export client may be terminated;
no backup job is involved. Protected root700/root600 proof caching avoids
re-exporting layers on every health poll. Subsequent immutable platform
inspection and runtime descriptor/source/user must still match exactly.

Only when a raw legacy handle is unavailable may `ai-trader:<actual BUILD_SHA>`
discover an immutable ref; its proved platform manifest must exactly match the
running container. Thereafter operations use the pinned immutable ref, never
follow the alias. Missing/unknown/ambiguous platform metadata fails closed.
Classic Docker images without OCI descriptors retain strict raw image/config
digest equality. Rollback probes, owned backup jobs, all-role readiness and
final release commit all use this one model. No index/config digest is renamed
or equated to another digest.

OCI operation requires
[`image inspect --platform` (API1.49+)](https://docs.docker.com/reference/cli/docker/image/inspect/).
The bounded [`image save`](https://docs.docker.com/reference/cli/docker/image/save/)
stream deliberately retains the complete immutable graph: a platform-filtered
export may rewrite its outer index and cannot prove the original index digest.
Selection still checks exact linux/amd64 membership, not a different platform.
Unsupported engines fail closed rather than using an alias fallback.
The installed controller opens the protected module without following symlinks,
validates its file descriptor, and compiles that single bounded raw-byte read.
It never executes timestamp/size-matched cached bytecode instead of reviewed
source.

The shell now records a genuine rollback-capability failure as `FAILED` before
returning67; a direct `exit67` previously bypassed the ERR trap and could leave
`PREDEPLOY_PENDING`. Existing incomplete attempts are **not** automatically
closed. After operator review only, under the same deployment lock:

```sh
/usr/local/sbin/ai-trader-pull --review-close-prewriter \
  --sha <exact-failed-source> --request-id <exact-attempt32hex> \
  --image <proved-immutable-old-runtime-ref>
```

This refuses any non-prewriter phase, previous-compose mutation evidence,
managed request/job or unresolved active backup, or changed/unhealthy runtime.
The work directory must be a root-owned, non-symlink, exact0700
`/opt/ai-trader-release.*` immediate child. Existing original archives must be
root-private regular files on both first close and rejoin, even if their bytes
already match the current journal.
It preserves the exact original journal in root-private `reviewed-attempts`,
records its hash and explicit review reason, then marks only that attempt
`FAILED`. A repeated exact call can acknowledge the same reviewed result after
revalidating archive/hash/runtime/job guards. Arbitrary failed attempts cannot
be adopted. Historical per-SHA/legacy failure latches are never cleared or
rewritten, and no deployed/last-release success marker is manufactured.
