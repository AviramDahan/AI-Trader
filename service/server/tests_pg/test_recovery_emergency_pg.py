"""Real PostgreSQL + age round-trip of durable entry pause; disposable schemas."""
import json
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import database
import entry_emergency as emergency
import scanner_engine as engine
import recovery_state as recovery
from test_recovery_holds import initialize_empty, record, state, target_schema


@pytest.mark.parametrize('resumed', [False, True])
def test_encrypted_emergency_roundtrip_preserves_pause_history_holds_and_exits(pg, tmp_path, resumed):
    initialize_empty()
    with patch.object(engine, 'now_z', return_value='2026-10-06T14:00:37Z'):
        assert record('ACTIVE')['status'] == 'PENDING_ENTRY'
        held = record('HELD')
        assert held['status'] == 'PENDING_ENTRY'
    with database.get_db_connection() as conn:
        conn.execute("UPDATE scanner_orders SET status='recovery_uncertain' WHERE signal_id=?", (held['id'],))
        conn.execute("UPDATE scanner_signals SET status='RECOVERY_UNCERTAIN' WHERE id=?", (held['id'],))
        conn.commit()
    with patch.object(engine, 'now_z', return_value='2026-10-06T14:10:00Z'):
        engine.process_bar('ACTIVE', dict(at='2026-10-06T14:05:00Z', open=100, high=100.1, low=99.9, close=100))
    assert state()['trades']
    control = emergency.set_paused(True, 0, now=datetime(2026,10,6,14,11,tzinfo=timezone.utc))
    if resumed:
        control = emergency.set_paused(False, 1, now=datetime(2026,10,6,14,17,tzinfo=timezone.utc))
    before = state()
    data = recovery.export_postgres(pg)
    assert data['version'] == data['recovery_format'] == 9
    assert data['hold_coverage']['entry_reserved_notional'] == before['reserved'][0]['amount']
    key = tmp_path/'synthetic-identity'
    subprocess.run(['age-keygen','-o',str(key)],check=True,capture_output=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()
    ciphertext, _ = recovery.encrypted_bytes(data, recipient)
    artifact=tmp_path/'synthetic.age'
    artifact.write_bytes(ciphertext)
    recovered = recovery.decrypt(artifact, key)
    assert recovered == data
    with target_schema(pg) as target:
        recovery.restore(recovered, target, 'synthetic-emergency-token-more-than-32-characters')
        engine.initialize_runtime()
        assert state() == before
        with database.get_db_connection() as conn:
            assert emergency.snapshot(conn.cursor()) == control
            allowed=emergency.check(conn.cursor(),bar_at='2026-10-06T14:15:00Z',observed_at='2026-10-06T14:20:00Z')
            assert not allowed['allowed']  # paused or straddling the saved resume.
            assert conn.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n'] == 0
            trade=dict(conn.execute("SELECT * FROM scanner_trades WHERE ticker='ACTIVE' AND is_shadow=0").fetchone())
        target_price=trade['tp3'] if trade['strategy']=='staged' else trade['tp1']
        with patch.object(engine, 'now_z', return_value='2026-10-06T14:25:00Z'):
            engine.process_bar('ACTIVE', dict(at='2026-10-06T14:20:00Z',open=target_price,
                high=target_price+.1,low=target_price-.1,close=target_price))
        after = state()
        assert after['holds'] == before['holds']
        assert len(after['fills']) > len(before['fills'])
        engine.initialize_runtime()
        with patch.object(engine,'now_z',return_value='2026-10-06T14:25:00Z'):
            engine.process_bar('ACTIVE',dict(at='2026-10-06T14:20:00Z',open=target_price,
                high=target_price+.1,low=target_price-.1,close=target_price))
        assert state() == after
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
