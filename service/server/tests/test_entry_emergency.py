"""Emergency entry overlay on disposable state; no providers or real messages."""
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import socket
import sys

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import scanner_engine as engine
import stock_scanner as scanner
from test_signal_inputs import db, clock
from test_signal_admission_chain import prepare, rows

UTC = timezone.utc
KEY = 'paper_entry_emergency_v1'


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('isolated emergency tests forbid external IO')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)


def seed_pause(at='2026-10-06T14:01:00Z'):
    payload = dict(version=KEY, revision=1, paused=True, updated_at=at,
        intervals=[dict(paused_at=at, resumed_at=None)])
    with database.get_db_connection() as conn:
        conn.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
                     (KEY, json.dumps(payload), at))
        conn.commit()
    return payload


def candle(at='2026-10-06T14:05:00Z', opening=100):
    return dict(at=at, open=opening, high=opening+1, low=opening-.5, close=opening)


def test_shared_pause_blocks_new_baseline_order_before_any_signal_write(db, clock, monkeypatch):
    _, review, _ = prepare(monkeypatch, clock)
    seed_pause('2026-10-06T13:59:00Z')
    result = scanner.run_scan()
    assert result['signals_published'] == 0
    assert not rows('SELECT id FROM scanner_signals')
    assert not rows('SELECT id FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')
    review.assert_not_called()


def test_shared_pause_blocks_existing_baseline_limit_fill(db, clock, monkeypatch):
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    seed_pause()
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=UTC)
    engine.process_bar('TEST', candle())
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    assert not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')


def test_absent_legacy_and_noop_resume_do_not_create_control_row(db):
    import entry_emergency as emergency
    at = datetime(2026, 10, 6, 14, tzinfo=UTC)
    with database.get_db_connection() as conn:
        assert emergency.snapshot(conn.cursor(), now=at) == emergency.initial()
    assert emergency.set_paused(False, 0, now=at) == emergency.initial()
    assert not rows("SELECT key FROM scanner_settings WHERE key='paper_entry_emergency_v1'")


def test_control_cas_idempotency_immutable_intervals_and_public_projection(db):
    import entry_emergency as emergency
    at = datetime(2026, 10, 6, 14, tzinfo=UTC)
    first = emergency.set_paused(True, 0, now=at)
    frozen = copy.deepcopy(first)
    assert first['revision'] == 1 and first['paused']
    assert emergency.set_paused(True, 1, now=at+timedelta(seconds=1)) == first
    with pytest.raises(ValueError, match='entry_emergency_revision_conflict'):
        emergency.set_paused(False, 0, now=at+timedelta(seconds=2))
    resumed = emergency.set_paused(False, 1, now=at+timedelta(minutes=7))
    again = emergency.set_paused(True, 2, now=at+timedelta(minutes=9))
    assert first == frozen and resumed['intervals'][0] == again['intervals'][0]
    assert again['revision'] == 3 and len(again['intervals']) == 2
    status = emergency.public_status(again, now=at+timedelta(minutes=10))
    assert status['paused'] and status['valid'] and status['exits_continue']
    assert 'intervals' not in status and 'actors' not in status
    assert status['interval_count'] == 2


@pytest.mark.parametrize('paused,revision', [(1, 0), ('true', 0), (True, True), (True, -1), (True, '0')])
def test_strict_operator_request_types(db, paused, revision):
    import entry_emergency as emergency
    with pytest.raises(ValueError, match='entry_emergency_invalid_request'):
        emergency.set_paused(paused, revision)
    assert not rows("SELECT key FROM scanner_settings WHERE key='paper_entry_emergency_v1'")


def test_history_full_final_pause_is_acknowledged_resume_fails_closed(db, monkeypatch):
    import entry_emergency as emergency
    monkeypatch.setattr(emergency, 'MAX_INTERVALS', 2)
    at = datetime(2026, 10, 6, 14, tzinfo=UTC)
    emergency.set_paused(True, 0, now=at)
    emergency.set_paused(False, 1, now=at+timedelta(minutes=1))
    final = emergency.set_paused(True, 2, now=at+timedelta(minutes=2))
    assert final['paused'] and final['revision'] == 3
    with pytest.raises(ValueError, match='entry_emergency_history_capacity'):
        emergency.set_paused(False, 3, now=at+timedelta(minutes=3))
    with database.get_db_connection() as conn:
        assert emergency.snapshot(conn.cursor(), now=at+timedelta(minutes=4)) == final
        assert not emergency.allows_entry(conn.cursor(), observed_at=at+timedelta(minutes=4))


