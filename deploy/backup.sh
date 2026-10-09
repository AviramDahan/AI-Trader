#!/bin/sh
# Active-state plus SEC-only encrypted companion. No full DB or plaintext upload.
set -eu
umask 077
exec python /app/service/server/recovery_backup.py "$@"
