"""Run a PostgreSQL utility without putting connection credentials in argv."""
import os
from pathlib import Path
import sys
from psycopg.conninfo import conninfo_to_dict


def main():
    if sys.argv[1] not in {"pg_dump", "pg_restore", "psql"}:
        raise ValueError("unsupported_database_command")
    params = conninfo_to_dict(Path(os.environ["DATABASE_URL_FILE"]).read_text().strip())
    mapping = {"host":"PGHOST", "port":"PGPORT", "user":"PGUSER", "password":"PGPASSWORD",
               "dbname":"PGDATABASE", "sslmode":"PGSSLMODE", "options":"PGOPTIONS",
               "connect_timeout":"PGCONNECT_TIMEOUT"}
    if set(params) - set(mapping):
        raise ValueError("unsupported_connection_parameter")
    for key, value in params.items():
        os.environ[mapping[key]] = str(value)
    command = sys.argv[1:]
    if command[0] == "pg_restore":
        command += ["--dbname", params["dbname"]]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