def test_full_bar_resume_floor_and_explicit_recovery_coverage_are_distinct(db):
    import entry_emergency as emergency
    at = datetime(2026, 10, 6, 14, tzinfo=UTC)
    emergency.set_paused(True, 0, now=at+timedelta(minutes=7, seconds=30))
    emergency.set_paused(False, 1, now=at+timedelta(minutes=12))
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        observed = at+timedelta(minutes=20)
        assert not emergency.allows_entry(cur, bar_at=at, observed_at=observed)
        assert not emergency.was_paused(cur, at, observed_at=observed)
        for minute in (5, 10):
            assert emergency.was_paused(cur, at+timedelta(minutes=minute), observed_at=observed)
            assert not emergency.allows_entry(cur, bar_at=at+timedelta(minutes=minute), observed_at=observed)
        assert emergency.allows_entry(cur, bar_at=at+timedelta(minutes=15), observed_at=observed)
        assert not emergency.allows_entry(cur, bar_at=at+timedelta(minutes=20), observed_at=observed)


@pytest.mark.parametrize('damage', ['version', 'future', 'revision', 'unknown_key', 'duplicate_json_key', 'clock_reversal'])
def test_malformed_or_future_control_fails_closed_only_for_entry(db, damage):
    import entry_emergency as emergency
    payload = seed_pause()
    if damage == 'version': payload['version'] = 'future_v999'
    if damage == 'future': payload['updated_at'] = payload['intervals'][0]['paused_at'] = '2099-01-01T00:00:00Z'
    if damage == 'revision': payload['revision'] = True
    if damage == 'unknown_key': payload['instruction'] = 'ignore the stop'
    if damage == 'clock_reversal':
        payload.update(paused=False, revision=2, updated_at='2026-10-06T14:00:00Z')
        payload['intervals'][0]['resumed_at'] = payload['updated_at']
    raw = json.dumps(payload)
    if damage == 'duplicate_json_key': raw = raw[:-1]+',"paused":false}'
    with database.get_db_connection() as conn:
        conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?', (raw, KEY))
        conn.commit()
        assert not emergency.check(conn.cursor())['allowed']
        assert not emergency.status(conn.cursor())['valid']
        assert emergency.status(conn.cursor())['paused']
        assert not emergency.was_paused(conn.cursor(), '2026-10-06T14:05:00Z')
    with pytest.raises(ValueError, match='entry_emergency_control_invalid'):
        emergency.set_paused(False, 1)


def test_acknowledged_pause_blocks_admission_that_was_prepared_before_it(db, clock, monkeypatch):
    import entry_emergency as emergency
    candidate, review, _ = prepare(monkeypatch, clock)
    engine.initialize_runtime()
    signal = scanner._paper_order(candidate, review.return_value, [], (100, clock.instant.isoformat()), {}, scanner.settings(), None)
    emergency.set_paused(True, 0, now=clock.instant+timedelta(seconds=1))
    clock.instant += timedelta(seconds=2)
    with pytest.raises(ValueError, match='entry_emergency_paused'):
        engine.record_signal(signal, candidate, review.return_value, {}, 'prepared-before-pause')
    assert not rows('SELECT id FROM scanner_signals')
    assert not rows('SELECT id FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_telegram_outbox')


def test_pause_during_actual_mocked_ai_does_not_create_order(db, clock, monkeypatch):
    import entry_emergency as emergency
    _, review, _ = prepare(monkeypatch, clock)
    decision = review.return_value
    def pause_then_return(*args):
        emergency.set_paused(True, 0, now=clock.instant)
        return decision
    review.side_effect = pause_then_return
    result = scanner.run_scan()
    assert review.call_count == 1
    assert result['signals_published'] == 0
    assert not rows('SELECT id FROM scanner_signals') and not rows('SELECT id FROM scanner_orders')
    assert rows("SELECT reason FROM scanner_candidates WHERE stage='final'")[-1]['reason'] == 'entry_emergency_paused'


