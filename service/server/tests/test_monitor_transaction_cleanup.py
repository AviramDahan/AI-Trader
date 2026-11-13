"""Regression for retained failed monitor connections, no network/database."""
from unittest.mock import Mock
import pytest


def test_bar_write_failure_closes_connection_even_when_reference_is_retained(monkeypatch):
    import scanner_engine as engine
    conn=Mock();conn.cursor.return_value=Mock()
    retained=[conn]  # Exception/audit retention must not be needed for cleanup.
    monkeypatch.setattr(engine,'get_db_connection',lambda:retained[0])
    def fail(_cursor):raise RuntimeError('synthetic write failure after connection acquisition')
    monkeypatch.setattr(engine,'begin_write_transaction',fail)
    with pytest.raises(RuntimeError,match='synthetic write failure'):
        engine.process_bar('TEST',dict(at='2026-11-03T15:00:00Z',open=100,high=101,low=99,close=100))
    conn.close.assert_called_once()


def test_bar_replay_rolls_back_and_closes_exactly_once(monkeypatch):
    import scanner_engine as engine
    conn=Mock();cur=conn.cursor.return_value
    cur.fetchone.return_value={'last_bar_at':'2026-11-03T15:00:00Z'}
    monkeypatch.setattr(engine,'get_db_connection',lambda:conn)
    monkeypatch.setattr(engine,'begin_write_transaction',lambda _cur:None)
    engine.process_bar('TEST',dict(at='2026-11-03T15:00:00Z',open=100,high=101,low=99,close=100))
    conn.rollback.assert_called_once();conn.close.assert_called_once();conn.commit.assert_not_called()
