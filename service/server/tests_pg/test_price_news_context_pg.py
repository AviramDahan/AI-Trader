"""Real isolated PostgreSQL admissions; provider/AI calls remain synthetic."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
import database
from test_signal_inputs import clock
from test_price_news_context import (
    PRICE_IDS,
    test_each_price_route_can_reach_real_pending_then_fill_and_exit_without_article as exercise_chain,
    test_mixed_detection_freezes_price_only_execution_then_bridge_restart_and_stop as exercise_mixed,
    test_new_context_pending_pause_restart_resume_does_not_backfill_paused_bar as exercise_emergency,
    test_empty_news_cannot_overcome_cash_gate as exercise_cash,
    test_fixed_ai_quota_and_default_off as exercise_quota,
)


@pytest.fixture
def price_pg(pg):
    from news_events.store import Store
    Store(database.get_db_connection, sandbox=True).install()
    return pg


@pytest.mark.parametrize('strategy_id', PRICE_IDS)
def test_pg_price_route_no_article_entry_exit_restart(price_pg, clock, monkeypatch, strategy_id):
    exercise_chain(None, clock, monkeypatch, strategy_id)


def test_pg_mixed_detection_cannot_fill_via_baseline(price_pg, clock, monkeypatch):
    exercise_mixed(None, clock, monkeypatch)


def test_pg_optional_news_respects_pending_pause_and_resume(price_pg, clock, monkeypatch):
    exercise_emergency(None, clock, monkeypatch)


def test_pg_optional_news_respects_cash(price_pg, clock, monkeypatch):
    exercise_cash(None, clock, monkeypatch)


def test_pg_optional_news_does_not_expand_ai_quota(price_pg, clock, monkeypatch):
    exercise_quota(None, clock, monkeypatch)
