#!/bin/sh
# PostgreSQL cluster administrator stays separate from the application role.
set -eu
export APP_DB_PASSWORD="$(cat /run/secrets/app_password)"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password APP_DB_PASSWORD
SELECT format('CREATE ROLE ai_trader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_password') \gexec
ALTER DATABASE ai_trader OWNER TO ai_trader;
GRANT USAGE, CREATE ON SCHEMA public TO ai_trader;
SQL
unset APP_DB_PASSWORD
