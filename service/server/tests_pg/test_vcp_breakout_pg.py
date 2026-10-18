"""Independent VCP scanner/lifecycle boundaries on real disposable PostgreSQL."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import database
import scanner_engine as engine
import stock_scanner as scanner
from test_signal_inputs import clock
from test_vcp_breakout_integration import (
    FLAG, prepare_vcp,
    test_vcp_selection_preserves_contract_fullbar_exit_restart_and_cooldown as exercise_lifecycle,
    test_confirmed_vcp_does_not_bypass_existing_admission as exercise_gates,
    test_vcp_gate_is_only_after_successful_no_forward_zone_fallback as exercise_scope,
    test_confirmed_vcp_selection_never_changes_recovery_holds as exercise_recovery,
    test_selection_evidence_does_not_change_actual_ai_input as exercise_ai_input,
)


@pytest.fixture
def vcp_pg(pg):
    from news_events.store import Store
    Store(database.get_db_connection, sandbox=True).install()
    return pg


def test_pg_vcp_actual_scanner_fullbar_fill_exit_restart(vcp_pg, clock, monkeypatch):
    exercise_lifecycle(None, clock, monkeypatch)


@pytest.mark.parametrize('block', ['hold', 'confidence', 'relevance', 'sentiment', 'quote',
                                  'session', 'resistance', 'cash', 'exposure', 'unknown_vcp'])
def test_pg_vcp_keeps_original_admission_gates(vcp_pg, clock, monkeypatch, block):
    exercise_gates(None, clock, monkeypatch, block)


def test_pg_vcp_only_gates_successful_original_breakout(vcp_pg, clock, monkeypatch):
    exercise_scope(None, clock, monkeypatch)


def test_pg_vcp_cannot_revive_recovery_hold(vcp_pg, clock, monkeypatch):
    exercise_recovery(None, clock, monkeypatch)


def test_pg_vcp_keeps_actual_ai_input(vcp_pg, clock, monkeypatch):
    exercise_ai_input(None, clock, monkeypatch)


def test_pg_vcp_metadata_keeps_existing_active_recovery_format_and_exit(vcp_pg, clock, monkeypatch, tmp_path):
    import recovery_state as recovery
    from test_recovery_holds import target_schema, state
    from test_signal_admission_chain import rows

    prepare_vcp(monkeypatch, clock)
    scanner.run_scan()
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    entry = dict(at='2026-10-06T14:05:00Z', open=100, high=101, low=99.8, close=100)
    engine.process_bar('TEST', entry)
    signal = rows('SELECT technical_json FROM scanner_signals')[0]
    assert json.loads(signal['technical_json'])['vcp_breakout']['state'] == 'CONFIRMED'
    before = state()
    saved_order = rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']
    exported = recovery.export_postgres(vcp_pg)
    assert exported['version'] == exported['recovery_format'] == 6
    assert all(set(json.loads(s['technical_json'])) == {'target_plan'}
               for s in exported['tables']['scanner_signals'])
    assert 'vcp_breakout' not in json.dumps(exported)
    identity = tmp_path / 'synthetic-age-identity'
    subprocess.run(['age-keygen', '-o', str(identity)], capture_output=True, check=True)
    recipient = subprocess.check_output(['age-keygen', '-y', str(identity)]).decode().strip()
    ciphertext, sizes = recovery.encrypted_bytes(exported, recipient)
    encrypted = tmp_path / 'synthetic-vcp-recovery.age'
    encrypted.write_bytes(ciphertext)
    decoded = recovery.decrypt(encrypted, identity)
    assert decoded == exported and sizes['encrypted_bytes'] == len(ciphertext)
    target = json.loads(saved_order)['target_plan']['active_target']
    monkeypatch.setenv(FLAG, 'false')
    with target_schema(vcp_pg) as destination:
        recovery.restore(decoded, destination, 'synthetic-vcp-recovery-token-32-characters')
        assert state() == before
        assert rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'] == saved_order
        assert not rows('SELECT id FROM scanner_telegram_outbox')
        engine.initialize_runtime()
        engine.process_bar('TEST', entry)
        assert state() == before
        clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
        exit_bar = dict(at='2026-10-06T14:10:00Z', open=target,
                        high=target+.2, low=target-.2, close=target)
        engine.process_bar('TEST', exit_bar)
        engine.initialize_runtime()
        engine.process_bar('TEST', exit_bar)
        assert len(rows('SELECT id FROM scanner_fills')) == 2
        assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [
            {'status': 'closed', 'remaining_quantity': 0}]
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
