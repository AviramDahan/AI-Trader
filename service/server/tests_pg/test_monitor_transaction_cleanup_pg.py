"""Real isolated PostgreSQL rollback and lock release, no providers or orders."""
import pytest


def test_failed_bar_releases_held_write_lock_with_retained_connection(pg,monkeypatch):
    import scanner_engine as engine
    import database
    original=database.get_db_connection
    captured=[]
    def connect():
        conn=original();captured.append(conn);return conn
    monkeypatch.setattr(engine,'get_db_connection',connect)
    def fail_after_acquisition(cur):
        database.begin_write_transaction(cur)
        cur.execute("INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('cleanup-test','{}','2026-11-03T15:00:00Z')")
        raise RuntimeError('synthetic failure after held write lock')
    monkeypatch.setattr(engine,'begin_write_transaction',fail_after_acquisition)
    try:
        with pytest.raises(RuntimeError,match='synthetic failure'):
            engine.process_bar('TEST',dict(at='2026-11-03T15:00:00Z',open=100,high=101,low=99,close=100))
        assert len(captured)==1 and captured[0].closed
        with original() as c:
            # Isolated test DB only. No Production lock probing/acquisition.
            assert c.execute('SELECT pg_try_advisory_xact_lock(719321,1) AS available').fetchone()['available'] is True
            assert not c.execute("SELECT 1 FROM scanner_settings WHERE key='cleanup-test'").fetchone()
            assert c.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']==0
    finally:
        for conn in captured:conn.close()
