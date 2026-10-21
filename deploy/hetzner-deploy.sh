#!/usr/bin/env bash
# Root-installed; direct and pull-triggered entries share one verified flock.
set -Eeuo pipefail
umask 077
sha=${1:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 64
lock=/run/lock/ai-trader-deploy.lock
if [[ -n "${AI_TRADER_DEPLOY_LOCK_FD:-}" ]]; then
  [[ "$AI_TRADER_DEPLOY_LOCK_FD" =~ ^[0-9]{1,3}$ && "$AI_TRADER_DEPLOY_LOCK_FD" -ge 3 ]] || exit 64
  [[ "$(stat -Lc '%d:%i' "/proc/self/fd/$AI_TRADER_DEPLOY_LOCK_FD")" == "$(stat -Lc '%d:%i' "$lock")" ]] || exit 64
  exec 9>&"$AI_TRADER_DEPLOY_LOCK_FD"
else
  exec 9>>"$lock"
fi
flock -n 9 || exit 75
export AI_TRADER_DEPLOY_LOCK_FD=9
export DOCKER_DEFAULT_PLATFORM=linux/amd64
root=/opt/ai-trader-staging
controller=/usr/local/sbin/ai-trader-pull
repo=https://github.com/AviramDahan/AI-Trader
export PUBLIC_API_HOST=2-28-100-77.sslip.io
cd "$root"
dc=(docker compose -f "$root/deploy/compose.yml" --profile backups)
# Whole forward budget and an independent rollback reserve. Unit/observer
# ceilings include both; no backup process is killed when our wait expires.
forward_budget_seconds=3600
rollback_budget_seconds=1200
backup_wait_seconds=1200
forward_deadline=$((SECONDS + forward_budget_seconds))
deadline=$forward_deadline
attempt=''
work=''
new=''
rollback=''
certified_candidate=0
writers_stopped=0
phase=STARTED
remaining() {
  local cap=$1 left=$((deadline - SECONDS))
  (( left > 0 )) || return 75
  (( cap < left )) && echo "$cap" || echo "$left"
}
bounded() {
  local cap=$1 limit
  shift
  limit=$(remaining "$cap") || return 75
  # This bounds release CLIENTS, never a detached valid backup container.
  timeout --foreground --signal=TERM --kill-after=10 "$limit" "$@"
}
set_phase() {
  phase=$1
  local args=(--journal-update --sha "$sha" --request-id "$attempt" --phase "$phase")
  [[ -z "$new" || "$new" == '-' ]] || args+=(--image "$new")
  "$controller" "${args[@]}"
}
drain_backup() {
  local wait
  wait=$(remaining 900) || return 75
  "$controller" --stop-backup-idle --wait-seconds "$wait"
}
start_healthy() {
  local cap=$1 limit role
  shift
  limit=$(remaining "$cap") || return 75
  bounded "$limit" "${dc[@]}" up -d --no-deps --no-build --wait --wait-timeout "$limit" "$@" || return $?
  for role in "$@"; do
    bounded 150 "$controller" --verify-role --role "$role" --image "$APP_IMAGE" >/dev/null || { echo "Readiness failed: $role is not healthy/running on expected image"; return 1; }
  done
}
failed() {
  local code=${1:-$?} interrupted=${2:-0}
  trap - ERR TERM INT
  if [[ -z "$attempt" ]]; then
    echo 'DEPLOY FAILED before durable attempt initialization'
    exit "$code"
  fi
  if [[ "$writers_stopped" == 0 && "$phase" != DRAIN_PENDING && "$phase" != REPLACING ]]; then
    if [[ "$code" == 75 && "$phase" =~ ^DEFERRED_ ]]; then
      : # Exact detached job remains joinable; no failure latch or kill.
    elif [[ "$interrupted" == 1 ]]; then
      set_phase INTERRUPTED || true
    else
      set_phase FAILED || true
    fi
    echo 'DEPLOY NOT COMPLETE; application writers untouched; any valid backup continues'
    exit "$code"
  fi
  deadline=$((SECONDS + rollback_budget_seconds))
  set_phase ROLLING_BACK || true
  if [[ "$writers_stopped" == 0 ]]; then
    # Drain may have stopped the idle hourly service just before an interrupt.
    # Do not touch financial workers. Never restart an already running backup.
    bounded 150 "$controller" --verify-role --role backup --image "$old" --allow-stopped >/dev/null || { set_phase ROLLBACK_DEFERRED || true; exit 70; }
    running=$(bounded 20 docker inspect --format '{{.State.Running}}' ai-trader-cloud-backup-1) || exit 70
    if [[ "$running" != true ]]; then
      bounded 30 docker start ai-trader-cloud-backup-1 || { set_phase ROLLBACK_DEFERRED || true; exit 70; }
    fi
    while true; do
      if bounded 150 "$controller" --verify-role --role backup --image "$old" >/dev/null; then break; fi
      remaining 1 >/dev/null || { set_phase ROLLBACK_DEFERRED || true; exit 70; }
      sleep 2
    done
    set_phase ROLLED_BACK || true
    echo 'DEPLOY NOT COMPLETE; original writers unchanged and original backup restored'
    exit "$code"
  fi
  # Never stop/kill the current backup while it owns backup.lock. If it
  # outlives the reserve, leave the current runtime alone and require review.
  if ! drain_backup; then
    set_phase ROLLBACK_DEFERRED || true
    echo 'ROLLBACK DEFERRED: valid backup or uncertain lock; manual intervention required'
    exit 70
  fi
  bounded 90 "${dc[@]}" stop scanner telegram monitor || { set_phase ROLLBACK_DEFERRED || true; exit 70; }
  cp "$work/previous-compose.yml" deploy/compose.yml
  export APP_IMAGE="${rollback:-$old}"
  start_healthy 180 api monitor scanner telegram || { set_phase ROLLBACK_DEFERRED || true; echo 'ROLLBACK FAILED: manual intervention required'; exit 70; }
  start_healthy "$backup_wait_seconds" backup || { set_phase ROLLBACK_DEFERRED || true; echo 'ROLLBACK FAILED: backup not healthy; no valid backup killed'; exit 70; }
  bounded 30 docker tag "$APP_IMAGE" ai-trader:staging || exit 70
  if [[ "$APP_IMAGE" != "$old" ]]; then
    bounded 60 "$controller" --record-bridge-rollback --sha "$sha" --image "$APP_IMAGE" --old-image "$old" --request-id "$attempt" || { set_phase ROLLBACK_DEFERRED || true; exit 70; }
  fi
  set_phase ROLLED_BACK || true
  echo "DEPLOY FAILED; supported rollback image=$APP_IMAGE; observed previous image=$old; database never rewound"
  exit "$code"
}
trap 'failed $? 0' ERR
trap 'failed 143 1' TERM
trap 'failed 130 1' INT
head=$(bounded 30 git ls-remote "$repo.git" refs/heads/main | cut -f1)
[[ "$head" == "$sha" ]] || { echo 'Refusing stale/non-main commit'; exit 65; }
old=$(bounded 180 "$controller" --resolve-running --role api --print-ref)
begin=$("$controller" --journal-begin --sha "$sha" --image "$old")
IFS=$'\t' read -r attempt work old new phase <<< "$begin"
[[ "$attempt" =~ ^[0-9a-f]{32}$ && -d "$work" && "$old" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 76
if [[ "$new" == '-' ]]; then
  set_phase BUILDING
  bounded 120 curl --fail --silent --show-error --location --max-time 110 "$repo/archive/$sha.tar.gz" -o "$work/source.tar.gz"
  mkdir "$work/source"
  bounded 60 tar xzf "$work/source.tar.gz" --strip-components=1 -C "$work/source"
  old_schema=$(bounded 30 docker exec ai-trader-cloud-api-1 python -c 'from cloud_runtime import SCHEMA_VERSION; print(SCHEMA_VERSION)')
  new_schema=$(sed -n 's/^SCHEMA_VERSION *= *\([0-9]*\).*/\1/p' "$work/source/service/server/cloud_runtime.py")
  [[ "$old_schema" == "$new_schema" ]] || { echo 'Schema change requires operator-approved migration'; exit 66; }
  if [[ -e deploy/compatible-rollback-v1.json || -L deploy/compatible-rollback-v1.json ]]; then
    if selected_candidate=$(bounded 360 "$controller" --compatible-candidate --sha "$sha" --image "$old" --print-ref); then
      [[ "$selected_candidate" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'Certified candidate identity missing'; failed 67 0; }
      new="$selected_candidate"
    else
      failed 67 0
    fi
    certified_candidate=1
  else
    bounded 600 docker build --build-arg BUILD_SHA="$sha" --label org.opencontainers.image.revision="$sha" -t "ai-trader:$sha" "$work/source"
    new=$(bounded 20 docker image inspect --format '{{.Id}}' "ai-trader:$sha")
  fi
  set_phase PREDEPLOY_PENDING
fi
rollback="$old"
if [[ -e deploy/compatible-rollback-v1.json || -L deploy/compatible-rollback-v1.json ]]; then
  certified_candidate=1
fi
if [[ "$certified_candidate" == 1 ]]; then
  if rollback=$(bounded 360 "$controller" --check-rollback --sha "$sha" --image "$old" --new-image "$new" --request-id "$attempt" --print-ref); then
    [[ "$rollback" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'Certified rollback identity missing'; failed 67 0; }
  else
    failed 67 0
  fi
elif ! bounded 360 "$controller" --check-rollback --sha "$sha" --image "$old" --new-image "$new"; then
  # Explicit exit bypasses ERR traps; persist the genuine pre-writer failure.
  failed 67 0
fi
set_phase PREDEPLOY_PENDING
wait=$(remaining 1800)
if "$controller" --backup-only --sha "$sha" --image "$new" --request-id "$attempt" --wait-seconds "$wait"; then
  set_phase PREDEPLOY_VERIFIED
else
  code=$?
  [[ "$code" != 75 ]] || set_phase DEFERRED_PREDEPLOY
  failed "$code" 0
fi
set_phase DRAIN_PENDING
[[ -f "$work/previous-compose.yml" ]] || cp deploy/compose.yml "$work/previous-compose.yml"
if drain_backup; then
  :
else
  code=$?
  [[ "$code" != 75 ]] || set_phase DEFERRED_DRAIN
  failed "$code" 0
fi
if [[ "$certified_candidate" == 1 ]]; then
  bounded 180 "$controller" --verify-rollback-selection --sha "$sha" --image "$new" --old-image "$old" --request-id "$attempt"
fi
set_phase REPLACING
writers_stopped=1
bounded 90 "${dc[@]}" stop scanner telegram monitor
cp "$work/source/deploy/compose.yml" deploy/compose.yml
export APP_IMAGE="$new"
bounded 180 "${dc[@]}" run --rm -T --no-deps migrate
start_healthy 180 api
start_healthy 180 monitor
start_healthy 180 scanner telegram
start_healthy "$backup_wait_seconds" backup
bounded 45 curl --fail --silent --show-error --max-time 30 "https://$PUBLIC_API_HOST/health" >/dev/null
bounded 30 docker tag "$new" ai-trader:staging
set_phase COMMITTING
"$controller" --commit-release --sha "$sha" --image "$new" --old-image "$old" --request-id "$attempt"
trap - ERR TERM INT
echo "DEPLOY PASS commit=$sha image=$new"
# Keep prior images, source, exact backup jobs and attempt metadata for review.
