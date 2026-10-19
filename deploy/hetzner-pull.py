#!/usr/bin/env python3
"""Root release gate and bounded backup coordination. Exit75 is retriable.

No path kills/removes a valid backup. Named no-restart jobs survive observers
and can be rejoined, including by a later protected activation operation.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = 'AviramDahan/AI-Trader'
ROOT = Path('/opt/ai-trader-staging/deploy')
LOCK = Path('/run/lock/ai-trader-deploy.lock')
WORK_PARENT = Path('/opt')
BACKUP_WAIT_MAX = 1800
BACKUP_LOCK_WAIT = 900
BACKUP_PROOF_MAX_AGE = 1800
LABEL = 'ai-trader.managed-backup'
_cancelled = False
_child = None
PHASES = {'STARTED', 'BUILDING', 'PREDEPLOY_PENDING', 'PREDEPLOY_VERIFIED',
    'DRAIN_PENDING', 'REPLACING', 'ROLLING_BACK', 'ROLLED_BACK', 'ROLLBACK_DEFERRED',
    'COMMITTING', 'COMPLETE', 'FAILED', 'INTERRUPTED', 'DEFERRED_PREDEPLOY', 'DEFERRED_DRAIN'}


class Busy(RuntimeError):
    pass


def emit(status, **fields):
    print(json.dumps(dict(status=status, **fields), sort_keys=True), flush=True)


def utc():
    return datetime.now(timezone.utc).isoformat()


def exact_sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('invalid_release_sha')
    return value


def exact_image(value):
    if not isinstance(value, str) or not re.fullmatch('sha256:[0-9a-f]{64}', value):
        raise ValueError('invalid_image_id')
    return value


def atomic(path, data):
    """Same-directory fsync/replace; never expose half a durable marker."""
    if path.is_symlink():
        raise ValueError('marker_symlink_refused')
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, value):
    atomic(path, json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def private_dir(path):
    if not path.exists():
        path.mkdir(mode=0o700)
    row = path.lstat()
    if not stat.S_ISDIR(row.st_mode) or row.st_uid != 0 or row.st_mode & 0o077:
        raise ValueError('unprotected_release_directory')


@contextmanager
def deployment_lock():
    """Validate inherited FD by inode AND actual flock, not an ENV boolean."""
    supplied = os.getenv('AI_TRADER_DEPLOY_LOCK_FD')
    owned = supplied is None
    if supplied is not None:
        if not re.fullmatch('[0-9]{1,3}', supplied) or int(supplied) < 3:
            raise ValueError('invalid_inherited_release_lock')
        descriptor = int(supplied)
    else:
        descriptor = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        actual, expected = os.fstat(descriptor), LOCK.lstat()
        if not stat.S_ISREG(expected.st_mode) or expected.st_uid != 0 or expected.st_mode & 0o022:
            raise ValueError('unprotected_release_lock')
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError('inherited_release_lock_inode_mismatch')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy('deployment_lock_busy') from None
        yield descriptor
    finally:
        # An inherited description remains locked in its actual parent owner.
        if owned:
            os.close(descriptor)


def run(args, timeout=30, env=None):
    result = subprocess.run(args, capture_output=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError('release_command_failed')
    if len(result.stdout) > 1024 * 1024:
        raise RuntimeError('release_output_bound')
    return result.stdout


def inspect(kind, name):
    result = subprocess.run(['docker', kind, 'inspect', name], capture_output=True, timeout=20)
    if result.returncode:
        return None
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('docker_inspection_bound')
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError('docker_inspection_shape')
    return rows[0]


def aware(value):
    # Docker emits RFC3339 nanoseconds; Python3.10 accepts microseconds only.
    value = re.sub(r'(\.\d{6})\d+(?=Z$|[+-]\d{2}:\d{2}$)', r'\1', value)
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise ValueError('backup_proof_clock_invalid')
    return value


def backup_spec(sha, image, request_id):
    exact_sha(sha)
    exact_image(image)
    if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id):
        raise ValueError('invalid_backup_request_id')
    return dict(version=1, request_id=request_id, build_sha=sha, image_id=image,
        name='ai-trader-managed-backup-' + request_id, phase='predeploy',
        command=['/app/service/server/recovery_backup.py', '--once', '--predeploy',
            '--lock-wait-seconds', str(BACKUP_LOCK_WAIT), '--request-id', request_id])


def validate_backup_container(row, spec, standing):
    if not isinstance(row, dict):
        raise ValueError('managed_backup_container_missing')
    if row.get('Name') != '/' + spec['name']:
        raise ValueError('managed_backup_name_mismatch')
    labels = row['Config'].get('Labels') or {}
    if row['Image'] != spec['image_id'] or labels.get(LABEL) != spec['request_id']:
        raise ValueError('managed_backup_identity_mismatch')
    for key in ('build_sha', 'phase'):
        if labels.get(LABEL + '.' + key) != spec[key]:
            raise ValueError('managed_backup_label_mismatch')
    if row['Config']['Entrypoint'] != ['python'] or row['Config']['Cmd'] != spec['command']:
        raise ValueError('managed_backup_command_mismatch')
    if row['HostConfig']['RestartPolicy']['Name'] != 'no':
        raise ValueError('managed_backup_must_never_restart_automatically')
    if row['HostConfig'].get('PortBindings'):
        raise ValueError('managed_backup_unexpected_ports')
    if set(row['NetworkSettings']['Networks']) != set(standing['NetworkSettings']['Networks']):
        raise ValueError('managed_backup_unexpected_network')
    def mounts(value):
        return {(m['Destination'], m['Type'], m.get('Source'), m.get('RW')) for m in value.get('Mounts', [])}
    if mounts(row) != mounts(standing):
        raise ValueError('managed_backup_unexpected_mount')


def managed_backup(sha, image, request_id, wait_seconds):
    """Observe one exact owned job. Timeout never kills/removes/restarts it."""
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= BACKUP_WAIT_MAX:
        raise ValueError('invalid_managed_backup_wait')
    if _cancelled:
        raise Busy('backup_observation_cancelled')
    spec = backup_spec(sha, image, request_id)
    directory = ROOT / 'backup-requests'
    private_dir(directory)
    # Validate all nonmutating launch preconditions before reserving a request.
    image_row = inspect('image', image)
    env = dict(v.split('=', 1) for v in (image_row or {}).get('Config', {}).get('Env', []) if '=' in v)
    if not image_row or image_row['Id'] != image or env.get('BUILD_SHA') != sha:
        raise ValueError('managed_backup_source_image_mismatch')
    standing = inspect('container', 'ai-trader-cloud-backup-1')
    if not standing:
        raise ValueError('standing_backup_definition_missing')
    active_path = directory / 'active.json'
    if active_path.exists():
        active = json.loads(active_path.read_text())
        if active.get('version') != 1 or not re.fullmatch('[0-9a-f]{32}', active.get('request_id', '')) or active.get('state') not in ('PLANNED', 'RUNNING_PENDING', 'VERIFIED_COMPLETE', 'FAILED'):
            raise ValueError('managed_backup_active_index_invalid')
        if active.get('request_id') != request_id and active.get('state') != 'VERIFIED_COMPLETE':
            # No queue of additional snapshots behind a still-live writer.
            raise Busy('another_managed_backup_pending')
        if active.get('request_id') != request_id:
            previous = inspect('container', 'ai-trader-managed-backup-' + active['request_id'])
            if previous and previous['State']['Running']:
                raise Busy('previous_managed_backup_running')
    record_path = directory / (request_id + '.json')
    existing_request = record_path.exists()
    if existing_request:
        record = json.loads(record_path.read_text())
        if record.get('spec') != spec:
            raise ValueError('managed_backup_request_conflict')
    else:
        if inspect('container', spec['name']) is not None:
            raise ValueError('unowned_existing_backup_container')
        record = dict(version=1, spec=spec, requested_at=utc(), state='PLANNED')
        atomic_json(record_path, record)
    atomic_json(active_path, dict(version=1, request_id=request_id, state=record['state']))
    row = inspect('container', spec['name'])
    if row is None:
        if existing_request:
            raise ValueError('managed_backup_existing_job_disappeared')
        override = directory / 'one-off-no-restart.yml'
        expected = b'services:\n  backup:\n    restart: "no"\n'
        if override.exists() and override.read_bytes() != expected:
            raise ValueError('managed_backup_override_conflict')
        if not override.exists():
            atomic(override, expected)
        command = ['docker', 'compose', '-f', str(ROOT / 'compose.yml'), '-f', str(override),
            '--profile', 'backups', 'run', '--no-deps', '--pull', 'never', '-d',
            '--name', spec['name'], '--label', LABEL + '=' + request_id,
            '--label', LABEL + '.build_sha=' + sha, '--label', LABEL + '.phase=predeploy',
            '--entrypoint', 'python', 'backup', *spec['command']]
        run(command, 60, env=dict(os.environ, APP_IMAGE=image,
            PUBLIC_API_HOST=os.getenv('PUBLIC_API_HOST', '2-28-100-77.sslip.io')))
        row = inspect('container', spec['name'])
    validate_backup_container(row, spec, standing)
    if record.get('container_id') not in (None, row['Id']):
        raise ValueError('managed_backup_container_id_changed')
    record['container_id'] = row['Id']
    atomic_json(record_path, record)
    deadline = time.monotonic() + wait_seconds
    # Exit75 means this exact job never obtained its lock. Only that completed
    # no-work job may be restarted. A running or successful writer never is.
    if not row['State']['Running'] and row['State'].get('ExitCode') == 75:
        run(['docker', 'start', spec['name']], 30)
    while True:
        row = inspect('container', spec['name'])
        if row is None:
            raise ValueError('managed_backup_disappeared')
        validate_backup_container(row, spec, standing)
        if row['Id'] != record['container_id']:
            raise ValueError('managed_backup_container_id_changed')
        if not row['State']['Running']:
            break
        if _cancelled or time.monotonic() >= deadline:
            record.update(state='RUNNING_PENDING', observed_at=utc())
            atomic_json(record_path, record)
            atomic_json(active_path, dict(version=1, request_id=request_id, state='RUNNING_PENDING'))
            emit('PENDING', reason='managed_backup_still_running', request_id=request_id,
                container=spec['name'], image_id=image)
            raise Busy('managed_backup_still_running')
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    if row['State'].get('ExitCode') == 75:
        raise Busy('backup_lock_wait_elapsed')
    if row['State'].get('ExitCode') != 0 or row['State'].get('OOMKilled'):
        record.update(state='FAILED', observed_at=utc(), exit_code=row['State'].get('ExitCode'))
        atomic_json(record_path, record)
        atomic_json(active_path, dict(version=1, request_id=request_id, state='FAILED'))
        raise RuntimeError('managed_backup_failed')
    logs = run(['docker', 'logs', '--tail', '20', spec['name']], 20)
    proofs = []
    for line in logs.decode().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and 'managed_request' in value:
            proofs.append(value)
    if len(proofs) != 1:
        raise ValueError('managed_backup_completed_proof_missing')
    proof = proofs[0]
    managed = proof['managed_request']
    if managed.get('request_id') != request_id or managed.get('build_sha') != sha or managed.get('predeploy') is not True:
        raise ValueError('managed_backup_proof_identity_mismatch')
    if not re.fullmatch('[0-9a-f]{64}', proof.get('snapshot_id', '')) or not re.fullmatch('[0-9a-f]{40}', managed.get('remote_commit', '')):
        raise ValueError('managed_backup_remote_proof_invalid')
    if type(proof.get('recovery_format')) is not int or not 1 <= proof['recovery_format'] <= 9:
        raise ValueError('managed_backup_recovery_format_invalid')
    start, finish = aware(managed['started_at']), aware(managed['finished_at'])
    now = datetime.now(timezone.utc)
    if start < aware(row['State']['StartedAt']) or start < aware(record['requested_at']) or finish < start or finish > now or finish > aware(row['State']['FinishedAt']):
        raise ValueError('managed_backup_proof_clock_mismatch')
    if (now - finish).total_seconds() > BACKUP_PROOF_MAX_AGE:
        raise ValueError('managed_backup_proof_stale')
    record.update(state='VERIFIED_COMPLETE', observed_at=utc(), proof=proof)
    atomic_json(record_path, record)
    atomic_json(active_path, dict(version=1, request_id=request_id, state='VERIFIED_COMPLETE'))
    emit('VERIFIED_COMPLETE', request_id=request_id, image_id=image, proof=proof)
    return proof


def stop_backup_idle(wait_seconds):
    """Keep the actual volume lock held THROUGH stopping an idle service."""
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= BACKUP_LOCK_WAIT:
        raise ValueError('invalid_backup_drain_wait')
    name = 'ai-trader-cloud-backup-1'
    row = inspect('container', name)
    if not row:
        raise ValueError('standing_backup_missing')
    labels = row['Config'].get('Labels') or {}
    if labels.get('com.docker.compose.project') != 'ai-trader-cloud' or labels.get('com.docker.compose.service') != 'backup':
        raise ValueError('standing_backup_owner_mismatch')
    matches = [m for m in row['Mounts'] if m['Destination'] == '/backup']
    if len(matches) != 1 or matches[0]['Type'] != 'volume' or matches[0].get('Name') != 'ai-trader-cloud_recovery_backup':
        raise ValueError('standing_backup_volume_mismatch')
    volume = inspect('volume', matches[0]['Name'])
    if not volume or volume['Mountpoint'] != matches[0]['Source']:
        raise ValueError('standing_backup_mountpoint_mismatch')
    descriptor = os.open(Path(volume['Mountpoint']) / 'backup.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        file = os.fstat(descriptor)
        if not stat.S_ISREG(file.st_mode) or file.st_uid not in (0, 10001):
            raise ValueError('standing_backup_lock_invalid')
        deadline = time.monotonic() + wait_seconds
        while True:
            if _cancelled:
                raise Busy('backup_drain_cancelled')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if _cancelled or time.monotonic() >= deadline:
                    raise Busy('valid_backup_still_running') from None
                time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        if _cancelled:
            raise Busy('backup_drain_cancelled')
        current = inspect('container', name)
        if not current or current['Id'] != row['Id']:
            raise ValueError('standing_backup_changed_while_waiting')
        if current['State']['Running']:
            run(['docker', 'stop', '--time', '30', name], 60)
        emit('BACKUP_STOPPED_WHILE_IDLE', container=name)
    finally:
        os.close(descriptor)


def check_rollback(sha, old, new):
    """Schema equality is not entry/backup compatibility; probe real binaries."""
    exact_sha(sha)
    results = []
    code = ('import json,os,entry_discovery_capabilities as c; '
        'print(json.dumps({"build_sha":os.environ["BUILD_SHA"],"capabilities":c.capabilities()}))')
    for image in (exact_image(old), exact_image(new)):
        row = inspect('image', image)
        env = dict(v.split('=', 1) for v in (row or {}).get('Config', {}).get('Env', []) if '=' in v)
        if not row or row['Id'] != image or not re.fullmatch('[0-9a-f]{40}', env.get('BUILD_SHA', '')):
            raise ValueError('rollback_source_image_identity_invalid')
        output = run(['docker', 'run', '--pull=never', '--rm', '--network', 'none', '--read-only',
            '--cpus', '0.25', '--memory', '128m', '--memory-swap', '128m', '--pids-limit', '64',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--entrypoint', 'python', image, '-c', code], 60)
        value = json.loads(output)
        if value.get('build_sha') != env['BUILD_SHA']:
            raise ValueError('rollback_embedded_source_mismatch')
        caps = value['capabilities']
        formats = caps.get('snapshot_formats')
        if not isinstance(formats, list) or not formats or any(type(n) is not int or n < 1 for n in formats):
            raise ValueError('rollback_format_capability_unknown')
        results.append(value)
    previous, candidate = results
    if candidate['build_sha'] != sha:
        raise ValueError('rollback_candidate_source_mismatch')
    a, b = previous['capabilities'], candidate['capabilities']
    keys = ('audit_version', 'execution_version', 'emergency_entry_version')
    if not set(a['snapshot_formats']).issuperset(b['snapshot_formats']) or any(not b.get(k) or a.get(k) != b[k] for k in keys):
        raise ValueError('actual_previous_image_not_compatible_with_candidate')
    emit('ROLLBACK_BINARY_CAPABILITIES_VERIFIED', old_image=old, new_image=new,
        old_build_sha=previous['build_sha'], build_sha=sha, capabilities=a)


def journal_begin(sha, old):
    exact_sha(sha)
    exact_image(old)
    path = ROOT / 'deployment-attempt.json'
    if path.exists():
        previous = json.loads(path.read_text())
        if previous.get('phase') not in ('COMPLETE', 'FAILED', 'ROLLED_BACK'):
            if previous.get('sha') == sha and previous.get('phase') in ('DEFERRED_PREDEPLOY', 'DEFERRED_DRAIN'):
                if previous.get('old_image') != old:
                    raise ValueError('pending_release_old_runtime_changed')
                for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
                    row = inspect('container', 'ai-trader-cloud-' + role + '-1')
                    if not row or row['Image'] != old or not row['State']['Running'] or row['State'].get('Health', {}).get('Status') != 'healthy':
                        raise ValueError('pending_release_old_runtime_not_verified')
                if not Path(previous['work']).is_dir():
                    raise ValueError('pending_release_work_missing')
                return previous
            raise ValueError('interrupted_release_requires_operator_review')
    work = tempfile.mkdtemp(prefix='ai-trader-release.', dir=WORK_PARENT)
    value = dict(version=1, attempt_id=os.urandom(16).hex(), sha=sha, old_image=old,
        new_image='', phase='STARTED', work=work, started_at=utc(), updated_at=utc())
    atomic_json(path, value)
    return value


def journal_update(sha, attempt_id, phase, image):
    if phase not in PHASES:
        raise ValueError('invalid_release_phase')
    path = ROOT / 'deployment-attempt.json'
    value = json.loads(path.read_text())
    if value.get('sha') != exact_sha(sha) or value.get('attempt_id') != attempt_id:
        raise ValueError('release_attempt_changed')
    if image:
        exact_image(image)
        if value.get('new_image') and value['new_image'] != image:
            raise ValueError('release_image_changed')
        value['new_image'] = image
    value.update(phase=phase, updated_at=utc())
    atomic_json(path, value)


def healthy_roles(sha, image):
    for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
        row = inspect('container', 'ai-trader-cloud-' + role + '-1')
        env = dict(v.split('=', 1) for v in (row or {}).get('Config', {}).get('Env', []) if '=' in v)
        if not row or row['Image'] != image or env.get('BUILD_SHA') != sha or not row['State']['Running'] or row['State'].get('OOMKilled') or row['State'].get('Health', {}).get('Status') != 'healthy':
            return False
    return True


def completed(sha):
    path = ROOT / 'last-release'
    if not path.exists():
        return False
    values = path.read_text().splitlines()
    if len(values) < 2 or values[0] != sha:
        return False
    image = exact_image(values[1])
    if not healthy_roles(sha, image):
        return False
    marker = run(['docker', 'exec', 'ai-trader-cloud-api-1', 'python', '-c',
        'from pathlib import Path; print(Path("/app/.runtime/deployed-release").read_text())'], 20).decode().strip()
    return marker == sha


def commit_release(sha, image, old, attempt_id):
    exact_sha(sha)
    exact_image(image)
    exact_image(old)
    value = json.loads((ROOT / 'deployment-attempt.json').read_text())
    if value.get('sha') != sha or value.get('attempt_id') != attempt_id or value.get('phase') != 'COMMITTING' or value.get('new_image') != image or value.get('old_image') != old:
        raise ValueError('release_commit_attempt_mismatch')
    if not healthy_roles(sha, image):
        raise ValueError('release_commit_roles_not_ready')
    code = ('import os,sys,tempfile; from pathlib import Path; '
        'p=Path("/app/.runtime/deployed-release"); '
        'fd,t=tempfile.mkstemp(prefix=".deployed-release-",dir=p.parent); '
        'f=os.fdopen(fd,"w"); f.write(sys.argv[1]); f.flush(); os.fsync(f.fileno()); '
        'f.close(); os.replace(t,p); d=os.open(p.parent,os.O_RDONLY); os.fsync(d); os.close(d)')
    run(['docker', 'exec', 'ai-trader-cloud-api-1', 'python', '-c', code, sha], 30)
    atomic(ROOT / 'last-release', (sha + '\n' + image + '\n' + old + '\n').encode())
    if not completed(sha):
        raise ValueError('release_commit_not_verified')
    journal_update(sha, attempt_id, 'COMPLETE', image)
    emit('VERIFIED_COMPLETE', build_sha=sha, image_id=image)


def launch_deploy(sha, descriptor):
    global _child
    _child = subprocess.Popen(['/usr/local/sbin/ai-trader-deploy', sha],
        pass_fds=(descriptor,), start_new_session=True,
        env=dict(os.environ, AI_TRADER_DEPLOY_LOCK_FD=str(descriptor)))
    try:
        return _child.wait()
    finally:
        _child = None


def poll(descriptor):
    sha = exact_sha(subprocess.check_output(['git', 'ls-remote',
        f'https://github.com/{REPO}.git', 'refs/heads/main'], text=True, timeout=30).split()[0])
    if completed(sha):
        emit('ALREADY_VERIFIED_COMPLETE', build_sha=sha)
        return
    for path in (ROOT / 'failed-release', ROOT / 'failed-releases' / (sha + '.json')):
        if path.exists() and (path.suffix == '.json' or path.read_text().splitlines()[0] == sha):
            emit('BLOCKED_FAILED_RELEASE', build_sha=sha)
            return
    request = urllib.request.Request(f'https://api.github.com/repos/{REPO}/actions/runs?head_sha={sha}&branch=main&event=push&per_page=100',
        headers={'User-Agent': 'AI-Trader-release-gate'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('release_check_response_bound')
    selected = {}
    for row in json.loads(data)['workflow_runs']:
        if row['head_sha'] == sha and row['head_branch'] == 'main' and row['event'] == 'push' and row['head_repository']['full_name'] == REPO:
            selected.setdefault(row['name'], row['conclusion'])
    if any(selected.get(name) != 'success' for name in ('CI', 'Cloud readiness (no deployment)')):
        emit('WAITING_FOR_EXACT_CHECKS', build_sha=sha)
        return
    code = launch_deploy(sha, descriptor)
    if code == 75:
        emit('DEFERRED', build_sha=sha, reason='release_or_backup_busy')
        raise SystemExit(75)
    if code == 0 and not completed(sha):
        # An installed wrapper returning zero is not completion evidence.
        code = 1
    if code:
        directory = ROOT / 'failed-releases'
        private_dir(directory)
        atomic_json(directory / (sha + '.json'), dict(version=1, sha=sha, exit_code=code, observed_at=utc()))
        legacy = ROOT / 'failed-release'
        if not legacy.exists() or legacy.read_text().splitlines()[0] == sha:
            atomic(legacy, (sha + '\n').encode())
        raise SystemExit(code)
    emit('VERIFIED_COMPLETE', build_sha=sha)


def cancelled(signum, frame):
    global _cancelled
    _cancelled = True
    if _child is not None:
        # TERM deployment CLIENTS only. Docker's detached valid backup remains.
        try:
            os.killpg(_child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--backup-only', action='store_true')
    modes.add_argument('--stop-backup-idle', action='store_true')
    modes.add_argument('--journal-begin', action='store_true')
    modes.add_argument('--journal-update', action='store_true')
    modes.add_argument('--commit-release', action='store_true')
    modes.add_argument('--check-rollback', action='store_true')
    parser.add_argument('--sha')
    parser.add_argument('--image')
    parser.add_argument('--old-image')
    parser.add_argument('--new-image')
    parser.add_argument('--request-id')
    parser.add_argument('--wait-seconds', type=int, default=BACKUP_WAIT_MAX)
    parser.add_argument('--phase')
    args = parser.parse_args([] if argv is None else argv)
    old_handlers = {s: signal.signal(s, cancelled) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        with deployment_lock() as descriptor:
            if args.backup_only:
                managed_backup(args.sha, args.image, args.request_id, args.wait_seconds)
            elif args.stop_backup_idle:
                stop_backup_idle(args.wait_seconds)
            elif args.journal_begin:
                value = journal_begin(args.sha, args.image)
                print('\t'.join(str(value[key]) or '-' for key in ('attempt_id', 'work', 'old_image', 'new_image', 'phase')))
            elif args.journal_update:
                journal_update(args.sha, args.request_id, args.phase, args.image or '')
            elif args.commit_release:
                commit_release(args.sha, args.image, args.old_image, args.request_id)
            elif args.check_rollback:
                check_rollback(args.sha, args.image, args.new_image)
            else:
                poll(descriptor)
    except Busy as exc:
        if args.backup_only:
            pending = str(exc) in ('managed_backup_still_running', 'another_managed_backup_pending', 'previous_managed_backup_running')
            emit('PENDING' if pending else 'BUSY', reason=str(exc), request_id=args.request_id)
        else:
            emit('DEFERRED', reason=str(exc))
        raise SystemExit(75)
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (ValueError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        emit('FAILED_CLOSED', error_type=type(exc).__name__)
        raise SystemExit(1)
