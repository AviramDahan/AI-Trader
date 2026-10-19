"""Release coordination regressions; no server, Docker, provider or real backup."""
import importlib.util
from contextlib import nullcontext
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SHA = 'a' * 40


def load_file(path, name, monkeypatch):
    if sys.platform == 'win32':
        monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(
            LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=lambda *a: None))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pull_lock_busy_is_retriable_not_a_permanent_failed_release(tmp_path, monkeypatch):
    release = load_file(ROOT / 'deploy/hetzner-pull.py', '_isolated_release_pull', monkeypatch)
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    if hasattr(release, 'deployment_lock'):
        monkeypatch.setattr(release, 'deployment_lock', lambda: nullcontext(9))
        monkeypatch.setattr(release, 'launch_deploy', lambda *a: 75)
    monkeypatch.setattr(release.subprocess, 'check_output', lambda *a, **k: SHA + '\trefs/heads/main\n')
    checks = {'workflow_runs': [dict(head_sha=SHA, head_branch='main', event='push',
        head_repository={'full_name': release.REPO}, name=name, conclusion='success')
        for name in ('CI', 'Cloud readiness (no deployment)')]}
    monkeypatch.setattr(release.urllib.request, 'urlopen', lambda *a, **k:
        io.BytesIO(json.dumps(checks).encode()))
    monkeypatch.setattr(release.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=75))
    with pytest.raises(SystemExit) as exit_value:
        release.main()
    assert exit_value.value.code == 75
    assert not (tmp_path / 'failed-release').exists(), 'temporary contention must not latch source failure'


def test_backup_contention_once_is_busy_without_publishing_backup_failure(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, 'recovery_state', SimpleNamespace())
    backup = load_file(ROOT / 'service/server/recovery_backup.py', '_isolated_release_backup', monkeypatch)
    statuses = []
    monkeypatch.setitem(sys.modules, 'scanner_engine', SimpleNamespace(
        set_service_status=lambda *a, **k: statuses.append((a, k))))
    monkeypatch.setattr(sys, 'argv', ['recovery_backup.py', '--once', '--predeploy'])
    def busy(*a, **k):
        raise getattr(backup, 'BackupBusy', BlockingIOError)('synthetic valid writer owns lock')
    monkeypatch.setattr(backup, 'backup', busy)
    with pytest.raises(SystemExit) as exit_value:
        backup.main()
    assert exit_value.value.code == 75
    assert statuses == [], 'contention is not an unsuccessful encrypted backup'
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[-1]['backup'] == 'busy'


def test_versioned_unit_covers_known_two_cold_backups_and_rollback():
    # Actual dated failure: 1200s unit versus two ~660s backups alone, before
    # build/start/rollback. This verifies a checked-in reviewed unit replaces
    # that insufficient whole-operation bound; never sleeps for twenty minutes.
    unit = (ROOT / 'deploy/systemd/ai-trader-deploy.service').read_text()
    values = dict(line.split('=', 1) for line in unit.splitlines() if '=' in line)
    assert values['KillMode'] == 'mixed'
    assert values['TimeoutStartSec'] != '1200'
    assert values['TimeoutStopSec'] != '90'
    assert int(values['TimeoutStartSec']) >= 3600 + 1200
    assert int(values['TimeoutStopSec']) >= 1200
    assert 'ExecStart=/usr/local/sbin/ai-trader-pull' in unit


def backup_module(monkeypatch):
    monkeypatch.setitem(sys.modules, 'recovery_state', SimpleNamespace())
    return load_file(ROOT / 'service/server/recovery_backup.py', '_isolated_lock_backup', monkeypatch)


