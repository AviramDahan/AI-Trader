#!/usr/bin/env bash
# Explicit additive 004 -> 005 migration and publication cutover, never DB rewind.
set -Eeuo pipefail
umask 077
sha=${1:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ && "${2:-}" == --approved-schema-4-to-5 ]] || exit 64
root=/opt/ai-trader-staging
exec 9>/run/lock/ai-trader-deploy.lock
flock -n 9 || exit 75
cd "$root"
export PUBLIC_API_HOST=2-28-100-77.sslip.io
dc() { docker compose -f "$root/deploy/compose.yml" --profile backups "$@"; }
[[ $(git ls-remote https://github.com/AviramDahan/AI-Trader.git refs/heads/main | cut -f1) == "$sha" ]] || exit 65
curl -fsS "https://api.github.com/repos/AviramDahan/AI-Trader/actions/runs?head_sha=$sha&per_page=100" |
 python3 -c 'import json,sys; runs=json.load(sys.stdin)["workflow_runs"]; assert all(any(r["name"]==name and r["head_sha"]==sys.argv[1] and r["conclusion"]=="success" for r in runs) for name in ("CI","Cloud readiness (no deployment)"))' "$sha"
[[ $(docker exec ai-trader-cloud-api-1 python -c 'from cloud_runtime import SCHEMA_VERSION; print(SCHEMA_VERSION)') == 4 ]] || exit 66
work=$(mktemp -d /opt/ai-trader-migration005.XXXXXXXX)
curl -fsSL "https://github.com/AviramDahan/AI-Trader/archive/$sha.tar.gz" -o "$work/source.tar.gz"
mkdir "$work/source"
tar xzf "$work/source.tar.gz" --strip-components=1 -C "$work/source"
[[ $(sed -n 's/^SCHEMA_VERSION *= *\([0-9]*\).*/\1/p' "$work/source/service/server/cloud_runtime.py") == 5 ]] || exit 66
docker build --build-arg BUILD_SHA="$sha" --label org.opencontainers.image.revision="$sha" -t "ai-trader:$sha" "$work/source"
new=$(docker image inspect --format '{{.Id}}' "ai-trader:$sha")
old=$(docker inspect --format '{{.Image}}' ai-trader-cloud-api-1)
dc run --rm -T --no-deps backup --once --predeploy
cp deploy/compose.yml "$work/previous-compose.yml"
cp deploy/runtime.env "$work/previous-runtime.env"
printf '%s\n' "$old" > "$work/previous-image"
export APP_IMAGE="$new"
migrated=false
rollback() {
  trap - ERR
  dc stop scanner telegram
  if [[ "$migrated" == true ]]; then
    # Phase 1 compatibility path in the same tested schema-5 image. Never run
    # schema-4 code blindly against schema 5 or roll an active portfolio back.
    dc run --rm -T --no-deps --entrypoint python api -m news_events.cutover phase1 --reason release_readiness_failed
    dc up -d --no-deps --no-build --wait --wait-timeout 180 api monitor scanner telegram backup
    echo 'NEWS CUTOVER FAILED: Phase 1 restored on schema 5; no DB rewind.'
  else
    cp "$work/previous-compose.yml" deploy/compose.yml
    cp "$work/previous-runtime.env" deploy/runtime.env
    export APP_IMAGE="$old"
    dc up -d --no-deps --no-build --wait --wait-timeout 180 api monitor scanner telegram backup
    echo 'Migration not committed: previous image restored.'
  fi
  exit 1
}
trap rollback ERR
dc stop scanner telegram monitor backup api
cp "$work/source/deploy/compose.yml" deploy/compose.yml
python3 - <<'PY'
from pathlib import Path
p=Path('deploy/runtime.env')
lines=[s for s in p.read_text().splitlines() if not s.startswith('NEWS_EVENTS_RUNTIME=')]
p.write_text('\n'.join(lines+['NEWS_EVENTS_RUNTIME=true'])+'\n');p.chmod(0o600)
PY
dc run --rm -T --no-deps migrate
migrated=true
dc run --rm -T --no-deps --entrypoint python api -m news_events.integrity > "$work/before-cutover.json"
dc up -d --no-deps --no-build --wait --wait-timeout 180 api monitor
# Both publishers are stopped; the persistent switch/cursors commit atomically.
dc run --rm -T --no-deps --entrypoint python api -m news_events.cutover canonical
dc up -d --no-deps --no-build --wait --wait-timeout 180 scanner telegram backup
dc run --rm -T --no-deps --entrypoint python api -m news_events.integrity > "$work/after-cutover.json"
python3 - "$work" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);a=json.loads((p/'before-cutover.json').read_text());b=json.loads((p/'after-cutover.json').read_text())
assert b['schema']==5 and b['control']['mode']=='canonical' and b['broken_projection']==0 and b['legacy_pending']==0
# Execute this upgrade outside market hours; accounting/fills must not drift.
for key in ('scanner_trades','scanner_fills','scanner_accounts','scanner_orders','positions','models'):
    assert a[key]==b[key], 'release_integrity_mismatch:'+key
PY
curl -fsS "https://$PUBLIC_API_HOST/health" >/dev/null
docker tag "$new" ai-trader:staging
docker exec ai-trader-cloud-api-1 python -c 'from pathlib import Path; import sys; Path("/app/.runtime/deployed-release").write_text(sys.argv[1])' "$sha"
printf '%s\n%s\n%s\n' "$sha" "$new" "$old" > deploy/last-release.next
mv deploy/last-release.next deploy/last-release
trap - ERR
echo "MIGRATION 005 / CANONICAL CUTOVER PASS commit=$sha audit=$work"
