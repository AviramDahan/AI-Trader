"""Same SEC state regressions on disposable PostgreSQL test schemas only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_team_sec_snapshot_regressions import (
    NOW,
    test_latest_snapshot_revokes_current_eligibility_without_old_fallback as exercise_revocation,
    test_future_snapshot_is_not_available_ahead_of_decision as exercise_future,
    test_future_universe_membership_cannot_rewrite_earlier_view as exercise_universe,
    test_snapshot_order_tracks_newest_state_with_deterministic_ties as exercise_ties,
    test_busy_issuer_cannot_crowd_out_another_tickers_snapshot as exercise_fairness,
    test_matched_disposal_amendment_withdraws_current_purchase_preserving_history as exercise_amendment,
    test_normal_snapshot_keeps_original_publication_and_expires_without_rejuvenation as exercise_normal,
    test_current_sec_news_route_remains_paper_only as exercise_mode,
)


@pytest.mark.parametrize("state", ["unknown", "expired", "issuer_mismatch"])
def test_pg_latest_state_revokes_eligibility(pg, state):
    exercise_revocation(pg, state)


@pytest.mark.parametrize("future_field", ["created", "available"])
def test_pg_no_ahead_snapshot(pg, future_field):
    exercise_future(pg, future_field)


def test_pg_no_ahead_universe(pg):
    exercise_universe(pg)


def test_pg_newest_state_and_deterministic_ties(pg):
    exercise_ties(pg)


def test_pg_busy_issuer_fairness(pg):
    exercise_fairness(pg)


def test_pg_reader_is_read_only_and_returns_one_database_row_per_ticker(pg, monkeypatch):
    import cloud_runtime
    import sec_intelligence as si

    exercise_fairness(pg)
    monkeypatch.setenv("AI_TRADER_CLOUD", "true")
    monkeypatch.setattr(cloud_runtime, "guard_lease", lambda: None)
    connect = si.get_db_connection
    returned_counts = []

    class Batch:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    def observed_connection():
        conn = connect()
        execute = conn.execute

        def observed_execute(statement, *args, **kwargs):
            cursor = execute(statement, *args, **kwargs)
            if "si_company_snapshots" in statement:
                assert execute("SHOW transaction_read_only").fetchone()[0] == "on"
                rows = cursor.fetchall()
                returned_counts.append(len(rows))
                return Batch(rows)
            return cursor

        conn.execute = observed_execute
        return conn

    monkeypatch.setattr(si, "get_db_connection", observed_connection)
    assert set(si.snapshots_for([{"ticker": "A"}, {"ticker": "B"}], NOW)) == {"A", "B"}
    assert returned_counts == [2]


def test_pg_disposal_amendment_preserves_historical_decision(pg, monkeypatch):
    exercise_amendment(pg, monkeypatch)


def test_pg_publication_time_and_normal_expiry(pg):
    exercise_normal(pg)


@pytest.mark.parametrize("mode,killed,eligible", [
    ("off", False, False), ("shadow", False, False),
    ("paper", True, False), ("paper", False, True)])
def test_pg_sec_news_stays_paper_only(pg, monkeypatch, mode, killed, eligible):
    exercise_mode(pg, monkeypatch, mode, killed, eligible)
