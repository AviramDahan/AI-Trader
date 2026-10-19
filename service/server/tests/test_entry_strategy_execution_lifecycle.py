"""New frozen setup guards in the existing isolated LIMIT/full-bar lifecycle."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import entry_discovery
import entry_discovery_capabilities as capabilities
import entry_strategy_execution as execution
import scanner_engine as engine
import scanner_targets
import stock_scanner as scanner
from test_entry_strategy_execution import package_for
from test_entry_strategies import DECISION
from test_entry_strategies_integration import prepare_route
from test_signal_inputs import db, clock
from test_signal_admission_chain import rows, prepare
from test_single_target_v2 import zone


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('synthetic execution controls prohibit external IO')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)


def order():
    return rows("SELECT * FROM scanner_orders WHERE purpose='entry' ORDER BY id")[0]


def balance():
    return rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')


def bar(minute=5, opening=100.8):
    return dict(at=f'2026-10-06T14:{minute:02d}:00Z', open=opening,
        high=opening+.2, low=opening-.2, close=opening+.05)


def setup_rs(monkeypatch, clock):
    prepare_route(monkeypatch, clock, 'RELATIVE_STRENGTH_LEADER')
    assert scanner.run_scan()['signals_published'] == 1
    original = copy.deepcopy(json.loads(order()['plan_json']))
    assert original[execution.KEY]['branches'][0]['support'] == pytest.approx(100.85)
    assert original['target_plan']['entry'] == 102
    return original


def process(clock, candle, observed=None):
    clock.instant = observed or datetime(2026, 10, 6, 14, 30, tzinfo=timezone.utc)
    engine.process_bar('TEST', candle)


def test_rs_below_pivot_declines_then_later_legal_original_fill_once_flags_off_bridge(db, clock, monkeypatch):
    original = setup_rs(monkeypatch, clock)
    before = balance()
    process(clock, bar())
    saved = json.loads(order()['plan_json'])
    assert order()['status'] == 'pending' and order()['filled_quantity'] == 0
    assert balance() == before and not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')
    assert saved[execution.KEY] == original[execution.KEY]
    assert saved['target_plan'] == original['target_plan']
    assert saved[execution.OBSERVATION_KEY]['reason'] == 'strategy_fill_below_support'
    assert engine.dashboard_payload()['signals'][0]['entry_price_wait']['reason'] == 'strategy_fill_below_support'
    assert 'last_entry_price_block' not in saved
    technical = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
    assert technical[execution.KEY] == original[execution.KEY]
    for flag in entry_discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    monkeypatch.setattr(capabilities, 'BUILD_ROLE', 'bridge')
    engine.initialize_runtime()
    good = bar(10, 101.0)
    process(clock, good)
    engine.initialize_runtime()
    process(clock, good)
    assert order()['status'] == 'filled' and len(rows('SELECT id FROM scanner_fills')) == 1
    trade = rows('SELECT * FROM scanner_trades')[0]
    assert 100.85 < trade['entry_price'] <= 102
    assert trade['original_stop'] == original['target_plan']['stop']
    assert trade['tp1'] == original['target_plan']['active_target']
    assert json.loads(trade['settings_json'])[execution.KEY] == original[execution.KEY]
    assert execution.public_wait(order()) is None
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


def test_rejected_touch_cannot_hide_a_later_missing_bar_or_release_uncertainty_hold(db, clock, monkeypatch):
    setup_rs(monkeypatch, clock)
    before = balance()
    bad, later = bar(), bar(15, 101.0)
    clock.instant = datetime(2026, 10, 6, 14, 20, tzinfo=timezone.utc)
    # The first observed low is NOT a possible fill: it failed the frozen pivot.
    # The missing14:10 candle therefore remains unresolved, not ignored as post-fill.
    engine._pending_recovery_check('TEST', [bad, later], clock.instant)
    assert order()['status'] == 'recovery_uncertain'
    assert rows("SELECT COUNT(*) n FROM scanner_orders WHERE status='recovery_uncertain'")[0]['n'] == 1
    process(clock, later)
    engine._expire_recovered_orders('TEST', DECISION+timedelta(days=3))
    assert order()['status'] == 'recovery_uncertain' and balance() == before
    assert not rows('SELECT id FROM scanner_fills')


def test_normal_expiry_after_rejections_keeps_levels_and_does_not_fill_retroactively(db, clock, monkeypatch):
    prepare_route(monkeypatch, clock, 'RELATIVE_STRENGTH_LEADER')
    cfg = engine.lifecycle_settings() | {'signal_validity_hours': .25}
    monkeypatch.setattr(engine, 'lifecycle_settings', lambda: cfg)
    assert scanner.run_scan()['signals_published'] == 1
    initial = copy.deepcopy(order())
    before = balance()
    process(clock, bar(5), datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc))
    process(clock, bar(10), datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc))
    engine._expire_recovered_orders('TEST', datetime(2026, 10, 6, 14, 16, tzinfo=timezone.utc))
    assert order()['status'] == 'expired' and order()['valid_until'] == initial['valid_until']
    process(clock, bar(15, 101.0))
    assert balance() == before and not rows('SELECT id FROM scanner_fills')
    assert json.loads(order()['plan_json'])[execution.KEY] == json.loads(initial['plan_json'])[execution.KEY]


@pytest.mark.parametrize('damage', ['unknown_version', 'branch', 'observation', 'signal_association'])
def test_new_malformed_contract_never_fills_or_debits(db, clock, monkeypatch, damage):
    setup_rs(monkeypatch, clock)
    before = balance()
    with database.get_db_connection() as conn:
        saved = json.loads(order()['plan_json'])
        if damage == 'unknown_version': saved[execution.KEY]['version'] = 'future_v999'
        if damage == 'branch': saved[execution.KEY]['branches'][0]['support'] -= 1
        if damage == 'observation': saved[execution.OBSERVATION_KEY] = {}
        if damage == 'signal_association':
            technical = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
            technical[execution.KEY]['audit_digest'] = 'a'*64
            conn.execute('UPDATE scanner_signals SET technical_json=?', (json.dumps(technical),))
        else:
            conn.execute('UPDATE scanner_orders SET plan_json=?', (json.dumps(saved),))
        conn.commit()
    process(clock, bar(5, 101.0))
    assert order()['status'] in {'invalid', 'recovery_uncertain'}
    assert balance() == before and not rows('SELECT id FROM scanner_fills')


def test_prefeature_audit_only_order_keeps_prior_passive_limit_behavior(db, clock, monkeypatch):
    setup_rs(monkeypatch, clock)
    # Model a retained204ad61 order: that binary never emitted the NEW key on
    # any node. Audit-only metadata alone is explicitly not an execution policy.
    with database.get_db_connection() as conn:
        contract = json.loads(order()['plan_json'])
        del contract[execution.KEY]
        conn.execute('UPDATE scanner_orders SET plan_json=?', (json.dumps(contract),))
        technical = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
        del technical[execution.KEY]
        conn.execute('UPDATE scanner_signals SET technical_json=?', (json.dumps(technical),))
        conn.commit()
    process(clock, bar())
    assert order()['status'] == 'filled'
    assert rows('SELECT entry_price FROM scanner_trades')[0]['entry_price'] < 100.85
    assert execution.KEY not in json.loads(rows('SELECT settings_json FROM scanner_trades')[0]['settings_json'])


def test_new_staged_v1_guard_uses_complete_bar_and_saved_settings_without_global_v2(db, clock, monkeypatch):
    prepare(monkeypatch, clock)
    clock.instant = DECISION
    monkeypatch.setenv(entry_discovery.FLAGS['RELATIVE_STRENGTH_LEADER'], 'true')
    monkeypatch.setenv('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED', 'false')
    monkeypatch.setenv('STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED', 'false')
    monkeypatch.setenv('STOCK_SCANNER_EXIT_STRATEGY', 'staged')
    engine.initialize_runtime()
    package = package_for()
    plan = scanner_targets.structure_plan('BUY', 102, 1,
        [zone(99, 99.2), zone(106, 106.4), zone(110, 110.4), zone(115, 115.4)], 2)
    signal = dict(ticker='TEST', company='Synthetic', action='BUY', entry=102, stop_loss=plan['stop'],
        target_plan=plan, confidence=.91, quote_at=DECISION.isoformat(),
        time_horizon='1-4 weeks', reason='Synthetic independent legacy exit', relevant_news=[])
    result = engine.record_signal(signal, dict(entry_discovery=package), {}, {}, 'synthetic-independent-v1')
    assert result['status'] == 'PENDING_ENTRY'
    saved = json.loads(order()['plan_json'])
    assert saved['entry_execution']['entry_eligible_from'] == '2026-10-06T14:05:00+00:00'
    assert saved['execution_settings']['active_strategy'] == 'staged'
    before = balance()
    process(clock, bar(), datetime(2026, 10, 6, 14, 7, tzinfo=timezone.utc))
    assert order()['status'] == 'pending' and execution.OBSERVATION_KEY not in json.loads(order()['plan_json'])
    assert not rows('SELECT id FROM scanner_fills') and balance() == before
    process(clock, bar(), datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc))
    assert execution.OBSERVATION_KEY in json.loads(order()['plan_json'])
    monkeypatch.setenv('STOCK_SCANNER_EXIT_STRATEGY', 'single')
    process(clock, bar(10, 101.0))
    assert order()['status'] == 'filled'
    trades = rows('SELECT strategy,is_shadow,settings_json FROM scanner_trades ORDER BY is_shadow')
    assert [(t['strategy'], t['is_shadow']) for t in trades] == [('staged', 0), ('single', 1)]
    assert all(json.loads(t['settings_json'])[execution.KEY] == saved[execution.KEY] for t in trades)
    assert all(json.loads(t['settings_json'])['target_plan'] == plan for t in trades)
