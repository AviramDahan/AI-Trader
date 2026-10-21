#!/usr/bin/env python3
"""Root release gate and bounded backup coordination. Exit75 is retriable.

No path kills/removes a valid backup. Named no-restart jobs survive observers
and can be rejoined, including by a later protected activation operation.
"""
import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
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
from types import ModuleType
import urllib.request

# One reviewed module works beside repository and root-installed helpers.
_identity_path = Path(__file__).resolve().with_name('docker_image_identity.py')
_identity_fd = os.open(_identity_path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
with os.fdopen(_identity_fd, 'rb') as _identity_stream:
    _info = os.fstat(_identity_stream.fileno())
    if not stat.S_ISREG(_info.st_mode) or _info.st_size > 256 * 1024:
        raise ValueError('image_identity_module_shape_invalid')
    if _identity_path.parent == Path('/usr/local/sbin') and (_info.st_uid != 0 or _info.st_mode & 0o022):
        raise ValueError('installed_image_identity_module_unprotected')
    _identity_raw = _identity_stream.read(256 * 1024 + 1)
    _after = os.fstat(_identity_stream.fileno())
    if len(_identity_raw) != _info.st_size or (_info.st_mtime_ns, _info.st_ctime_ns) != (_after.st_mtime_ns, _after.st_ctime_ns):
        raise ValueError('image_identity_module_changed_during_read')
# Compile the exact single read. Timestamp/size-matched stale pyc is never run.
identity = ModuleType('_release_image_identity')
identity.__file__ = str(_identity_path)
exec(compile(_identity_raw, str(_identity_path), 'exec'), identity.__dict__)

REPO = 'AviramDahan/AI-Trader'
ROOT = Path('/opt/ai-trader-staging/deploy')
LOCK = Path('/run/lock/ai-trader-deploy.lock')
WORK_PARENT = Path('/opt')
BACKUP_WAIT_MAX = 1800
BACKUP_LOCK_WAIT = 900
BACKUP_PROOF_MAX_AGE = 1800
LABEL = 'ai-trader.managed-backup'
COMPATIBLE_CERTIFICATE = 'compatible-rollback-v1.json'
COMPATIBLE_PHASES = ('identity_bridge', 'identity_candidate', 'old_seed', 'candidate_preserve_v1',
    'candidate_intraday', 'bridge_creation_blocked', 'bridge_pending', 'bridge_restart',
    'candidate_emergency', 'bridge_emergency', 'old_reader_refused10', 'bridge_restore10',
    'bridge_restored_exits', 'bridge_resume', 'bridge_expiry', 'bridge_final')
COMPATIBLE_PROOFS = {'source-proof.json', 'ordered-proof.json', 'results.jsonl',
    'rollback-artifact.json', 'candidate-artifact.json', 'images.json'}
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


def image_identity(image, sha=None):
    return identity.resolve_image(exact_image(image), expected_build=sha, cache_dir=ROOT / 'image-identities')


def runtime_identity(row):
    return identity.resolve_running(row, cache_dir=ROOT / 'image-identities')


def verify_role(role, image, sha=None, healthy=True):
    if role not in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
        raise ValueError('invalid_release_role')
    value = image_identity(image, sha)
    identity.verify_container(inspect('container', 'ai-trader-cloud-' + role + '-1'), value, require_healthy=healthy)
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
    value = spec.get('image_identity') or image_identity(spec['image_id'], spec['build_sha'])
    identity.validate_identity(value)
    if value['runnable_ref'] != spec['image_id'] or value['build_sha'] != spec['build_sha']:
        raise ValueError('managed_backup_frozen_identity_conflict')
    identity.verify_container(row, value)
    if labels.get(LABEL) != spec['request_id']:
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
    spec['image_identity'] = image_identity(image, sha)
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
        saved = dict(record.get('spec') or {})
        # Older classic requests had no expanded identity. They remain strict;
        # no OCI request may be retroactively adopted without its frozen proof.
        if 'image_identity' not in saved and spec['image_identity']['kind'] == 'classic':
            saved['image_identity'] = spec['image_identity']
        if saved != spec:
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
        run(command, 60, env=dict(os.environ, APP_IMAGE=image, DOCKER_DEFAULT_PLATFORM=identity.PLATFORM,
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
    if type(proof.get('recovery_format')) is not int or not 1 <= proof['recovery_format'] <= 10:
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
    frozen_identity = runtime_identity(row)
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
        identity.verify_container(current, frozen_identity)
        if current['State']['Running']:
            run(['docker', 'stop', '--time', '30', name], 60)
        emit('BACKUP_STOPPED_WHILE_IDLE', container=name)
    finally:
        os.close(descriptor)


def canonical_identity(value):
    identity.validate_identity(value)
    return {key: value[key] for key in identity.FIELDS}


def sha256_value(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('compatible_proof_digest_invalid')
    return value


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result: raise ValueError('compatible_duplicate_json_key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('compatible_nonfinite_json')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


@contextmanager
def protected_stream(path, maximum):
    """Read exact protected bytes once; no symlink, unbounded file or TOCTOU."""
    path = Path(path)
    if not path.is_relative_to(ROOT): raise ValueError('compatible_path_outside_root')
    for parent in (path.parent, *path.parent.parents):
        if not parent.is_relative_to(ROOT): break
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('compatible_parent_unprotected')
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0 or
                stat.S_IMODE(opened.st_mode) != 0o600 or not 0 < opened.st_size <= maximum or
                (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise ValueError('compatible_file_unprotected_or_bound')
        yield stream
        after, linked = os.fstat(stream.fileno()), path.lstat()
        keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid')
        if any(getattr(opened, key) != getattr(after, key) or getattr(opened, key) != getattr(linked, key) for key in keys):
            raise ValueError('compatible_file_changed_during_read')


def protected_bytes(path, maximum):
    with protected_stream(path, maximum) as stream:
        value = stream.read(maximum+1)
        if len(value) != os.fstat(stream.fileno()).st_size: raise ValueError('compatible_file_bound')
        return value


def protected_digest(path, maximum):
    with protected_stream(path, maximum) as stream:
        result, size = hashlib.sha256(), 0
        while True:
            block = stream.read(65536)
            if not block: break
            size += len(block)
            if size > maximum: raise ValueError('compatible_file_bound')
            result.update(block)
        return result.hexdigest(), size


def repository_tree(sha):
    exact_sha(sha)
    request = urllib.request.Request(f'https://api.github.com/repos/{REPO}/git/commits/{sha}',
        headers={'User-Agent': 'AI-Trader-compatible-rollback-gate'})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(65537)
    if len(raw) > 65536: raise ValueError('compatible_source_response_bound')
    data = strict_json(raw)
    if data.get('sha') != sha: raise ValueError('compatible_repository_sha_mismatch')
    return exact_sha(data.get('tree', {}).get('sha'))


def paused_entry_proof():
    """One bounded read-only settings observation; never initializes workers."""
    code = '''import json,hashlib
from database import get_db_connection
import entry_emergency
with get_db_connection() as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
 c.execute("SET LOCAL statement_timeout='5s'")
 c.execute("SET LOCAL lock_timeout='2s'")
 c.execute("SET LOCAL idle_in_transaction_session_timeout='10s'")
 assert c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
 assert c.execute('SHOW transaction_isolation').fetchone()['transaction_isolation']=='repeatable read'
 value=entry_emergency.snapshot(c.cursor())
 assert value['paused'] is True and type(value['revision']) is int and value['revision']>0
 raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
 print(json.dumps(dict(revision=value['revision'],updated_at=value['updated_at'],control_sha256=hashlib.sha256(raw).hexdigest())))
'''
    return strict_json(run(['docker', 'exec', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e',
        'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=2000',
        'ai-trader-cloud-api-1', 'python', '-c', code], 20))


def binary_capabilities(image, *, immutable=False):
    code = ('import json,os,entry_discovery_capabilities as c; '
        'print(json.dumps({"build_sha":os.environ["BUILD_SHA"],"capabilities":c.capabilities()}))')
    if immutable:
        code = ('import json,os,pathlib,entry_discovery_capabilities as c; '
            'p=pathlib.Path(c.__file__); '
            'assert os.geteuid()==10001 and p.stat().st_uid==p.parent.stat().st_uid==0 and '
            'p.stat().st_mode&0o222==0 and not os.access(p.parent,os.W_OK); '
            'print(json.dumps({"build_sha":os.environ["BUILD_SHA"],"capabilities":c.capabilities(),'
            '"immutable_file_and_parent_verified":True}))')
    return strict_json(run(['docker', 'run', '--platform', identity.PLATFORM, '--pull=never', '--rm', '--network', 'none', '--read-only',
        '--cpus', '0.25', '--memory', '128m', '--memory-swap', '128m', '--pids-limit', '64',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--entrypoint', 'python', exact_image(image), '-c', code], 60))


def _validate_compatible_certificate(sha, old, new=None):
    """Explicit format10 transition, not a relaxation of actual-old rollback."""
    exact_sha(sha); exact_image(old)
    actual_old = canonical_identity(image_identity(old))
    for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
        verify_role(role, old, actual_old['build_sha'])
    raw = protected_bytes(ROOT / COMPATIBLE_CERTIFICATE, 32768)
    value = strict_json(raw)
    keys = {'version', 'candidate_sha', 'artifact_build_sha', 'source_tree', 'verified_at', 'expires_at',
        'actual_old_identity', 'runtime_sha256', 'marker_sha256', 'identity_module_sha256',
        'bridge_identity', 'candidate_identity', 'bridge_archive', 'candidate_archive',
        'probe_sha256', 'fixtures_sha256', 'target_proof_sha256', 'proof', 'capabilities', 'entry_pause', 'proof_files'}
    if (type(value) is not dict or set(value) != keys or type(value['version']) is not int or value['version'] != 1
            or value['candidate_sha'] != sha or value['artifact_build_sha'] != sha
            or value['proof'] != 'TARGET_ISOLATED16_FORMAT10_PHASES_PASS'):
        raise ValueError('compatible_certificate_shape_or_source_invalid')
    verified, expires = aware(value['verified_at']), aware(value['expires_at'])
    now = datetime.now(timezone.utc)
    if (verified > now or now-verified > timedelta(hours=6) or not timedelta(0) < expires-verified <= timedelta(hours=6)
            or expires-now < timedelta(hours=2)):
        raise ValueError('compatible_certificate_expired_or_future')
    if value['source_tree'] != repository_tree(sha):
        raise ValueError('compatible_candidate_tree_mismatch')
    if (set(value['actual_old_identity']) != identity.FIELDS or
            canonical_identity(value['actual_old_identity']) != actual_old):
        raise ValueError('compatible_actual_old_identity_changed')
    for key in ('bridge_identity', 'candidate_identity'):
        expected = value[key]
        if set(expected) != identity.FIELDS or canonical_identity(expected) != expected or expected['build_sha'] != sha:
            raise ValueError('compatible_identity_shape_invalid')
        if canonical_identity(image_identity(expected['runnable_ref'], sha)) != expected:
            raise ValueError('compatible_loaded_image_changed')
    if value['bridge_identity']['runnable_ref'] in (old, value['candidate_identity']['runnable_ref']):
        raise ValueError('compatible_distinct_bridge_required')
    if new is not None and new != value['candidate_identity']['runnable_ref']:
        raise ValueError('compatible_candidate_image_changed')
    for key, path in (('runtime_sha256', ROOT/'runtime.env'), ('marker_sha256', ROOT/'last-release')):
        if protected_digest(path, 65536)[0] != sha256_value(value[key]):
            raise ValueError('compatible_runtime_or_marker_changed')
    if sha256_value(value['identity_module_sha256']) != hashlib.sha256(_identity_raw).hexdigest():
        raise ValueError('compatible_identity_module_changed')
    pause = value['entry_pause']
    if (type(pause) is not dict or set(pause) != {'revision', 'updated_at', 'control_sha256'}
            or type(pause['revision']) is not int or pause['revision'] <= 0):
        raise ValueError('compatible_entry_pause_invalid')
    aware(pause['updated_at']); sha256_value(pause['control_sha256'])
    if paused_entry_proof() != pause: raise ValueError('compatible_entry_pause_changed')
    folder = ROOT / 'entry-intraday-rollback-v1' / sha
    for role in ('bridge', 'candidate'):
        archive = value[role+'_archive']
        if (type(archive) is not dict or set(archive) != {'filename', 'sha256', 'bytes', 'config_digest'}
                or archive['filename'] not in (f'entry-intraday-{role}-tested.tar.gz', f'entry-intraday-{role}-tested.tar.xz')
                or type(archive['bytes']) is not int or not 0 < archive['bytes'] <= 250*1024*1024
                or archive['config_digest'] != value[role+'_identity']['config_digest']):
            raise ValueError('compatible_archive_shape_invalid')
        if protected_digest(folder/archive['filename'], 250*1024*1024) != (sha256_value(archive['sha256']), archive['bytes']):
            raise ValueError('compatible_archive_hash_changed')
    proof_files = value['proof_files']
    if type(proof_files) is not dict or set(proof_files) != COMPATIBLE_PROOFS:
        raise ValueError('compatible_proof_files_invalid')
    documents = {}
    for name in sorted(COMPATIBLE_PROOFS):
        content = protected_bytes(folder/name, 65536)
        if hashlib.sha256(content).hexdigest() != sha256_value(proof_files[name]):
            raise ValueError('compatible_proof_file_changed')
        documents[name] = ([strict_json(line) for line in content.decode().splitlines()]
                           if name == 'results.jsonl' else strict_json(content))
    source, ordered = documents['source-proof.json'], documents['ordered-proof.json']
    if (source.get('source_commit') != sha or source.get('source_tree') != value['source_tree']
            or ordered.get('source_commit') != sha or ordered.get('actual_pass_count') != 16
            or ordered.get('recovery_format') != 10 or ordered.get('phases') != list(COMPATIBLE_PHASES)
            or source.get('file_sha256', {}).get('scripts/entry_intraday_compatibility_probe.py') != sha256_value(value['probe_sha256'])):
        raise ValueError('compatible_ci_source_or_order_invalid')
    def phases(values, strict=False):
        if type(values) is not list or [r.get('phase') for r in values] != list(COMPATIBLE_PHASES):
            raise ValueError('compatible_phase_order_invalid')
        for row in values:
            if strict and set(row) != {'phase', 'status', 'build_sha', 'probe_sha256'}:
                raise ValueError('compatible_target_phase_shape_invalid')
            expected = actual_old['build_sha'] if row['phase'] in ('old_seed', 'old_reader_refused10') else sha
            if row.get('status') != 'PASS' or row.get('build_sha') != expected or row.get('probe_sha256') != value['probe_sha256']:
                raise ValueError('compatible_phase_source_invalid')
    phases(documents['results.jsonl'])
    images = documents['images.json']
    if type(images) is not list or len(images) != 3 or {r.get('role') for r in images} != {'old', 'bridge', 'candidate'}:
        raise ValueError('compatible_ci_images_invalid')
    for role in ('bridge', 'candidate'):
        image = next(row for row in images if row['role'] == role)
        artifact = documents['rollback-artifact.json' if role == 'bridge' else 'candidate-artifact.json']
        archive = value[role+'_archive']
        if (image.get('build_sha') != sha or image.get('config_digest') != archive['config_digest']
                or artifact.get('source_commit') != sha or artifact.get('archive_sha256') != archive['sha256']
                or artifact.get('archive_bytes') != archive['bytes'] or artifact.get('retained_filename') != archive['filename']
                or artifact.get('verified_loaded_image_id') != image.get('image_id')
                or artifact.get('loaded_capability_verified') is not True
                or artifact.get('status') != f'TESTED_FORMAT10_{role.upper()}_ARCHIVE_RETAINED_ONE_DAY'):
            raise ValueError('compatible_ci_archive_identity_invalid')
    target_raw = protected_bytes(folder/'target-proof.json', 65536)
    if hashlib.sha256(target_raw).hexdigest() != sha256_value(value['target_proof_sha256']):
        raise ValueError('compatible_target_proof_changed')
    target = strict_json(target_raw)
    target_keys = {'version', 'candidate_sha', 'source_tree', 'actual_old_identity', 'bridge_identity',
        'candidate_identity', 'runtime_sha256', 'marker_sha256', 'identity_module_sha256',
        'probe_sha256', 'fixtures_sha256', 'entry_pause', 'phases'}
    if (type(target) is not dict or set(target) != target_keys or type(target['version']) is not int or target['version'] != 1
            or any(json.dumps(target[key], sort_keys=True, allow_nan=False) !=
                   json.dumps(value[key], sort_keys=True, allow_nan=False) for key in target_keys-{'version', 'phases'})):
        raise ValueError('compatible_target_binding_invalid')
    phases(target['phases'], strict=True)
    if protected_digest(folder/'fixtures.tar.gz', 16*1024*1024)[0] != sha256_value(value['fixtures_sha256']):
        raise ValueError('compatible_fixtures_changed')
    bridge = binary_capabilities(value['bridge_identity']['runnable_ref'], immutable=True)
    candidate = binary_capabilities(value['candidate_identity']['runnable_ref'], immutable=True)
    expected_caps = dict(build_role='bridge', independent_creation=False, snapshot_formats=list(range(1, 11)),
        audit_version='entry_discovery_intraday_v1', audit_versions=['entry_discovery_v1', 'entry_discovery_intraday_v1'],
        execution_version='independent_entry_execution_intraday_v1',
        execution_versions=['independent_entry_execution_v1', 'independent_entry_execution_intraday_v1'],
        emergency_entry_version='paper_entry_emergency_v1')
    for observed, expected in ((bridge, expected_caps), (candidate, dict(expected_caps, build_role='candidate', independent_creation=True))):
        if (observed.get('build_sha') != sha or observed.get('immutable_file_and_parent_verified') is not True
                or json.dumps(observed.get('capabilities'), sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True)):
            raise ValueError('compatible_binary_capability_mismatch')
    if json.dumps(value['capabilities'], sort_keys=True, allow_nan=False) != json.dumps(expected_caps, sort_keys=True):
        raise ValueError('compatible_certificate_capabilities_invalid')
    return dict(value, certificate_sha256=hashlib.sha256(raw).hexdigest())


def validate_compatible_certificate(sha, old, new=None):
    try:
        return _validate_compatible_certificate(sha, old, new)
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError):
        raise ValueError('compatible_certificate_shape_invalid') from None


def compatible_candidate(sha, old):
    exact_sha(sha); exact_image(old)
    path = ROOT / COMPATIBLE_CERTIFICATE
    if not path.exists() and not path.is_symlink(): return '-'
    return validate_compatible_certificate(sha, old)['candidate_identity']['runnable_ref']


def freeze_rollback(sha, request_id, old, new, selected, certificate=None):
    if not re.fullmatch('[0-9a-f]{32}', request_id or ''): raise ValueError('invalid_rollback_attempt')
    path = ROOT/'deployment-attempt.json'
    value = strict_json(protected_bytes(path, 32768))
    if (value.get('sha') != sha or value.get('attempt_id') != request_id or value.get('old_image') != old
            or value.get('new_image') != new or value.get('phase') not in ('BUILDING', 'PREDEPLOY_PENDING')):
        raise ValueError('rollback_selection_attempt_mismatch')
    fields = dict(rollback_image=selected['runnable_ref'], rollback_identity=selected,
        rollback_mode='CERTIFIED_FORMAT10_BRIDGE' if certificate else 'ACTUAL_PREVIOUS',
        rollback_certificate_sha256=certificate['certificate_sha256'] if certificate else None,
        observed_old_identity=canonical_identity(image_identity(old)))
    if certificate:
        fields.update(entry_pause=certificate['entry_pause'], runtime_sha256=certificate['runtime_sha256'],
                      marker_sha256=certificate['marker_sha256'])
    if any(key in value and value[key] != item for key, item in fields.items()):
        raise ValueError('rollback_selection_changed')
    value.update(fields)
    atomic_json(path, value)


def verify_rollback_selection(sha, old, new, request_id):
    """Recheck pause/runtime at the writer boundary after a long safe backup."""
    value = strict_json(protected_bytes(ROOT/'deployment-attempt.json', 32768))
    if (value.get('sha') != exact_sha(sha) or value.get('attempt_id') != request_id
            or value.get('old_image') != exact_image(old) or value.get('new_image') != exact_image(new)
            or value.get('phase') != 'DRAIN_PENDING' or value.get('rollback_mode') != 'CERTIFIED_FORMAT10_BRIDGE'):
        raise ValueError('rollback_writer_boundary_attempt_invalid')
    for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
        verify_role(role, old, value['observed_old_identity']['build_sha'], healthy=role != 'backup')
    if (paused_entry_proof() != value.get('entry_pause') or
            protected_digest(ROOT/'runtime.env',65536)[0] != value.get('runtime_sha256') or
            protected_digest(ROOT/'last-release',65536)[0] != value.get('marker_sha256')):
        raise ValueError('rollback_writer_boundary_pause_or_runtime_changed')
    if canonical_identity(image_identity(value['rollback_image'])) != value.get('rollback_identity'):
        raise ValueError('rollback_writer_boundary_image_changed')
    emit('FROZEN_ROLLBACK_WRITER_BOUNDARY_VERIFIED', build_sha=sha, observed_old_image=old,
         rollback_image=value['rollback_image'], entry_paused=True)


def check_rollback(sha, old, new, request_id=None):
    """Schema equality is not entry/backup compatibility; probe real binaries."""
    exact_sha(sha)
    results = []
    for image in (exact_image(old), exact_image(new)):
        image_proof = image_identity(image)
        if image == old:
            for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
                verify_role(role, old)
        value = binary_capabilities(image)
        if value.get('build_sha') != image_proof['build_sha']:
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
        if not (ROOT/COMPATIBLE_CERTIFICATE).exists() and not (ROOT/COMPATIBLE_CERTIFICATE).is_symlink():
            raise ValueError('actual_previous_image_not_compatible_with_candidate')
        certificate = validate_compatible_certificate(sha, old, new)
        selected = certificate['bridge_identity']
        if not request_id: raise ValueError('certified_rollback_requires_durable_attempt')
        freeze_rollback(sha, request_id, old, new, selected, certificate)
        emit('CERTIFIED_ROLLBACK_TARGET_VERIFIED', observed_old_image=old, new_image=new,
             rollback_image=selected['runnable_ref'], build_sha=sha)
        return selected['runnable_ref']
    if request_id:
        freeze_rollback(sha, request_id, old, new, canonical_identity(image_identity(old)))
    emit('ROLLBACK_BINARY_CAPABILITIES_VERIFIED', old_image=old, new_image=new,
        old_build_sha=previous['build_sha'], build_sha=sha, capabilities=a)
    return old


def journal_begin(sha, old):
    exact_sha(sha)
    exact_image(old)
    old_identity = image_identity(old)
    for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
        identity.verify_container(inspect('container', 'ai-trader-cloud-' + role + '-1'), old_identity, require_healthy=True)
    path = ROOT / 'deployment-attempt.json'
    if path.exists():
        previous = json.loads(path.read_text())
        if previous.get('phase') not in ('COMPLETE', 'FAILED', 'ROLLED_BACK'):
            if previous.get('sha') == sha and previous.get('phase') in ('DEFERRED_PREDEPLOY', 'DEFERRED_DRAIN'):
                if previous.get('old_image') != old:
                    raise ValueError('pending_release_old_runtime_changed')
                for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
                    verify_role(role, old)
                if not Path(previous['work']).is_dir():
                    raise ValueError('pending_release_work_missing')
                return previous
            raise ValueError('interrupted_release_requires_operator_review')
    work = tempfile.mkdtemp(prefix='ai-trader-release.', dir=WORK_PARENT)
    value = dict(version=1, attempt_id=os.urandom(16).hex(), sha=sha, old_image=old,
        new_image='', phase='STARTED', work=work, started_at=utc(), updated_at=utc())
    value['old_identity'] = old_identity
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
    value = image_identity(image, sha)
    for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
        row = inspect('container', 'ai-trader-cloud-' + role + '-1')
        try:
            identity.verify_container(row, value, require_healthy=True)
        except ValueError:
            return False
    return True


def protected_review_archive(path):
    file = path.lstat()
    if not stat.S_ISREG(file.st_mode) or file.st_uid != 0 or file.st_mode & 0o077 or file.st_size > 16384:
        raise ValueError('review_original_archive_unprotected')
    return path.read_bytes()


def review_close_prewriter(sha, attempt_id, old):
    """EXPLICIT operator review only; preserve original journal and all latches."""
    exact_sha(sha)
    if not re.fullmatch('[0-9a-f]{32}', attempt_id or ''):
        raise ValueError('invalid_review_attempt')
    path = ROOT / 'deployment-attempt.json'
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError('review_current_journal_invalid')
    raw = path.read_bytes()
    value = json.loads(raw)
    original = value
    archives = ROOT / 'reviewed-attempts'
    archive = archives / (attempt_id + '.json')
    rejoined = value.get('phase') == 'FAILED'
    if rejoined:
        review = value.get('review') or {}
        if not archive.exists() or archive.is_symlink():
            raise ValueError('review_original_archive_missing')
        raw = protected_review_archive(archive)
        original = json.loads(raw)
        if review.get('version') != 1 or review.get('reason') != 'VERIFIED_PREWRITER_ABORT' or review.get('archive') != archive.name or review.get('archive_sha256') != hashlib.sha256(raw).hexdigest():
            raise ValueError('review_original_archive_proof_invalid')
    if type(original.get('version')) is not int or original['version'] != 1 or value.get('sha') != sha or value.get('attempt_id') != attempt_id or original.get('sha') != sha or original.get('attempt_id') != attempt_id or original.get('phase') not in ('STARTED', 'BUILDING', 'PREDEPLOY_PENDING') or (not rejoined and value.get('phase') not in ('STARTED', 'BUILDING', 'PREDEPLOY_PENDING')):
        raise ValueError('review_requires_exact_prewriter_attempt')
    work = Path(original['work'])
    work_info = work.lstat()
    if work.parent != WORK_PARENT or not re.fullmatch(r'ai-trader-release\.[A-Za-z0-9_-]+', work.name) or not stat.S_ISDIR(work_info.st_mode) or work_info.st_uid != 0 or stat.S_IMODE(work_info.st_mode) != 0o700 or (work / 'previous-compose.yml').exists():
        raise ValueError('review_cannot_prove_writers_untouched')
    directory = ROOT / 'backup-requests'
    if (directory / (attempt_id + '.json')).exists() or inspect('container', 'ai-trader-managed-backup-' + attempt_id) is not None:
        raise ValueError('review_managed_backup_exists')
    if (directory / 'active.json').exists():
        active = json.loads((directory / 'active.json').read_bytes())
        if type(active.get('version')) is not int or active['version'] != 1 or not re.fullmatch('[0-9a-f]{32}', active.get('request_id', '')) or active.get('state') != 'VERIFIED_COMPLETE':
            raise ValueError('review_other_backup_not_complete')
        previous = inspect('container', 'ai-trader-managed-backup-' + active.get('request_id', ''))
        if previous is None or previous.get('State', {}).get('Running'):
            raise ValueError('review_previous_backup_unknown')
    proof = image_identity(old)
    if rejoined and value['review'].get('old_identity') != proof:
        raise ValueError('review_rejoin_identity_changed')
    legacy = original.get('old_image')
    for role in ('api', 'scanner', 'monitor', 'telegram', 'backup'):
        row = inspect('container', 'ai-trader-cloud-' + role + '-1')
        identity.verify_container(row, proof, require_healthy=True)
        if legacy != old and row.get('Image') != legacy:
            raise ValueError('review_observed_old_runtime_changed')
    private_dir(archives)
    if archive.exists():
        if protected_review_archive(archive) != raw: raise ValueError('review_original_archive_conflict')
    else:
        atomic(archive, raw)
    if not rejoined:
        value.update(phase='FAILED', updated_at=utc(), review=dict(version=1,
            reason='VERIFIED_PREWRITER_ABORT', archive=archive.name,
            archive_sha256=hashlib.sha256(raw).hexdigest(), old_identity=proof))
        atomic_json(path, value)
    emit('REVIEWED_PREWRITER_FAILED', build_sha=sha, attempt_id=attempt_id,
        archive=archive.name, archive_sha256=hashlib.sha256(raw).hexdigest(), old_identity=proof)


def completed(sha, *, allow_committing=False):
    path = ROOT / 'last-release'
    if not path.exists():
        return False
    values = path.read_text().splitlines()
    if len(values) < 2 or values[0] != sha:
        return False
    image = exact_image(values[1])
    journal = ROOT/'deployment-attempt.json'
    if not journal.exists(): return False
    value = strict_json(protected_bytes(journal, 32768))
    phases = ('COMPLETE', 'COMMITTING') if allow_committing else ('COMPLETE',)
    if (value.get('sha') != sha or value.get('phase') not in phases
            or value.get('new_image') != image or value.get('rollback_image') == image):
        return False
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
    rollback = value.get('rollback_image', old)
    if rollback != old:
        if value.get('rollback_mode') != 'CERTIFIED_FORMAT10_BRIDGE':
            raise ValueError('release_commit_rollback_mode_invalid')
        certificate = ROOT/COMPATIBLE_CERTIFICATE
        # Consume exactly this reviewed certificate under the existing release
        # lock. A later release cannot silently reuse another attempt's pin.
        directory = ROOT/'entry-intraday-rollback-v1'/sha
        for parent in (directory, *directory.parents):
            if not parent.is_relative_to(ROOT): break
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('compatible_consumed_parent_unprotected')
        archive = directory/f'consumed-{attempt_id}.json'
        if archive.exists() or archive.is_symlink():
            # Atomic rename may have committed immediately before a remote
            # marker/client failure. Rejoin ONLY the exact frozen attempt copy.
            if certificate.exists() or certificate.is_symlink():
                raise ValueError('compatible_consumed_archive_conflict')
            raw = protected_bytes(archive, 32768)
        else:
            raw = protected_bytes(certificate, 32768)
        if hashlib.sha256(raw).hexdigest() != value.get('rollback_certificate_sha256'):
            raise ValueError('release_commit_certificate_changed')
        if not archive.exists(): os.rename(certificate, archive)
    code = ('import os,sys,tempfile; from pathlib import Path; '
        'p=Path("/app/.runtime/deployed-release"); '
        'fd,t=tempfile.mkstemp(prefix=".deployed-release-",dir=p.parent); '
        'f=os.fdopen(fd,"w"); f.write(sys.argv[1]); f.flush(); os.fsync(f.fileno()); '
        'f.close(); os.replace(t,p); d=os.open(p.parent,os.O_RDONLY); os.fsync(d); os.close(d)')
    run(['docker', 'exec', 'ai-trader-cloud-api-1', 'python', '-c', code, sha], 30)
    marker = sha + '\n' + image + '\n' + rollback + '\n'
    if rollback != old: marker += old + '\n'  # observed old is not the supported rollback image
    atomic(ROOT / 'last-release', marker.encode())
    if not completed(sha, allow_committing=True):
        raise ValueError('release_commit_not_verified')
    journal_update(sha, attempt_id, 'COMPLETE', image)
    if not completed(sha): raise ValueError('release_complete_journal_not_verified')
    emit('VERIFIED_COMPLETE', build_sha=sha, image_id=image)


def record_bridge_rollback(sha, image, old, attempt_id):
    """Truthful failure marker; never marks a Bridge as a completed candidate."""
    value = strict_json(protected_bytes(ROOT/'deployment-attempt.json', 32768))
    if (value.get('sha') != exact_sha(sha) or value.get('attempt_id') != attempt_id
            or value.get('phase') != 'ROLLING_BACK' or value.get('old_image') != exact_image(old)
            or value.get('rollback_mode') != 'CERTIFIED_FORMAT10_BRIDGE'
            or value.get('rollback_image') != exact_image(image)):
        raise ValueError('bridge_rollback_attempt_mismatch')
    frozen = value['rollback_identity']
    if canonical_identity(image_identity(image, frozen['build_sha'])) != frozen:
        raise ValueError('bridge_rollback_identity_changed')
    if not healthy_roles(frozen['build_sha'], image): raise ValueError('bridge_rollback_not_ready')
    # Do not reapply certificate expiry: this is the already-needed, frozen
    # supported rollback. It must remain available after a long forward failure.
    pause = paused_entry_proof()
    expected_pause = value.get('entry_pause')
    if expected_pause is not None and pause != expected_pause:
        raise ValueError('bridge_rollback_entry_pause_changed')
    marker = 'ROLLBACK_BRIDGE:' + frozen['build_sha'] + ':' + image
    code = ('import os,sys,tempfile; from pathlib import Path; '
        'p=Path("/app/.runtime/deployed-release"); '
        'fd,t=tempfile.mkstemp(prefix=".deployed-release-",dir=p.parent); '
        'f=os.fdopen(fd,"w"); f.write(sys.argv[1]); f.flush(); os.fsync(f.fileno()); '
        'f.close(); os.replace(t,p); d=os.open(p.parent,os.O_RDONLY); os.fsync(d); os.close(d); print(p.read_text())')
    if run(['docker', 'exec', 'ai-trader-cloud-api-1', 'python', '-c', code, marker], 30).decode().strip() != marker:
        raise ValueError('bridge_rollback_marker_not_verified')
    atomic_json(ROOT/'last-rollback.json', dict(version=1, candidate_sha=sha,
        attempt_id=attempt_id, observed_old_image=old, rollback_identity=frozen,
        state='SUPPORTED_BRIDGE_NOT_COMPLETED_CANDIDATE', observed_at=utc(), entry_pause=pause))
    emit('SUPPORTED_BRIDGE_ROLLBACK_VERIFIED', candidate_sha=sha, rollback_image=image,
         observed_old_image=old, candidate_release_complete=False)


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
    modes.add_argument('--compatible-candidate', action='store_true')
    modes.add_argument('--record-bridge-rollback', action='store_true')
    modes.add_argument('--verify-rollback-selection', action='store_true')
    modes.add_argument('--resolve-running', action='store_true')
    modes.add_argument('--verify-role', action='store_true')
    modes.add_argument('--review-close-prewriter', action='store_true')
    parser.add_argument('--sha')
    parser.add_argument('--image')
    parser.add_argument('--old-image')
    parser.add_argument('--new-image')
    parser.add_argument('--request-id')
    parser.add_argument('--wait-seconds', type=int, default=BACKUP_WAIT_MAX)
    parser.add_argument('--phase')
    parser.add_argument('--role', choices=('api', 'scanner', 'monitor', 'telegram', 'backup'))
    parser.add_argument('--print-ref', action='store_true')
    parser.add_argument('--allow-stopped', action='store_true')
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
                if args.print_ref:
                    with redirect_stdout(sys.stderr):
                        selected = check_rollback(args.sha, args.image, args.new_image, args.request_id)
                    print(selected)
                else:
                    check_rollback(args.sha, args.image, args.new_image, args.request_id)
            elif args.compatible_candidate:
                selected = compatible_candidate(args.sha, args.image)
                if args.print_ref: print(selected)
                else: emit('COMPATIBLE_CANDIDATE_VERIFIED', image_id=selected)
            elif args.record_bridge_rollback:
                record_bridge_rollback(args.sha, args.image, args.old_image, args.request_id)
            elif args.verify_rollback_selection:
                verify_rollback_selection(args.sha, args.old_image, args.image, args.request_id)
            elif args.resolve_running:
                value = runtime_identity(inspect('container', 'ai-trader-cloud-' + (args.role or 'api') + '-1'))
                if args.print_ref: print(value['runnable_ref'])
                else: emit('RUNTIME_IDENTITY_VERIFIED', identity=value)
            elif args.verify_role:
                value = verify_role(args.role, args.image, args.sha, not args.allow_stopped)
                emit('ROLE_IDENTITY_VERIFIED', role=args.role, identity=value)
            elif args.review_close_prewriter:
                review_close_prewriter(args.sha, args.request_id, args.image)
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
