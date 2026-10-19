"""Independent real PostgreSQL parity and encrypted strategy attribution recovery.

Only the existing opt-in test_* schema fixture is used. No worker/provider call.
"""
import copy
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
import entry_discovery as discovery
from test_signal_inputs import clock
from test_entry_strategies_integration import (
    IDS, GATES, prepare_route, seed_close_hold, no_external_entry_io,
    test_each_real_discovery_signal_pending_fullbar_exit_restart as exercise_lifecycle,
    test_each_route_preserves_all_original_admission_gates as exercise_gate,
    test_two_real_detections_merge_one_ai_one_order_all_attribution as exercise_merge,
    test_close_long_attribution_matches_closing_signal_not_original_entry as exercise_close,
    test_forged_future_attribution_blocks_creation_before_any_signal as exercise_future,
    test_creation_disabled_does_not_accept_retained_new_route_as_new_signal as exercise_disabled,
    test_completed_setup_discovery_keeps_existing_passive_limit_gap_semantics as exercise_gap,
    test_new_frozen_support_declines_actual_gap_then_retries_without_level_moves as exercise_frozen_gap,
    test_new_malformed_execution_becomes_uncertain_without_cash_or_fill as exercise_malformed,
    test_bridge_role_cannot_create_even_with_flags_enabled as exercise_bridge,
    test_original_release_producer_to_reader_to_actual_pead_and_restart as exercise_release,
    test_new_frozen_window_expiry_or_gap_is_uncertain_not_fabricated_fill as exercise_expiry,
)
from test_signal_admission_chain import rows


@pytest.fixture
def entry_pg(pg):
    from news_events.store import Store
    Store(database.get_db_connection, sandbox=True).install()
    return pg


@pytest.mark.parametrize('strategy_id', IDS)
def test_pg_actual_each_discovery_signal_bar_exit_restart(entry_pg, clock, monkeypatch, strategy_id):
    exercise_lifecycle(None, clock, monkeypatch, strategy_id)


@pytest.mark.parametrize('strategy_id', IDS)
@pytest.mark.parametrize('block', GATES)
def test_pg_each_route_keeps_admission_gates(entry_pg, clock, monkeypatch, strategy_id, block):
    exercise_gate(None, clock, monkeypatch, strategy_id, block)


def test_pg_multiple_detections_one_order(entry_pg, clock, monkeypatch):
    exercise_merge(None, clock, monkeypatch)


def test_pg_closing_attribution_is_not_original_entry(entry_pg, clock, monkeypatch):
    exercise_close(None, clock, monkeypatch)


def test_pg_future_detection_cannot_create_signal(entry_pg, clock, monkeypatch):
    exercise_future(None, clock, monkeypatch)


def test_pg_creation_disabled_is_not_execution_disabled(entry_pg, clock, monkeypatch):
    exercise_disabled(None, clock, monkeypatch)


def test_pg_setup_is_not_continuous_above_pivot_fill_policy(entry_pg, clock, monkeypatch):
    exercise_gap(None, clock, monkeypatch)


@pytest.mark.parametrize('strategy_id', ('RELATIVE_STRENGTH_LEADER', 'TREND_PULLBACK_RECLAIM'))
def test_pg_new_frozen_support_gap_retry(entry_pg, clock, monkeypatch, strategy_id):
    exercise_frozen_gap(None, clock, monkeypatch, strategy_id)


@pytest.mark.parametrize('damage', ('version', 'support', 'signal_association', 'orphan_observation'))
def test_pg_new_malformed_execution_uncertain(entry_pg, clock, monkeypatch, damage):
    exercise_malformed(None, clock, monkeypatch, damage)


def test_pg_bridge_cannot_create(entry_pg, clock, monkeypatch):
    exercise_bridge(None, clock, monkeypatch)


def test_pg_original_release_producer_reader_actual_pead_restart(entry_pg, clock, monkeypatch):
    exercise_release(None, clock, monkeypatch)


@pytest.mark.parametrize('evidence', ('touch_straddles_expiry', 'missing_bar'))
def test_pg_new_frozen_window_expiry_or_gap(entry_pg, clock, monkeypatch, evidence):
    exercise_expiry(None, clock, monkeypatch, evidence)


def encrypt_roundtrip(data, tmp_path):
    import recovery_state as recovery
    key = tmp_path / 'synthetic-only-identity'
    subprocess.run(['age-keygen', '-o', str(key)], capture_output=True, check=True)
    recipient = subprocess.check_output(['age-keygen', '-y', str(key)]).decode().strip()
    ciphertext, sizes = recovery.encrypted_bytes(data, recipient)
    artifact = tmp_path / 'synthetic-entry-discovery.age'
    artifact.write_bytes(ciphertext)
    assert sizes['encrypted_bytes'] == len(ciphertext)
    restored = recovery.decrypt(artifact, key)
    assert restored == data
    return restored


