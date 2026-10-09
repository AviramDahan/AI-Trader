#!/usr/bin/env bash
# Operator-approved 006 -> 007 transition, or a guarded retry on complete 007.
# Never invoked by the normal deploy/pull gate; that schema guard stays intact.
set -Eeuo pipefail
umask 077
sha=${1:-}
mode=${2:-}
expected_old=${3:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ && "$expected_old" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 64
case "$mode" in
  --approved-schema-6-to-7) expected_schema=6 ;;
  --approved-resume-schema-7) expected_schema=7 ;;
  *) exit 64 ;;
esac
root=/opt/ai-trader-staging
exec 9>/run/lock/ai-trader-deploy.lock
flock -n 9 || exit 75
cd "$root"
export PUBLIC_API_HOST=2-28-100-77.sslip.io
dc() { docker compose -f "$root/deploy/compose.yml" --profile backups "$@"; }
repo=https://github.com/AviramDahan/AI-Trader
[[ $(git ls-remote "$repo.git" refs/heads/main | cut -f1) == "$sha" ]] || exit 65
curl -fsS "https://api.github.com/repos/AviramDahan/AI-Trader/actions/runs?head_sha=$sha&branch=main&event=push&per_page=100" |
 python3 -c 'import json,sys; found={}
for run in json.load(sys.stdin)["workflow_runs"]:
 if run["head_sha"]==sys.argv[1] and run["head_branch"]=="main" and run["event"]=="push" and run["head_repository"]["full_name"]=="AviramDahan/AI-Trader":
  found.setdefault(run["name"],run["conclusion"])
assert all(found.get(name)=="success" for name in ("CI","Cloud readiness (no deployment)"))' "$sha"
old=$(docker inspect --format '{{.Image}}' ai-trader-cloud-api-1)
[[ "$old" == "$expected_old" ]] || exit 66
docker image inspect "$old" >/dev/null
for role in api scanner monitor telegram backup; do
  [[ $(docker inspect --format '{{.Image}}' "ai-trader-cloud-$role-1") == "$old" ]] || exit 66
done
old_sha=$(docker exec ai-trader-cloud-api-1 python -c 'import os; print(os.environ["BUILD_SHA"])')
[[ "$old_sha" =~ ^[0-9a-f]{40}$ ]] || exit 66
# This verifies the actual DB in a READ ONLY transaction and refuses an older
# schema-6-only image or a partial 007. No init, DDL or worker is started.
preflight='import sys
from cloud_runtime import SEC_SCHEMA7_ROLLBACK_CAPABILITY, assert_schema
from database import get_db_connection
assert SEC_SCHEMA7_ROLLBACK_CAPABILITY == "sec-schema7-readers-no-producers"
assert_schema()
with get_db_connection() as c:
 c.execute("SET TRANSACTION READ ONLY")
 actual=c.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()["version"]
 assert actual==int(sys.argv[1]), ("unexpected_schema",actual)'
docker exec ai-trader-cloud-api-1 python -c "$preflight" "$expected_schema"
work=$(mktemp -d /opt/ai-trader-sec007.XXXXXXXX)
curl -fsSL "$repo/archive/$sha.tar.gz" -o "$work/source.tar.gz"
mkdir "$work/source"
tar xzf "$work/source.tar.gz" --strip-components=1 -C "$work/source"
[[ $(sed -n 's/^SCHEMA_VERSION *= *\([0-9]*\).*/\1/p' "$work/source/service/server/cloud_runtime.py") == 7 ]] || exit 66
docker build --build-arg BUILD_SHA="$sha" --label org.opencontainers.image.revision="$sha" -t "ai-trader:$sha" "$work/source"
new=$(docker image inspect --format '{{.Id}}' "ai-trader:$sha")
disabled='from sec_intelligence import mode
assert mode()=="off", "sec_production_must_remain_off_during_transition"'
APP_IMAGE="$new" dc run --rm -T --no-deps --entrypoint python api -c "$disabled"
dc run --rm -T --no-deps backup --once --predeploy
[[ $(git ls-remote "$repo.git" refs/heads/main | cut -f1) == "$sha" ]] || exit 65
cp deploy/compose.yml "$work/previous-compose.yml"
docker tag "$old" "ai-trader:sec-schema7-rollback-$old_sha"
printf '%s\n%s\n' "$old_sha" "$old" > deploy/sec-schema7-compatible-image
writers_stopped=0
rollback() {
  code=$?
  trap - ERR
  if [[ "$writers_stopped" == 1 ]]; then
    dc stop scanner telegram monitor backup api || { echo 'STOP FAILED'; exit 70; }
    cp "$work/previous-compose.yml" deploy/compose.yml
    export APP_IMAGE="$old"
    dc up -d --no-deps --no-build --wait --wait-timeout 180 api monitor scanner telegram backup || { echo 'ROLLBACK FAILED'; exit 70; }
    docker tag "$old" ai-trader:staging
    docker exec ai-trader-cloud-api-1 python -c 'from pathlib import Path; import sys; Path("/app/.runtime/deployed-release").write_text(sys.argv[1])' "$old_sha"
  fi
  echo 'SEC 007 RELEASE FAILED; compatible bridge restored; database not rewound'
  exit "$code"
}
trap rollback ERR
writers_stopped=1
dc stop scanner telegram monitor backup api
cp "$work/source/deploy/compose.yml" deploy/compose.yml
export APP_IMAGE="$new"
# Recheck the rollback IMAGE against the stopped-writer database.
APP_IMAGE="$old" dc run --rm -T --no-deps --entrypoint python api -c "$preflight" "$expected_schema"
dc run --rm -T --no-deps --entrypoint python api -c "$disabled"
if [[ "$expected_schema" == 6 ]]; then
  dc run --rm -T --no-deps migrate
fi
# Resume on 007 never invokes migrate, even if migration DDL is idempotent.
APP_IMAGE="$old" dc run --rm -T --no-deps --entrypoint python api -c "$preflight" 7
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
echo "SEC 007 PASS commit=$sha image=$new rollback=$old mode=$mode"
