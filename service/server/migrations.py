"""Numbered PostgreSQL migration runner; never executed by cloud API/workers."""
from pathlib import Path


def migrate():
    import psycopg
    from config import DATABASE_URL
    from database import init_database
    if not DATABASE_URL:
        raise RuntimeError("migration_requires_postgresql")
    with psycopg.connect(DATABASE_URL, autocommit=True) as control:
        control.execute("SELECT pg_advisory_lock(719323,1)")
        control.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        versions = {r[0] for r in control.execute("SELECT version FROM schema_migrations")}
        if 1 not in versions:
            # Idempotent baseline of the original schema. No seed/demo portfolio.
            init_database()
            control.execute("INSERT INTO schema_migrations(version) VALUES(1)")
        for version, filename in [(2, "002_cloud.sql")]:
            if version in versions:
                continue
            with control.transaction():
                control.execute((Path(__file__).parent / "migrations" / filename).read_text())
                control.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (version,))


if __name__ == "__main__":
    migrate()