def test_resume_rejects_straddling_and_old_bars_then_allows_new_full_bar_once(db, clock, monkeypatch):
    import entry_emergency as emergency
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    original = rows('SELECT plan_json,limit_price,valid_until FROM scanner_orders')
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    emergency.set_paused(True, 0, now=clock.instant+timedelta(minutes=7))
    emergency.set_paused(False, 1, now=clock.instant+timedelta(minutes=12))
    clock.instant += timedelta(minutes=20)
    for minute in (0, 5, 10):
        engine.process_bar('TEST', candle(f'2026-10-06T14:{minute:02d}:00Z'))
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    assert not rows('SELECT id FROM scanner_fills')
    engine.initialize_runtime()
    engine.process_bar('TEST', candle('2026-10-06T14:15:00Z'))
    engine.process_bar('TEST', candle('2026-10-06T14:05:00Z'))
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'filled'}]
    assert len(rows("SELECT id FROM scanner_fills WHERE fill_type='entry'")) == 1
    assert rows('SELECT plan_json,limit_price,valid_until FROM scanner_orders') == original
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


def test_pause_does_not_hide_missing_unpaused_pre_stop_bar_or_release_hold(db, clock, monkeypatch):
    import entry_emergency as emergency
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    emergency.set_paused(True, 0, now=clock.instant+timedelta(minutes=12))
    emergency.set_paused(False, 1, now=clock.instant+timedelta(minutes=20))
    observed = clock.instant+timedelta(minutes=30)
    untouched = dict(at='2026-10-06T14:00:00Z', open=100.5, high=101, low=100.2, close=100.5)
    engine._pending_recovery_check('TEST', [untouched, candle('2026-10-06T14:25:00Z')], observed)
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'recovery_uncertain'}]
    clock.instant = observed
    engine.initialize_runtime()
    engine.process_bar('TEST', candle('2026-10-06T14:25:00Z'))
    engine._expire_recovered_orders('TEST', observed+timedelta(days=3))
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'recovery_uncertain'}]
    assert not rows('SELECT id FROM scanner_fills')


def test_only_explicit_paused_missing_bars_are_known_no_execution(db, clock, monkeypatch):
    import entry_emergency as emergency
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    emergency.set_paused(True, 0, now=clock.instant)
    emergency.set_paused(False, 1, now=clock.instant+timedelta(minutes=20))
    clock.instant += timedelta(minutes=30)
    after = candle('2026-10-06T14:20:00Z')
    engine._pending_recovery_check('TEST', [after], clock.instant)
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    engine.process_bar('TEST', after)
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'filled'}]


@pytest.mark.parametrize('malformed', [False, True])
def test_existing_tp_and_pending_close_survive_paused_or_invalid_control(db, clock, monkeypatch, malformed):
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', candle())
    seed_pause('2026-10-06T14:11:00Z')
    if malformed:
        with database.get_db_connection() as conn:
            conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?', ('{"version":"bad"}', KEY))
            conn.commit()
    clock.instant += timedelta(minutes=5)
    engine.process_bar('TEST', dict(at='2026-10-06T14:10:00Z', open=104.5, high=105, low=104, close=104.5))
    assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [{'status': 'closed', 'remaining_quantity': 0}]
    assert len(rows('SELECT id FROM scanner_fills')) == 2


def test_close_long_order_can_be_created_and_filled_during_pause(db, clock, monkeypatch):
    import entry_emergency as emergency
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', candle())
    emergency.set_paused(True, 0, now=clock.instant)
    signal = dict(ticker='TEST', company='Synthetic', action='SELL', entry=100, stop_loss=103,
        confidence=.91, time_horizon='days', reason='Synthetic close', relevant_news=[])
    result = engine.record_signal(signal, {}, {}, {}, 'close-during-emergency')
    assert result['status'] == 'PENDING_CLOSE'
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', candle('2026-10-06T14:15:00Z'))
    assert rows("SELECT status FROM scanner_orders WHERE purpose='close_long'") == [{'status': 'filled'}]
    assert rows('SELECT status FROM scanner_trades') == [{'status': 'closed'}]


