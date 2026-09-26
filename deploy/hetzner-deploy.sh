#!/usr/bin/env bash
# Installed root-owned. Invoked only through a restricted SSH forced command.
set -Eeuo pipefail
umask 077
sha=${1:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 64
exec 9>/run/lock/ai-trader-deploy.lock
flock -n 9 || exit 75
root=/opt/ai-trader-staging
repo=https://github.com/AviramDahan/AI-Trader
head=$(git ls-remote "$repo.git" refs/heads/main | cut -f1)
[[ "$head" == "$sha" ]] || { echo 'Refusing stale/non-main commit'; exit 65; }
cd "$root"
export PUBLIC_API_HOST=2-28-100-77.sslip.io
dc() { docker compose -f "$root/deploy/compose.yml" --profile backups "$@"; }
old=$(docker inspect --format '{{.Image}}' ai-trader-cloud-api-1)
work=$(mktemp -d /opt/ai-trader-release.XXXXXXXX)
curl --fail --silent --show-error --location "$repo/archive/$sha.tar.gz" -o "$work/source.tar.gz"
mkdir "$work/source"
tar xzf "$work/source.tar.gz" --strip-components=1 -C "$work/source"
# Schema-changing releases require an explicit compatibility/rollback review.
old_schema=$(docker exec ai-trader-cloud-api-1 python -c 'from cloud_runtime import SCHEMA_VERSION; print(SCHEMA_VERSION)')
new_schema=$(sed -n 's/^SCHEMA_VERSION *= *\([0-9]*\).*/\1/p' "$work/source/service/server/cloud_runtime.py")
[[ "$old_schema" == "$new_schema" ]] || { echo 'Schema change requires operator-approved migration'; exit 66; }
docker build --build-arg BUILD_SHA="$sha" --label org.opencontainers.image.revision="$sha" -t "ai-trader:$sha" "$work/source"
new=$(docker image inspect --format '{{.Id}}' "ai-trader:$sha")
dc run --rm -T --no-deps backup --once --predeploy
cp deploy/compose.yml "$work/previous-compose.yml"
writers_stopped=0
rollback() {
  code=$?
  trap - ERR
  if [[ "$writers_stopped" == 1 ]]; then
    dc stop scanner telegram monitor backup || true
    cp "$work/previous-compose.yml" deploy/compose.yml
    export APP_IMAGE="$old"
    dc up -d --no-deps --no-build --wait --wait-timeout 180 api monitor scanner telegram backup || { echo 'ROLLBACK FAILED: manual intervention required'; exit 70; }
    docker tag "$old" ai-trader:staging
  fi
  echo 'DEPLOY FAILED; previous version restored where possible; database never rewound'
  exit "$code"
}
trap rollback ERR
writers_stopped=1
dc stop scanner telegram monitor backup
cp "$work/source/deploy/compose.yml" deploy/compose.yml
export APP_IMAGE="$new"
dc run --rm -T --no-deps migrate
dc up -d --no-deps --no-build --wait --wait-timeout 180 api
dc up -d --no-deps --no-build --wait --wait-timeout 180 monitor
dc up -d --no-deps --no-build --wait --wait-timeout 180 scanner telegram backup
curl --fail --silent --show-error "https://$PUBLIC_API_HOST/health" >/dev/null
docker tag "$new" ai-trader:staging
printf '%s\n%s\n%s\n' "$sha" "$new" "$old" > deploy/last-release
docker exec ai-trader-cloud-api-1 python -c 'from pathlib import Path; import sys; Path("/app/.runtime/deployed-release").write_text(sys.argv[1])' "$sha"
trap - ERR
echo "DEPLOY PASS commit=$sha image=$new"
# Keep the previous image/release for rollback; do not prune active data or images.
