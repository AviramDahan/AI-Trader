"""Same application controls on an isolated migrated PostgreSQL test schema."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
from test_news_provider_controls import (make_pipeline, exercise_disabled_checkpoint_preservation,
    exercise_consumed_probe_survives_disable_and_restart, exercise_grant_never_becomes_unverified_market_news)


def test_pg_disabled_checkpoint_preservation(pg, monkeypatch):
    from database import get_db_connection
    exercise_disabled_checkpoint_preservation(make_pipeline(get_db_connection), monkeypatch)


def test_pg_consumed_probe_survives_disable_and_restart(pg, monkeypatch):
    from database import get_db_connection
    exercise_consumed_probe_survives_disable_and_restart(make_pipeline(get_db_connection), monkeypatch)


def test_pg_grant_never_becomes_unverified_market_news(pg, monkeypatch):
    from database import get_db_connection
    exercise_grant_never_becomes_unverified_market_news(make_pipeline(get_db_connection), monkeypatch)
