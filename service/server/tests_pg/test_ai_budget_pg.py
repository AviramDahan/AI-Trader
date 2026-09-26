import json
from unittest.mock import Mock
import ai_budget
import database
import scanner_engine


def test_budget_warnings_are_durable_and_deduplicated(pg):
    for usage in (15,15,18,18,20,20):
        ai_budget.persist(usage,20,'2026-09-26T12:00:00+00:00')
    with database.get_db_connection() as conn:
        alerts=conn.execute("SELECT key FROM scanner_settings WHERE key LIKE 'ai_budget_alert:%'").fetchall()
        assert len(alerts)==3
        state=json.loads(conn.execute("SELECT value_json FROM scanner_settings WHERE key='ai_budget'").fetchone()['value_json'])
        assert state['exhausted'] is True
    ai_budget.persist(0,20,'2026-10-01T00:00:01+00:00')
    with database.get_db_connection() as conn:
        state=json.loads(conn.execute("SELECT value_json FROM scanner_settings WHERE key='ai_budget'").fetchone()['value_json'])
        assert state['exhausted'] is False


def test_monitor_does_not_consult_failed_ai_budget(pg,monkeypatch):
    gate=Mock(side_effect=ai_budget.BudgetUnavailable('exhausted'))
    monkeypatch.setattr(ai_budget,'check',gate)
    monkeypatch.setattr(scanner_engine,'market_session_state',lambda: {'is_trading_day':False,'is_open':False,'reason':'weekend'})
    result=scanner_engine.monitor_prices()
    assert not result['errors']
    gate.assert_not_called()


def test_request_pacing_reserves_across_callers_and_releases_lock_before_sleep(pg,monkeypatch):
    import psycopg
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    waits=[]
    def sleep(delay):
        waits.append(delay)
        # An independent connection must be able to take the slot lock while
        # the previous caller waits. No sleeping database transaction remains.
        with psycopg.connect(pg) as conn:
            assert conn.execute('SELECT pg_try_advisory_xact_lock(719324,1)').fetchone()[0]
    monkeypatch.setattr(ai_budget.time,'sleep',sleep)
    ai_budget.acquire_request_slot()
    ai_budget.acquire_request_slot()
    ai_budget.acquire_request_slot()
    assert len(waits)==2
    assert 0 < waits[0] < waits[1] <= 6.4