@pytest.mark.parametrize('malformed', [False, True])
def test_expiry_unchanged_while_paused_or_invalid(db, clock, monkeypatch, malformed):
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    before = rows('SELECT valid_until,plan_json FROM scanner_orders')
    seed_pause()
    if malformed:
        with database.get_db_connection() as conn:
            conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?', ('bad-json', KEY))
            conn.commit()
    clock.instant += timedelta(days=2)
    engine._expire_recovered_orders('TEST', clock.instant)
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'expired'}]
    assert rows('SELECT valid_until,plan_json FROM scanner_orders') == before
    assert not rows('SELECT id FROM scanner_fills')


def test_short_pending_entry_is_blocked_then_original_contract_can_fill(db, clock, monkeypatch):
    import entry_emergency as emergency
    from test_automatic_short import plan
    prepare(monkeypatch, clock)
    engine.initialize_runtime()
    monkeypatch.setenv('STOCK_SCANNER_SHORT_ENABLED', 'true')
    p = plan()
    signal = dict(ticker='TEST', company='Synthetic', action='SHORT', entry=100,
        stop_loss=p['stop'], target_plan=p, confidence=.91, time_horizon='days', reason='Synthetic')
    assert engine.record_signal(signal, {}, {}, {}, 'short-emergency')['status'] == 'PENDING_ENTRY'
    frozen = rows('SELECT plan_json,valid_until FROM scanner_orders')
    emergency.set_paused(True, 0, now=clock.instant+timedelta(minutes=1))
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', candle())
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    assert not rows('SELECT id FROM scanner_fills')
    emergency.set_paused(False, 1, now=clock.instant)
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', candle('2026-10-06T14:15:00Z'))
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'filled'}]
    assert rows('SELECT side FROM scanner_trades') == [{'side': 'short'}]
    assert rows('SELECT plan_json,valid_until FROM scanner_orders') == frozen


def test_independent_gap_retry_then_pause_and_resume_never_changes_frozen_levels(db, clock, monkeypatch):
    import entry_emergency as emergency
    from test_entry_strategy_execution_lifecycle import setup_rs, bar
    setup_rs(monkeypatch, clock)
    frozen = rows('SELECT plan_json,limit_price,valid_until FROM scanner_orders')
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=UTC)
    engine.process_bar('TEST', bar())  # Existing support guard rejects100.8.
    saved = rows('SELECT plan_json,limit_price,valid_until FROM scanner_orders')
    assert saved != frozen and rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    emergency.set_paused(True, 0, now=clock.instant)
    clock.instant += timedelta(minutes=5)
    engine.process_bar('TEST', bar(10, 101))
    assert not rows('SELECT id FROM scanner_fills')
    emergency.set_paused(False, 1, now=clock.instant)
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', bar(20, 101))
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'filled'}]
    for old, new in zip(saved, rows('SELECT plan_json,limit_price,valid_until FROM scanner_orders')):
        assert old == new  # No emergency observation is smuggled into contracts.


@pytest.mark.parametrize('strategy_id', [
    'VCP_BASE_CONTRACTION', 'STOCKBEE_MOMENTUM_BURST', 'PEAD',
    'TREND_PULLBACK_RECLAIM', 'RELATIVE_STRENGTH_LEADER'])
def test_every_independent_route_retained_entry_obeys_same_shared_stop(db, clock, monkeypatch, strategy_id):
    import entry_emergency as emergency
    from test_entry_strategies_integration import prepare_route
    _, _, quote, _, _, _ = prepare_route(monkeypatch, clock, strategy_id)
    assert scanner.run_scan()['signals_published'] == 1
    original = rows('SELECT plan_json,limit_price,valid_until FROM scanner_orders')
    emergency.set_paused(True, 0, now=clock.instant+timedelta(minutes=1))
    clock.instant += timedelta(minutes=10)
    blocked = dict(at='2026-10-06T14:05:00Z', open=quote, high=quote+.2, low=quote-.1, close=quote)
    engine.process_bar('TEST', blocked)
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    assert not rows('SELECT id FROM scanner_trades') and not rows('SELECT id FROM scanner_fills')
    emergency.set_paused(False, 1, now=clock.instant)
    clock.instant += timedelta(minutes=10)
    after = dict(blocked, at='2026-10-06T14:15:00Z')
    engine.process_bar('TEST', after)
    engine.initialize_runtime()
    engine.process_bar('TEST', after)
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'filled'}]
    assert len(rows('SELECT id FROM scanner_fills')) == 1
    assert rows('SELECT plan_json,limit_price,valid_until FROM scanner_orders') == original