@pytest.mark.parametrize('strategy_id', IDS)
def test_pg_encrypted_recovery_preserves_each_strategy_audit_and_frozen_exit(
        entry_pg, clock, monkeypatch, tmp_path, strategy_id):
    import recovery_state as recovery
    from test_recovery_holds import state, target_schema
    _, _, quote, _, _, _ = prepare_route(monkeypatch, clock, strategy_id)
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    entry = dict(at='2026-10-06T14:05:00Z', open=quote, high=quote+.2, low=quote-.1, close=quote)
    engine.process_bar('TEST', entry)
    before = state()
    order_before = rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']
    contract = json.loads(order_before)
    package = contract['entry_discovery']
    assert package['strategy_ids'] == [strategy_id]
    exported = recovery.export_postgres(entry_pg)
    assert exported['version'] == exported['recovery_format'] == 8
    assert rows('SELECT MAX(version) version FROM schema_migrations') == [{'version': 7}]
    assert json.loads(exported['tables']['scanner_signals'][0]['technical_json'])['entry_discovery'] == package
    assert json.loads(exported['tables']['scanner_orders'][0]['plan_json'])['entry_discovery'] == package
    assert json.loads(exported['tables']['scanner_trades'][0]['settings_json'])['entry_discovery'] == package
    decoded = encrypt_roundtrip(exported, tmp_path)
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    with target_schema(entry_pg) as destination:
        recovery.restore(decoded, destination, 'synthetic-entry-recovery-token-32-characters')
        assert state() == before
        assert rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'] == order_before
        assert not rows('SELECT id FROM scanner_telegram_outbox')
        engine.initialize_runtime()
        engine.process_bar('TEST', entry)
        assert state() == before
        target = contract['target_plan']['active_target']
        clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
        bar = dict(at='2026-10-06T14:10:00Z', open=target, high=target+.2, low=target-.2, close=target)
        engine.process_bar('TEST', bar)
        closed = state()
        engine.initialize_runtime()
        engine.process_bar('TEST', bar)
        assert state() == closed
        assert len(rows('SELECT id FROM scanner_fills')) == 2
        assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [{'status': 'closed', 'remaining_quantity': 0}]
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        stable = state()
        with pytest.raises(ValueError, match='already_imported'):
            recovery.restore(decoded, destination, 'synthetic-entry-recovery-token-32-characters')
        assert state() == stable


def test_pg_close_hold_keeps_separate_closing_and_entry_audits_encrypted(
        entry_pg, clock, monkeypatch, tmp_path):
    import recovery_state as recovery
    from test_recovery_holds import state, target_schema
    entry_package, closing_package, entry, quote = seed_close_hold(monkeypatch, clock)
    before = state()
    exported = recovery.export_postgres(entry_pg)
    assert exported['version'] == exported['recovery_format'] == 8
    decoded = encrypt_roundtrip(exported, tmp_path)
    close_order = next(row for row in decoded['tables']['scanner_orders'] if row['purpose'] == 'close_long')
    assert json.loads(close_order['plan_json']) == {'entry_discovery': closing_package}
    assert json.loads(decoded['tables']['scanner_trades'][0]['settings_json'])['entry_discovery'] == entry_package
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    with target_schema(entry_pg) as destination:
        recovery.restore(decoded, destination, 'synthetic-close-recovery-token-32-characters')
        assert state() == before
        engine.initialize_runtime()
        engine.process_bar('TEST', entry)
        assert state() == before
        # A retained close hold is not an executable pending SELL after restore.
        clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
        engine.process_bar('TEST', dict(at='2026-10-06T14:10:00Z', open=quote,
            high=quote+.2, low=quote-.1, close=quote))
        assert rows("SELECT status FROM scanner_orders WHERE purpose='close_long'") == [{'status': 'recovery_uncertain'}]
        assert len(rows('SELECT id FROM scanner_fills')) == 1


def test_pg_different_order_audit_cannot_be_sanitized_into_valid_snapshot(entry_pg, clock, monkeypatch):
    import recovery_state as recovery
    _, _, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    scanner.run_scan()
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=quote,
        high=quote+.2, low=quote-.1, close=quote))
    exported = recovery.export_postgres(entry_pg)
    broken = copy.deepcopy(exported)
    order = broken['tables']['scanner_orders'][0]
    contract = json.loads(order['plan_json'])
    contract['entry_discovery']['detections'][0]['score'] = .123456
    order['plan_json'] = json.dumps(contract)
    with pytest.raises(ValueError, match='order_discovery_attribution_mismatch|entry_strategy_execution_contract_invalid'):
        recovery.sanitize(broken)


def test_pg_future_audit_after_signal_creation_cannot_restore(entry_pg, clock, monkeypatch):
    from datetime import timedelta
    import recovery_state as recovery
    from test_entry_strategies import DECISION
    _, _, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    scanner.run_scan()
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=quote,
        high=quote+.2, low=quote-.1, close=quote))
    exported = recovery.export_postgres(entry_pg)
    broken = copy.deepcopy(exported)
    future = (DECISION + timedelta(seconds=1)).isoformat()
    for table, field in (('scanner_signals', 'technical_json'), ('scanner_orders', 'plan_json'),
                         ('scanner_trades', 'settings_json')):
        for row in broken['tables'][table]:
            material = json.loads(row[field])
            material['entry_discovery']['detected_at'] = future
            for record in material['entry_discovery']['detections']:
                record['source_times']['decision_at'] = future
            row[field] = json.dumps(material)
    with pytest.raises(ValueError, match='future_discovery_attribution'):
        recovery.sanitize(broken)


