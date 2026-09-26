#!/bin/sh
# Active-state only. Never upload a full database or a plaintext snapshot.
set -eu
umask 077
exec python /app/service/server/recovery_backup.py "$@"
