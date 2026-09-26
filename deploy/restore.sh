#!/bin/sh
# Run in an isolated container/database, never against the active database.
set -eu
umask 077
[ "${RESTORE_ISOLATED_DATABASE:-}" = true ] || exit 2
[ -n "${RESTORE_DATABASE_URL_FILE:-}" ] || exit 2
export DATABASE_URL_FILE="$RESTORE_DATABASE_URL_FILE"
count=$(python /app/service/server/db_command.py psql -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
[ "$count" = 0 ] || { echo 'Restore destination must be empty'; exit 2; }
work=$(mktemp -d /tmp/ai-trader-restore.XXXXXX)
mkfifo "$work/dump.pipe"
age -d -i "$AGE_IDENTITY_FILE" "$1" > "$work/dump.pipe" &
decryptor=$!
ok=1
python /app/service/server/db_command.py pg_restore --exit-on-error --single-transaction --no-owner --no-acl < "$work/dump.pipe" || ok=0
wait "$decryptor" || ok=0
rm -f "$work/dump.pipe"
rmdir "$work"
[ "$ok" = 1 ] || exit 1
python /app/service/server/db_command.py psql -v ON_ERROR_STOP=1 -Atc 'SELECT count(*) FROM scanner_trades; SELECT max(version) FROM schema_migrations;'
echo 'Restore completed; run active-state integrity validation before using this database'
