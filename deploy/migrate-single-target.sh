#!/usr/bin/env bash
# Explicit 005 -> 006, or guarded resume on 006. Normal schema guard stays intact.
# Install/run only after separate operator approval; never invoked by pull gate.
set -Eeuo pipefail
umask 077
sha=${1:-}
expected_old=${3:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ && "$expected_old" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 64
case "${2:-}" in
  --approved-schema-5-to-6) expected_schema=5 ;;
  --approved-resume-schema-6) expected_schema=6 ;;
  *) exit 64 ;;
esac
root=/opt/ai-trader-staging
exec 9>/run/lock/ai-trader-deploy.lock
flock -n 9 || exit 75
cd "$root"
export PUBLIC_API_HOST=2-28-100-77.sslip.io
dc() { docker compose -f "$root/deploy/compose.yml" --profile backups "$@"; }
[[ $(git ls-remote https://github.com/AviramDahan/AI-Trader.git refs/heads/main | cut -f1) == "$sha" ]] || exit 65
curl -fsS "https://api.github.com/repos/AviramDahan/AI-Trader/actions/runs?head_sha=$sha&branch=main&event=push&per_page=100" |
 python3 -c 'import json,sys; selected={}
for r in json.load(sys.stdin)["workflow_runs"]:
 if r["head_sha"]==sys.argv[1] and r["head_branch"]=="main" and r["event"]=="push" and r["head_repository"]["full_name"]=="AviramDahan/AI-Trader":selected.setdefault(r["name"],r["conclusion"])
assert all(selected.get(n)=="success" for n in ("CI","Cloud readiness (no deployment)"))' "$sha"
old=$(docker inspect --format '{{.Image}}' ai-trader-cloud-api-1)
[[ "$old" == "$expected_old" ]] || exit 66
docker image inspect "$old" >/dev/null
for role in api scanner monitor telegram backup; do
  [[ $(docker inspect --format '{{.Image}}' "ai-trader-cloud-$role-1") == "$old" ]] || exit 66
done
old_sha=$(docker exec ai-trader-cloud-api-1 python -c 'import os; print(os.environ["BUILD_SHA"])')
[[ "$old_sha" =~ ^[0-9a-f]{40}$ ]] || exit 66
docker exec ai-trader-cloud-api-1 python -c 'import sys; from single_target_release import assert_bridge; assert_bridge(int(sys.argv[1]))' "$expected_schema"
work=$(mktemp -d /opt/ai-trader-migration006.XXXXXXXX)
curl -fsSL "https://github.com/AviramDahan/AI-Trader/archive/$sha.tar.gz" -o "$work/source.tar.gz"
mkdir "$work/source"
tar xzf "$work/source.tar.gz" --strip-components=1 -C "$work/source"
[[ $(sed -n 's/^SCHEMA_VERSION *= *\([0-9]*\).*/\1/p' "$work/source/service/server/cloud_runtime.py") == 6 ]] || exit 66
docker build --build-arg BUILD_SHA="$sha" --label org.opencontainers.image.revision="$sha" -t "ai-trader:$sha" "$work/source"
new=$(docker image inspect --format '{{.Id}}' "ai-trader:$sha")
# Candidate must initially run with creation disabled under the REAL compose env.
APP_IMAGE="$new" dc run --rm -T --no-deps --entrypoint python api -c 'from single_target_release import assert_creation_disabled; assert_creation_disabled()'
dc run --rm -T --no-deps backup --once --predeploy
# Recheck after the build/backup, before stopping services. The same shared lock
# excludes the normal deploy/pull gate for the entire transition and rollback.
[[ $(git ls-remote https://github.com/AviramDahan/AI-Trader.git refs/heads/main | cut -f1) == "$sha" ]] || exit 65
cp deploy/compose.yml "$work/previous-compose.yml"
docker tag "$old" "ai-trader:single-target-rollback-$old_sha"
printf '%s\n%s\n' "$old_sha" "$old" > deploy/single-target-compatible-image
writers_stopped=0
rollback() {
  code=$?
  trap - ERR
  if [[ "$writers_stopped" == 1 ]]; then
    dc stop scanner telegram monitor backup api || { echo 'STOP FAILED; operator intervention required'; exit 70; }
    cp "$work/previous-compose.yml" deploy/compose.yml
    export APP_IMAGE="$old"
    # Bridge accepts actual schema 5 OR 6, with complete V2 readers. No rewind.
    dc up -d --no-deps --no-build --wait --wait-timeout 180 api monitor scanner telegram backup || { echo 'ROLLBACK FAILED'; exit 70; }
    docker tag "$old" ai-trader:staging
    docker exec ai-trader-cloud-api-1 python -c 'from pathlib import Path; import sys; Path("/app/.runtime/deployed-release").write_text(sys.argv[1])' "$old_sha"
  fi
  echo 'MIGRATION 006 RELEASE FAILED; compatible image restored, database never rewound'
  exit "$code"
}
trap rollback ERR
writers_stopped=1
dc stop scanner telegram monitor backup api
cp "$work/source/deploy/compose.yml" deploy/compose.yml
export APP_IMAGE="$new"
# Verify the rollback IMAGE itself against the current database after quiescing
# writers (not merely a running container or MAX(version)). No init or DDL.
APP_IMAGE="$old" dc run --rm -T --no-deps --entrypoint python api -c 'import sys; from single_target_release import assert_bridge; assert_bridge(int(sys.argv[1]))' "$expected_schema"
dc run --rm -T --no-deps --entrypoint python api -c 'from single_target_release import assert_creation_disabled; assert_creation_disabled()'
if [[ "$expected_schema" == 5 ]]; then
  dc run --rm -T --no-deps migrate
fi
# Resume never invokes migrate: not even an idempotent DDL/history writer.
dc run --rm -T --no-deps --entrypoint python api -c 'from single_target_release import assert_transition_schema; assert_transition_schema(6)'
# Failure even here is recoverable on the bridge image.
dc run --rm -T --no-deps --entrypoint python api -c 'from cloud_runtime import assert_schema; assert_schema()'
dc up -d --no-deps --no-build --wait --wait-timeout 180 api monitor
dc up -d --no-deps --no-build --wait --wait-timeout 180 scanner telegram backup
curl -fsS "https://$PUBLIC_API_HOST/health" >/dev/null
dc run --rm -T --no-deps backup --once --predeploy
docker tag "$new" ai-trader:staging
docker exec ai-trader-cloud-api-1 python -c 'from pathlib import Path; import sys; Path("/app/.runtime/deployed-release").write_text(sys.argv[1])' "$sha"
printf '%s\n%s\n%s\n' "$sha" "$new" "$old" > deploy/last-release.next
mv deploy/last-release.next deploy/last-release
trap - ERR
echo "MIGRATION 006 PASS commit=$sha image=$new rollback=$old creation=disabled source_schema=$expected_schema"
