"""Numbered PostgreSQL migration runner; never executed by cloud API/workers."""
from pathlib import Path


def migrate(target_version=7):
    import psycopg
    from config import DATABASE_URL
    from database import init_database
    if not DATABASE_URL:
        raise RuntimeError("migration_requires_postgresql")
    if target_version not in (5, 6, 7):
        raise ValueError('unsupported_migration_target')
    with psycopg.connect(DATABASE_URL, autocommit=True) as control:
        control.execute("SELECT pg_advisory_lock(719323,1)")
        control.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        versions = {r[0] for r in control.execute("SELECT version FROM schema_migrations")}
        if 1 not in versions:
            # Idempotent baseline of the original schema. No seed/demo portfolio.
            init_database()
            control.execute("INSERT INTO schema_migrations(version) VALUES(1)")
        for version, filename in [(2, "002_cloud.sql"), (3, "003_ai_operations.sql"), (4, "004_news_evidence.sql"), (5, "005_news_events.sql"), (6, "006_single_target.sql"), (7, "007_sec_intelligence.sql")]:
            if version > target_version:
                continue
            if version in versions:
                continue
            with control.transaction():
                if version == 5:
                    control.execute((Path(__file__).parent / 'news_events' / 'schema.sql').read_text())
                control.execute((Path(__file__).parent / "migrations" / filename).read_text())
                control.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (version,))


if __name__ == "__main__":
    migrate()
