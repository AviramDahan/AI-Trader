"""Only synthetic detector/contract prices; no live IO or orders."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import entry_discovery
import entry_discovery_capabilities as capabilities
import entry_strategy_execution as execution
import entry_strategies
import entry_window
import single_target_policy
from test_entry_strategies import fixture_case, DECISION, OBSERVED
from test_single_target_v2 import zone


def package_for(strategy_id='RELATIVE_STRENGTH_LEADER'):
    frame, context, decision, observed = fixture_case(strategy_id)
    if strategy_id == 'RELATIVE_STRENGTH_LEADER':
        frame['High'] += .65
        frame['Low'] -= .65
    elif strategy_id == 'TREND_PULLBACK_RECLAIM':
        frame.iloc[-2, frame.columns.get_loc('High')] = 102.5
    record = entry_strategies.detect_all(frame, decision_at=decision,
        source_observed_at=observed, enabled_ids=[strategy_id], context=context)[strategy_id]
    assert record['state'] == 'DETECTED', record
    return entry_discovery.attribution([record], decision)


def contract_for(strategy_id='RELATIVE_STRENGTH_LEADER'):
    package = package_for(strategy_id)
    price = package['detections'][0]['entry_reference']['price']
    until = (DECISION+timedelta(days=1)).isoformat()
    window = entry_window.build(DECISION, until)
    saved = execution.build(package, created_at=DECISION, valid_until=until,
        limit_price=price, quote_at=DECISION, entry_execution=window)
    plan = single_target_policy.build(price, 1, [zone(price-3, price-2.8),
        zone(price+8, price+8.4)], '2026-10-05', DECISION.isoformat())
    contract = dict(entry_discovery=package, entry_strategy_execution=saved,
        target_plan=plan, execution_settings=dict(active_strategy='single', entry_order_type='limit',
            slippage_bps=0, minimum_commission=.25, commission_per_share=.005),
        entry_execution=window)
    order = dict(purpose='entry', side='buy', order_type='limit', limit_price=price,
        created_at=DECISION.isoformat(), updated_at=DECISION.isoformat(), valid_until=until,
        status='pending', plan_json=json.dumps(contract))
    signal = dict(action='BUY', planned_entry=price, original_stop=plan['stop'],
        tp1=plan['active_target'], tp2=None, tp3=None, tp1_pct=1, tp2_pct=0, tp3_pct=0,
        created_at=DECISION.isoformat(), valid_until=until,
        technical_json=json.dumps(dict(entry_discovery=package, entry_strategy_execution=saved,
                                      target_plan=plan)))
    return order, contract, signal


@pytest.mark.parametrize('strategy_id', entry_strategies.STRATEGY_IDS)
def test_build_order_actual_fill_and_audit_association_each_route(strategy_id):
    order, contract, signal = contract_for(strategy_id)
    frozen = copy.deepcopy(contract)
    assert execution.validate_order(order, contract, signal=signal)
    assert execution.validate_fill(contract[execution.KEY], order['limit_price']) == [strategy_id]
    assert execution.validate_association(contract['entry_discovery'], contract[execution.KEY]) == contract[execution.KEY]
    assert contract == frozen


@pytest.mark.parametrize('strategy_id', [sid for sid in entry_strategies.STRATEGY_IDS if sid != 'TREND_PULLBACK_RECLAIM'])
def test_breakout_routes_reject_actual_price_at_or_below_frozen_pivot(strategy_id):
    _, contract, _ = contract_for(strategy_id)
    saved = contract[execution.KEY]
    pivot = saved['branches'][0]['support']
    for price in (pivot, pivot-.01):
        with pytest.raises(ValueError, match='strategy_fill_below_support'):
            execution.validate_fill(saved, price)
    assert execution.validate_fill(saved, pivot+.01) == [strategy_id]


def test_rs_regression_original_v2_accepts100_8_new_pivot100_85_declines():
    order, contract, _ = contract_for()
    assert order['limit_price'] == 102
    assert contract[execution.KEY]['branches'][0]['support'] == pytest.approx(100.85)
    assert single_target_policy.validate_fill(contract['target_plan'], 100.8) >= 2
    with pytest.raises(ValueError, match='strategy_fill_below_support'):
        execution.validate_fill(contract[execution.KEY], 100.8)


def test_pullback_allows_retest_below_reclaim_trigger_only_above_frozen_ema():
    _, contract, _ = contract_for('TREND_PULLBACK_RECLAIM')
    saved = contract[execution.KEY]
    record = contract['entry_discovery']['detections'][0]
    branch = saved['branches'][0]
    assert branch['support'] == record['features']['ema20']
    assert branch['rule'] == 'CONFIRMED_RECLAIM_THEN_ABOVE_EMA20'
    price = (branch['support'] + record['trigger']['level']) / 2
    assert price < record['trigger']['level'] and execution.validate_fill(saved, price)
    with pytest.raises(ValueError, match='strategy_fill_below_support'):
        execution.validate_fill(saved, branch['support'])


def test_multi_strategy_is_frozen_or_not_and():
    stockbee = package_for('STOCKBEE_MOMENTUM_BURST')['detections'][0]
    rs = package_for()['detections'][0]
    package = entry_discovery.attribution([stockbee, rs], DECISION)
    saved = execution.build(package, created_at=DECISION, valid_until=DECISION+timedelta(days=1),
        limit_price=101.0, quote_at=DECISION)
    assert len(saved['branches']) == 2
    assert execution.validate_fill(saved, 100.5) == ['STOCKBEE_MOMENTUM_BURST']
    with pytest.raises(ValueError, match='strategy_fill_below_support'):
        execution.validate_fill(saved, 99)


def test_creation_admits_only_branches_whose_actual_quote_was_valid():
    stockbee = package_for('STOCKBEE_MOMENTUM_BURST')['detections'][0]
    rs = package_for()['detections'][0]
    package = entry_discovery.attribution([stockbee, rs], DECISION)
    saved = execution.build(package, created_at=DECISION, valid_until=DECISION+timedelta(days=1),
        limit_price=100.5, quote_at=DECISION)
    assert saved['admitted_ids'] == ['STOCKBEE_MOMENTUM_BURST']
    assert saved['audit_digest'] == execution._digest(package)


def test_baseline_contributor_gets_no_new_execution_contract():
    independent = package_for()['detections'][0]
    baseline = copy.deepcopy(independent)
    baseline.update(strategy_id='BASELINE', version='existing_trend_momentum_v1')
    package = entry_discovery.attribution([baseline, independent], DECISION)
    assert execution.build(package, created_at=DECISION, valid_until=DECISION+timedelta(days=1),
        limit_price=102, quote_at=DECISION) is None
    assert execution.branches_from_discovery(package) == []


def test_research_component_projection_is_optin_and_cannot_build_executable_contract():
    package = package_for()
    component = entry_discovery.attribution(package['detections'], DECISION,
        calculation_at=DECISION-timedelta(days=1))
    with pytest.raises(ValueError, match='attribution'):
        execution.branches_from_discovery(component)
    assert execution.branches_from_discovery(component, allow_component=True) == execution.branches_from_discovery(package)
    with pytest.raises(ValueError, match='attribution'):
        execution.build(component, created_at=DECISION, valid_until=DECISION+timedelta(days=1),
                        limit_price=102, quote_at=DECISION)


def test_bridge_rejects_creation_but_reads_manages_frozen_contract_with_flags_off(monkeypatch):
    order, contract, signal = contract_for()
    monkeypatch.setattr(capabilities, 'BUILD_ROLE', 'bridge')
    for flag in entry_discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    with pytest.raises(ValueError, match='disabled_in_bridge'):
        execution.build(contract['entry_discovery'], created_at=DECISION,
            valid_until=order['valid_until'], limit_price=102, quote_at=DECISION)
    assert execution.validate_order(order, contract, signal=signal)
    assert execution.validate_fill(contract[execution.KEY], 101.0)


def test_absent_contract_preserves_old_audit_only_semantics():
    order, contract, signal = contract_for()
    del contract[execution.KEY]
    technical = json.loads(signal['technical_json'])
    del technical[execution.KEY]
    signal['technical_json'] = json.dumps(technical)
    assert execution.validate_order(order, contract, signal=signal) is False
    contract[execution.OBSERVATION_KEY] = {}
    with pytest.raises(ValueError, match='contract_invalid'):
        execution.validate_order(order, contract)


def test_new_signal_guard_cannot_be_downgraded_by_dropping_order_guard():
    order, contract, signal = contract_for()
    del contract[execution.KEY]
    assert execution.KEY in json.loads(signal['technical_json'])
    with pytest.raises(ValueError, match='entry_strategy_execution_contract_invalid'):
        execution.validate_order(order, contract, signal=signal)


@pytest.mark.parametrize('damage', ['version', 'extra', 'audit', 'support', 'ids', 'order_limit',
    'window', 'signal_audit', 'signal_execution', 'target', 'null', 'purpose'])
def test_malformed_contract_and_audit_association_fail_closed(damage):
    order, contract, signal = contract_for()
    saved = contract[execution.KEY]
    if damage == 'version': saved['version'] = 'future_v99'
    if damage == 'extra': saved['anything'] = True
    if damage == 'audit': saved['audit_digest'] = 'a'*64
    if damage == 'support': saved['branches'][0]['support'] -= 1
    if damage == 'ids': saved['admitted_ids'] = ['PEAD']
    if damage == 'order_limit': order['limit_price'] -= .1
    if damage == 'window': contract['entry_execution']['entry_eligible_from'] = DECISION.isoformat()
    if damage.startswith('signal_'):
        technical = json.loads(signal['technical_json'])
        if damage == 'signal_audit': technical['entry_discovery']['primary_strategy_id'] = 'BASELINE'
        else: del technical[execution.KEY]
        signal['technical_json'] = json.dumps(technical)
    if damage == 'target': contract['target_plan']['stop'] -= .01
    if damage == 'null': contract[execution.KEY] = None
    if damage == 'purpose': order['purpose'] = 'close_long'
    with pytest.raises(ValueError, match='contract_invalid|unsupported'):
        execution.validate_order(order, contract, signal=signal)


def test_rejected_price_observation_is_immutable_monotonic_and_not_a_fill():
    order, contract, _ = contract_for()
    before = copy.deepcopy(contract)
    at, observed = '2026-10-06T14:05:00Z', '2026-10-06T14:10:00Z'
    waiting = execution.observe(order, contract, 100.8, at, observed, 'strategy_fill_below_support')
    assert contract == before
    assert waiting[execution.KEY] == before[execution.KEY]
    checked = dict(order, updated_at=observed, plan_json=json.dumps(waiting))
    assert execution.validate_order(checked, waiting)
    assert execution.public_wait(checked)['reason'] == 'strategy_fill_below_support'
    with pytest.raises(ValueError, match='contract_invalid'):
        execution.observe(checked, waiting, 100.8, at, observed, 'strategy_fill_below_support')
    for key in ('bar_at', 'observed_at', 'reason', 'price'):
        bad = copy.deepcopy(waiting)
        bad[execution.OBSERVATION_KEY][key] = dict(bar_at='2026-10-06T14:00:00Z',
            observed_at='2026-10-06T14:07:00Z', reason='invented', price=101)[key]
        with pytest.raises(ValueError, match='contract_invalid'):
            execution.validate_order(checked, bad)
