#!/bin/sh
# Run from the deployment directory with PUBLIC_API_HOST exported.
# A failed off-server checkpoint aborts before stopping any application service.
set -eu
compose() { docker compose -f deploy/compose.yml --profile backups "$@"; }
compose build
compose exec -T backup python /app/service/server/recovery_backup.py --once --predeploy
compose stop scanner monitor telegram api
compose run --rm --no-deps migrate
compose up -d --wait --wait-timeout 120
