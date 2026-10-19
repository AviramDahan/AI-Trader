"""Actual isolated PostgreSQL snapshots; no workers, providers or real messages."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import database
import strategy_performance as performance
from test_signal_inputs import clock
from test_entry_strategies_integration import no_external_entry_io
from test_strategy_performance import (
    NOW, test_actual_route_entry_exit_report_readonly_and_flags_do_not_rewrite_history as exercise_report,
)


@pytest.mark.parametrize('strategy_id', tuple(performance.FLAGS))
def test_pg_actual_each_route_retained_performance(pg, clock, monkeypatch, strategy_id):
    from news_events.store import Store
    Store(database.get_db_connection, sandbox=True).install()
    exercise_report(None, clock, monkeypatch, strategy_id)


def test_pg_unprotected_snapshot_is_rejected(pg):
    with database.get_db_connection() as conn:
        with pytest.raises(RuntimeError, match='read_only_snapshot_required'):
            performance.report(conn, 48, NOW)
