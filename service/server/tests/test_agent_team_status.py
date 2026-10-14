"""Synthetic, bounded reports. Never publish to Production or start agents."""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_team_status as team

NOW = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)


def report(state='running'):
    return {'version': 1, 'run_id': 'synthetic-test', 'reported_at': NOW.isoformat(),
            'report_url': 'https://github.com/AviramDahan/AI-Trader/pull/74',
            'agents': [{'id': 'coordinator', 'state': state, 'task': 'coordination',
                        'observed_at': NOW.isoformat()}]}


@pytest.fixture
def destination(tmp_path, monkeypatch):
    target = tmp_path / 'agent-team-status.json'
    monkeypatch.setattr(team, 'RUNTIME_REPORT', target)
    return target


def test_absent_report_has_explicit_historical_provenance(destination):
    value = team.snapshot(NOW)
    assert value['source'] == 'published_audit' and len(value['agents']) == 8
    assert all(row['state'] == 'completed' for row in value['agents'])
    assert value['reported_at'] == '2026-10-14T20:45:27+00:00'
    assert not destination.exists()  # GET does not initialize a report.


def test_publish_roundtrip_atomic_snapshot_and_no_private_fields(destination):
    value = report()
    value['secret'] = 'do-not-copy'
    value['agents'][0]['prompt'] = 'do-not-copy'
    assert team.publish(value, NOW)['published']
    before = destination.read_bytes()
    result = team.snapshot(NOW)
    assert result['source'] == 'coordinator_report' and result['agents'][0]['state'] == 'running'
    assert destination.read_bytes() == before
    assert 'do-not-copy' not in before.decode() and 'do-not-copy' not in json.dumps(result)
    assert list(destination.parent.iterdir()) == [destination]


def test_stale_activity_is_not_running_and_completed_is_historical(destination):
    team.publish(report(), NOW)
    assert team.snapshot(NOW+timedelta(seconds=180))['agents'][0]['state'] == 'running'
    assert team.snapshot(NOW+timedelta(seconds=181))['agents'][0]['state'] == 'stale'
    team.publish(report('completed'), NOW)
    assert team.snapshot(NOW+timedelta(days=2))['agents'][0]['state'] == 'completed'


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(version=True), lambda d: d.update(version=2),
    lambda d: d.update(run_id='private@example.invalid'),
    lambda d: d.update(reported_at=(NOW+timedelta(seconds=6)).isoformat()),
    lambda d: d.update(reported_at='2026-10-15T10:00:00'),
    lambda d: d.update(report_url='javascript:alert(1)'),
    lambda d: d.update(report_url='https://github.com/other/repository/pull/1'),
    lambda d: d['agents'].append(copy.deepcopy(d['agents'][0])),
    lambda d: d['agents'][0].update(id='unsupported'),
    lambda d: d['agents'][0].update(state='healthy'),
    lambda d: d['agents'][0].update(task='untrusted command'),
    lambda d: d['agents'][0].update(blocker_code='untrusted reason'),
    lambda d: d['agents'][0].update(blocker_code='needs_approval'),
    lambda d: d['agents'][0].update(observed_at=(NOW+timedelta(seconds=1)).isoformat()),
])
def test_invalid_new_report_does_not_revive_old_completed_state(destination, mutation):
    value = report(); mutation(value)
    destination.write_text(json.dumps(value))
    result = team.snapshot(NOW)
    assert result['source'] == 'unavailable' and result['agents'] == []
    with pytest.raises((ValueError, TypeError)):
        team.publish(value, NOW)


@pytest.mark.parametrize('raw', [b'{', b'{"version":1,"version":1}', b'{"x":NaN}', b'x'*32769, b'['*2000+b']'*2000], ids=['invalid-json','duplicate-version','nonfinite','oversized','deep-nesting'])
def test_corrupt_or_oversized_reports_fail_closed(destination, raw):
    destination.write_bytes(raw)
    assert team.snapshot(NOW)['source'] == 'unavailable'


def test_publish_rejects_old_active_report_without_losing_previous(destination):
    team.publish(report('completed'), NOW)
    before = destination.read_bytes()
    with pytest.raises(ValueError):
        team.publish(report(), NOW+timedelta(seconds=181))
    assert destination.read_bytes() == before


def test_future_packaged_report_not_presented_as_available(destination):
    assert team.snapshot(datetime(2026, 10, 14, 15, tzinfo=timezone.utc))['source'] == 'unavailable'


def test_nonregular_destination_is_not_read_as_a_report(destination):
    destination.mkdir()
    assert team.snapshot(NOW)['source'] == 'unavailable'


def test_blocker_reason_is_verified_not_freeform(destination):
    value=report('blocked');value['agents'][0]['blocker_code']='missing_evidence'
    team.publish(value,NOW)
    assert team.snapshot(NOW)['agents'][0]['blocker_code']=='missing_evidence'