def test_pg_blocked_frozen_price_age_restore_bridge_keeps_uncertain_reservation(
        entry_pg, clock, monkeypatch, tmp_path):
    import entry_discovery_capabilities as capabilities
    import entry_strategy_execution as execution
    import recovery_state as recovery
    from test_recovery_holds import state, target_schema
    prepare_route(monkeypatch, clock, 'RELATIVE_STRENGTH_LEADER')
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    bad = dict(at='2026-10-06T14:05:00Z', open=100.8, high=100.9, low=100.7, close=100.8)
    engine.process_bar('TEST', bad)
    # Active recovery intentionally includes open trades and uncertainty holds,
    # not ordinary pending orders. A missing later bar must first retain a hold;
    # the snapshot contract is NOT expanded to smuggle pending orders through.
    engine._pending_recovery_check('TEST', [], datetime(2026, 10, 6, 14, 20, tzinfo=timezone.utc))
    before = state()
    saved_order = rows('SELECT * FROM scanner_orders')[0]
    contract = json.loads(saved_order['plan_json'])
    assert saved_order['status'] == 'recovery_uncertain' and execution.OBSERVATION_KEY in contract
    data = recovery.export_postgres(entry_pg)
    assert data['version'] == data['recovery_format'] == 8
    decoded = encrypt_roundtrip(data, tmp_path)
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    monkeypatch.setattr(capabilities, 'BUILD_ROLE', 'bridge')
    with target_schema(entry_pg) as destination:
        recovery.restore(decoded, destination, 'synthetic-guard-restore-token-at-least-32-characters')
        assert state() == before
        restored = rows('SELECT * FROM scanner_orders')[0]
        assert restored['plan_json'] == saved_order['plan_json']
        assert json.loads(restored['plan_json'])[execution.OBSERVATION_KEY]['reason'] == 'strategy_fill_below_support'
        assert execution.public_wait(restored) is None  # no misleading executable wait for a hold
        engine.initialize_runtime()
        engine.process_bar('TEST', bad)
        assert state() == before and rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'] == saved_order['plan_json']
        clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
        good = dict(at='2026-10-06T14:10:00Z', open=102, high=102.1, low=101.9, close=102)
        engine.process_bar('TEST', good)
        assert rows('SELECT status FROM scanner_orders') == [{'status': 'recovery_uncertain'}]
        assert not rows('SELECT id FROM scanner_fills') and not rows('SELECT id FROM scanner_trades')
        after = state()
        engine.initialize_runtime()
        engine.process_bar('TEST', good)
        assert state() == after


@pytest.mark.parametrize('exit_strategy', ('single', 'staged'))
def test_pg_new_v1_frozen_guard_age_restore_keeps_native_shadow_and_targets(
        entry_pg, clock, monkeypatch, tmp_path, exit_strategy):
    import entry_discovery_capabilities as capabilities
    import recovery_state as recovery
    from test_recovery_holds import state, target_schema
    frame, _, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    frame.iloc[133, frame.columns.get_loc('High')] = 150
    frame.iloc[137, frame.columns.get_loc('High')] = 160
    monkeypatch.setenv('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED', 'false')
    engine.set_active_strategy(exit_strategy)
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=quote,
        high=quote+.1, low=quote-.1, close=quote))
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    contract = json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    assert contract['target_plan']['method'] == 'confirmed_daily_swing_zones_v1'
    before = state()
    decoded = encrypt_roundtrip(recovery.export_postgres(entry_pg), tmp_path)
    assert decoded['version'] == decoded['recovery_format'] == 8
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    monkeypatch.setattr(capabilities, 'BUILD_ROLE', 'bridge')
    with target_schema(entry_pg) as destination:
        recovery.restore(decoded, destination, 'synthetic-v1-restore-token-at-least-32-characters')
        engine.initialize_runtime()
        assert state() == before
        trades = rows('SELECT * FROM scanner_trades')
        assert {row['strategy'] for row in trades} == {'single', 'staged'}
        assert next(row['strategy'] for row in trades if not row['is_shadow']) == exit_strategy
        assert all(json.loads(row['settings_json'])['target_plan'] == contract['target_plan'] for row in trades)
        target = contract['target_plan']['targets'][0]
        clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
        exit_bar = dict(at='2026-10-06T14:10:00Z', open=target, high=target+.1, low=target-.1, close=target)
        engine.process_bar('TEST', exit_bar)
        assert len(rows('SELECT id FROM scanner_fills')) > 2
        after = state()
        engine.initialize_runtime()
        engine.process_bar('TEST', exit_bar)
        assert state() == after and engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
