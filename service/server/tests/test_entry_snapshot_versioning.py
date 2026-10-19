"""Content-derived formats fail closed; no old data is relabeled in storage."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import single_target_recovery as recovery
from test_entry_strategy_execution import contract_for


def data_for():
    order, contract, signal = contract_for()
    signal['id'] = order['signal_id'] = 1
    order['id'] = 1
    order['plan_json'] = json.dumps(contract)
    return dict(version=8, tables=dict(scanner_signals=[signal], scanner_orders=[order], scanner_trades=[]))


def test_new_guard_requires_format8_and_no_mislabeled_older_snapshot():
    data = data_for()
    assert recovery.version(data['tables']) == 8
    recovery.validate_snapshot(data)
    for number in range(1, 8):
        with pytest.raises(ValueError, match='format_content_mismatch'):
            recovery.validate_snapshot(dict(data, version=number))


def test_audit_only_requires_format7_not_pre_release_format6():
    data = data_for()
    for table, field in (('scanner_signals', 'technical_json'), ('scanner_orders', 'plan_json')):
        value = json.loads(data['tables'][table][0][field])
        value.pop('entry_strategy_execution')
        data['tables'][table][0][field] = json.dumps(value)
    data['version'] = 7
    assert recovery.version(data['tables']) == 7
    recovery.validate_snapshot(data)
    with pytest.raises(ValueError, match='format_content_mismatch'):
        recovery.validate_snapshot(dict(data, version=6))


@pytest.mark.parametrize('damage', ['missing_order_guard', 'unknown_signal_guard', 'null_signal_guard'])
def test_snapshot_cannot_downgrade_or_hide_signal_execution_without_order(damage):
    data = copy.deepcopy(data_for())
    if damage == 'missing_order_guard':
        value = json.loads(data['tables']['scanner_orders'][0]['plan_json'])
        value.pop('entry_strategy_execution')
        data['tables']['scanner_orders'][0]['plan_json'] = json.dumps(value)
    else:
        value = json.loads(data['tables']['scanner_signals'][0]['technical_json'])
        if damage == 'unknown_signal_guard':
            value['entry_strategy_execution']['version'] = 'future_v99'
        else:
            value['entry_strategy_execution'] = None
        data['tables']['scanner_signals'][0]['technical_json'] = json.dumps(value)
        data['tables']['scanner_orders'] = []
    with pytest.raises(ValueError, match='contract_invalid|unsupported'):
        recovery.validate_snapshot(data)
