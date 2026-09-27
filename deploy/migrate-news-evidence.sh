#!/usr/bin/env bash
# One-time operator-approved 003 -> 004 release. Automatic deploy guard unchanged.
set -Eeuo pipefail
umask 077
sha=${1:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ && "${2:-}" == --approved-schema-3-to-4 ]] || exit 64
root=/opt/ai-trader-staging
exec 9>/run/lock/ai-trader-deploy.lock
flock -n 9 || exit 75
cd "$root"
export PUBLIC_API_HOST=2-28-100-77.sslip.io
dc() { docker compose -f "$root/deploy/compose.yml" --profile backups "$@"; }
[[ $(git ls-remote https://github.com/AviramDahan/AI-Trader.git refs/heads/main | cut -f1) == "$sha" ]] || exit 65
curl -fsS "https://api.github.com/repos/AviramDahan/AI-Trader/actions/runs?head_sha=$sha&per_page=100" |
 python3 -c 'import json,sys; runs=json.load(sys.stdin)["workflow_runs"]; assert all(any(r["name"]==name and r["head_sha"]==sys.argv[1] and r["conclusion"]=="success" for r in runs) for name in ("CI","Cloud readiness (no deployment)"))' "$sha"
[[ $(docker exec ai-trader-cloud-api-1 python -c 'from cloud_runtime import SCHEMA_VERSION; print(SCHEMA_VERSION)') == 3 ]] || exit 66
work=$(mktemp -d /opt/ai-trader-migration004.XXXXXXXX)
curl -fsSL "https://github.com/AviramDahan/AI-Trader/archive/$sha.tar.gz" -o "$work/source.tar.gz"
mkdir "$work/source"
tar xzf "$work/source.tar.gz" --strip-components=1 -C "$work/source"
[[ $(sed -n 's/^SCHEMA_VERSION *= *\([0-9]*\).*/\1/p' "$work/source/service/server/cloud_runtime.py") == 4 ]] || exit 66
docker build --build-arg BUILD_SHA="$sha" --label org.opencontainers.image.revision="$sha" -t "ai-trader:$sha" "$work/source"
new=$(docker image inspect --format '{{.Id}}' "ai-trader:$sha")
old=$(docker inspect --format '{{.Image}}' ai-trader-cloud-api-1)
dc run --rm -T --no-deps backup --once --predeploy
cp deploy/compose.yml "$work/previous-compose.yml"
printf '%s\n' "$old" > "$work/previous-image"
# Only this feature's flag is changed. Keep every existing secret/config private.
python3 - <<'PY'
from pathlib import Path
p=Path('deploy/runtime.env')
lines=[s for s in p.read_text().splitlines() if not s.startswith('NEWS_EVIDENCE_ENABLED=')]
p.write_text('\n'.join(lines+['NEWS_EVIDENCE_ENABLED=false'])+'\n')
p.chmod(0o600)
PY
trap 'echo "Controlled migration failed: enrichment stays disabled. Do not rewind the DB or start local workers; operator recovery required."' ERR
dc stop scanner telegram monitor backup api
cp "$work/source/deploy/compose.yml" deploy/compose.yml
export APP_IMAGE="$new"
dc run --rm -T --no-deps migrate
dc up -d --no-deps --no-build --wait --wait-timeout 180 api
dc up -d --no-deps --no-build --wait --wait-timeout 180 monitor
dc up -d --no-deps --no-build --wait --wait-timeout 180 scanner telegram backup
curl -fsS "https://$PUBLIC_API_HOST/health" >/dev/null
docker tag "$new" ai-trader:staging
docker exec ai-trader-cloud-api-1 python -c 'from pathlib import Path; import sys; Path("/app/.runtime/deployed-release").write_text(sys.argv[1])' "$sha"
printf '%s\n%s\n%s\n' "$sha" "$new" "$old" > deploy/last-release.next
mv deploy/last-release.next deploy/last-release
echo "MIGRATION 004 PASS commit=$sha enrichment=disabled"
