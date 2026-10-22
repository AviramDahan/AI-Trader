Deployment latency without weaker release gates
==============================================

The 22 October 2026 PR95 release is a dated example, not a promised duration:
manual preparation/approval bookkeeping began04:19:38UTC, merge04:29:19,
whole main Readiness04:44:35, canonical controller04:46:48,
COMPLETE05:05:12 and private final bookkeeping05:13:12.
The actual server operation was18m24s, not the whole53m34s human-facing interval.
Its predeploy backup took8m06s; the new-source snapshot capture-to-completion
interval was8m13s (not its full process lifetime). Both backups remain required.
The data does not establish which internal backup stage dominates.

Safe changes
------------

* Run the PG-backed backend/scanner regression independently of lifecycle/restore
  tests, retaining the same PostgreSQL17 service, environment, client and age.
* Partition the fully collected PG suite between two independent CI runners and
  databases. Shared-database pytest-xdist is deliberately not used: lifecycle
  tests exercise real database-wide advisory locks.
* Collect the original whole PG directory in each runner before selecting its
  assigned files' actual parametrized node IDs. Reject unknown files, duplicate
  node IDs, overlapping file assignments and empty collected shards. Emit total
  node count, both shard counts and the complete collection's SHA256. No test is
  removed from the combined gate. Either shard failing fails whole Readiness;
  fail-fastfalse preserves evidence from its peer.
* Avoid decoding non-secret environment values for every archived SEC row and
  decode row text once. Secret-name matching remains equivalent and case
  sensitive; secret values are still read live for EACH row. There is no cached
  secret list that could miss a change between rows. Exact row bytes, chunk
  hashes/reuse, encryption, formats, retention and restore contracts are unchanged.

The paired local synthetic validator benchmark (3rounds,10000rows/round,
150additional public environment values) measured median1.7219724s before versus
0.7739597s after, about2.22x. This is not a whole-backup or Production speedup.
The removed serial regression took209.60s in PR95; sharding can further reduce
the639.12s lifecycle critical path, depending on runner speed and shard balance.
Actual CI duration and matching node manifests must be checked, not inferred.

Release invariants and operator handoff
--------------------------------------

The exact merged-main CI and WHOLE Readiness conclusion remain mandatory. The
five-minute existing timer, serialization/idempotency, actual old/new binary
capability checks, fresh same-attempt encrypted predeploy proof, idle backup
drain, all-five-role readiness, exact image/source markers and new-source backup
remain unchanged. No shortening a timeout, killing a valid backup, force-unlock,
old-source backup reuse, DB rewind or skipping a gate is a speed improvement.

Reuse already frozen source/independent-QA evidence by its exact source/tree and
receipt hashes; re-review changed code or invalidated proof, not unchanged source
from scratch. Run independent final checks against the single frozen set of
actual post-release observations. Parallelize independent read-only observations,
retain their real individual clocks, and never refresh timestamps without an
observation. Do not add another deployment, scanner or schedule to save waiting.

This work prepares the next release process only. It does not merge/deploy this
new branch or alter running services/flags. A scoped release still needs the
human's explicit approval after the actual checks and changes are explained.
