"""Synthetic empty portfolio: durable kill overlay must not disappear in recovery."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import active_snapshot
import recovery_holds
import recovery_state

KEY = 'paper_entry_emergency_v1'
AT = '2026-10-06T14:01:00Z'


def control(paused=True):
    return dict(version=KEY, revision=1, paused=paused, updated_at=AT,
                intervals=[dict(paused_at=AT, resumed_at=None)])


def packet(version=9):
    tables = {name: [] for name in active_snapshot.TABLES}
    tables['agents'] = [dict(id=1, name='us-stock-scanner', cash=1000, deposited=1000)]
    tables['scanner_accounts'] = [dict(id=1, agent_id=1, cash=1000, initial_cash=1000,
                                     fees_paid=0, realized_pnl=0)]
    return dict(version=version, created_at=AT, tables=tables, primary_agent_id=1,
                settings=[dict(key=KEY, value_json=json.dumps(control()), updated_at=AT)],
                hold_coverage=recovery_holds.coverage([]))


def test_emergency_control_survives_sanitization_as_required_format9():
    source = packet()
    saved = recovery_state.sanitize(source)
    assert saved['recovery_format'] == saved['version'] == 9
    assert saved['settings'] == source['settings']
    assert recovery_state.validate(saved)['scanner_accounts'] == 1
    assert source == packet()


@pytest.mark.parametrize('version', [2, 6, 7, 8])
def test_control_cannot_be_smuggled_into_older_backup_format(version):
    with pytest.raises(ValueError):
        recovery_state.sanitize(packet(version))


@pytest.mark.parametrize('damage', ['paused', 'duplicate', 'version', 'clock', 'unknown_setting'])
def test_invalid_control_or_duplicate_setting_is_not_silently_restorable(damage):
    data = packet(2)
    payload = json.loads(data['settings'][0]['value_json'])
    if damage == 'paused':
        payload['paused'] = 'false'
    elif damage == 'duplicate':
        data['settings'].append(copy.deepcopy(data['settings'][0]))
    elif damage == 'version':
        payload['version'] = 'future_v99'
    elif damage == 'clock':
        data['settings'][0]['updated_at'] = '2026-10-06T13:00:00Z'
    elif damage == 'unknown_setting':
        data['settings'].append(dict(key='unreviewed_control', value_json='{}', updated_at=AT))
    data['settings'][0]['value_json'] = json.dumps(payload)
    with pytest.raises(ValueError):
        recovery_state.sanitize(data)


def test_format9_without_control_is_rejected_not_synthetic_default():
    source = packet()
    source['settings'] = []
    with pytest.raises(ValueError):
        recovery_state.sanitize(source)


def test_old_packet_without_new_control_keeps_original_format():
    source = packet(2)
    source['settings'] = []
    assert recovery_state.sanitize(source)['version'] == 2


def test_duplicate_json_control_key_and_unpersisted_default_are_refused():
    data = packet()
    data['settings'][0]['value_json'] = data['settings'][0]['value_json'].replace(
        '"paused": true', '"paused": false, "paused": true')
    with pytest.raises(ValueError):
        recovery_state.sanitize(data)
    data = packet()
    data['settings'][0].update(value_json=json.dumps(dict(version=KEY, revision=0,
        paused=False, updated_at=None, intervals=[])), updated_at=None)
    with pytest.raises(ValueError):
        recovery_state.sanitize(data)


def test_control_newer_than_snapshot_capture_is_refused():
    data = packet()
    data['created_at'] = '2026-10-06T14:00:00Z'
    with pytest.raises(ValueError, match='future_emergency_snapshot_control'):
        recovery_state.sanitize(data)