def test_backup_lock_wait_is_bounded_and_never_truncates_or_overwrites_status(tmp_path, monkeypatch):
    backup = backup_module(monkeypatch)
    clock = [0.0]
    calls = []
    def blocked(*a):
        calls.append(True)
        raise BlockingIOError()
    monkeypatch.setattr(backup.fcntl, 'flock', blocked)
    monkeypatch.setattr(backup.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(backup.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(backup.requests, 'get', lambda *a, **k: pytest.fail('busy must do zero provider IO'))
    work = tmp_path / 'repository'
    (tmp_path / 'backup.lock').write_text('existing owner metadata')
    (tmp_path / 'status.json').write_text('{"previous_success":true}')
    monkeypatch.setenv('RECOVERY_WORKDIR', str(work))
    monkeypatch.setenv('RECOVERY_GITHUB_REPO', 'synthetic/not-contacted')
    with pytest.raises(backup.BackupBusy):
        backup.backup(True, lock_wait_seconds=2)
    assert clock[0] == 2 and len(calls) == 9
    assert (tmp_path / 'backup.lock').read_text() == 'existing owner metadata'
    assert (tmp_path / 'status.json').read_text() == '{"previous_success":true}'


def test_backup_lock_can_be_obtained_after_valid_writer_finishes(monkeypatch):
    backup = backup_module(monkeypatch)
    clock, calls = [0.0], []
    def eventually(*a):
        calls.append(True)
        if len(calls) <= 2:
            raise BlockingIOError()
    monkeypatch.setattr(backup.fcntl, 'flock', eventually)
    monkeypatch.setattr(backup.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(backup.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))
    backup.acquire_backup_lock(object(), 2)
    assert len(calls) == 3 and clock[0] == 0.5


@pytest.mark.parametrize('wait', [-1, 901, True, 0.25])
def test_backup_lock_invalid_wait_fails_before_any_lock_or_provider_call(monkeypatch, wait):
    backup = backup_module(monkeypatch)
    monkeypatch.setattr(backup.fcntl, 'flock', lambda *a: pytest.fail('invalid wait touched lock'))
    with pytest.raises(ValueError, match='invalid_backup_lock_wait'):
        backup.acquire_backup_lock(object(), wait)


def test_docker_nanosecond_utc_clock_is_accepted_without_future_rounding(monkeypatch):
    release = load_file(ROOT / 'deploy/hetzner-pull.py', '_clock_release', monkeypatch)
    assert release.aware('2026-10-19T09:30:00.123456789Z').microsecond == 123456
    with pytest.raises(ValueError, match='backup_proof_clock_invalid'):
        release.aware('2026-10-19T09:30:00')


@pytest.mark.parametrize('old_formats,old_execution,passes', [
    (list(range(1, 10)), 'independent_entry_execution_v1', True),
    (list(range(1, 7)), 'independent_entry_execution_v1', False),
    (list(range(1, 10)), 'unknown', False),
])
def test_actual_old_binary_not_schema_or_last_release_marker_controls_rollback(monkeypatch, old_formats, old_execution, passes):
    release = load_file(ROOT / 'deploy/hetzner-pull.py', '_rollback_capability_release', monkeypatch)
    old, new = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
    caps = dict(snapshot_formats=list(range(1, 10)), audit_version='entry_discovery_v1',
        execution_version='independent_entry_execution_v1', emergency_entry_version='paper_entry_emergency_v1')
    monkeypatch.setattr(release, 'inspect', lambda kind, image:
        {'Id': image, 'Config': {'Env': ['BUILD_SHA=' + (SHA if image == new else 'b' * 40)]}})
    monkeypatch.setattr(release, 'image_identity', lambda image, sha=None: dict(build_sha=SHA if image == new else 'b' * 40))
    monkeypatch.setattr(release, 'verify_role', lambda *a, **k: True)
    commands = []
    def synthetic(command, *a, **k):
        commands.append(command)
        image = command[-3]
        value = dict(caps)
        if image == old:
            value.update(snapshot_formats=old_formats, execution_version=old_execution)
        return json.dumps({'build_sha': SHA if image == new else 'b' * 40, 'capabilities': value}).encode()
    monkeypatch.setattr(release, 'run', synthetic)
    if passes:
        release.check_rollback(SHA, old, new)
    else:
        with pytest.raises(ValueError, match='actual_previous_image_not_compatible'):
            release.check_rollback(SHA, old, new)
    assert len(commands) == 2
    assert all(command[command.index('--network') + 1] == 'none' and '--read-only' in command for command in commands)
