"""Reviewer-owned deployment-transition controls; no Docker/server/backup IO.

Docker observations are synthetic. The controller, proof validation, canonical
container association and durable temporary request state are the actual code.
Native Linux lock/process evidence remains in its separate mandatory CI suite.
"""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_deployment_backup_recovery import load_file
from test_deployment_bridge10 import (BRIDGE, NEW, OLD, certificate_case,
    controller)

ROOT = Path(__file__).resolve().parents[3]
SHA = 'a'*40
IMAGE = 'sha256:'+'b'*64
REQUEST = 'c'*32
NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('Bridge transition QA forbids external IO')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def completed_backup(tmp_path, monkeypatch, recovery_format):
    module = load_file(ROOT/'deploy/hetzner-pull.py', 'reviewer_bridge10_pull', monkeypatch)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'datetime', Clock)
    # Only the root-owned-directory precondition is doubled on an unprivileged
    # Windows/CI runner. Actual request JSON and canonical validator stay real.
    monkeypatch.setattr(module, 'private_dir', lambda p: p.mkdir(mode=0o700, exist_ok=True))
    if sys.platform == 'win32':
        atomic = module.atomic
        def portable_atomic(path, data):
            try:
                atomic(path, data)
            except PermissionError:
                # Windows cannot open/fsync a directory using the POSIX path.
                # Keep the real file fsync+replace; tolerate only the final
                # directory-open failure after these exact bytes are present.
                assert path.is_file() and path.read_bytes() == data
        monkeypatch.setattr(module, 'atomic', portable_atomic)
    identity = dict(version=1, kind='classic', runnable_ref=IMAGE,
        platform='linux/amd64', platform_manifest=None, config_digest=IMAGE,
        build_sha=SHA, user='10001:10001')
    monkeypatch.setattr(module, 'image_identity', lambda image, sha=None: copy.deepcopy(identity))
    spec = module.backup_spec(SHA, IMAGE, REQUEST)
    spec['image_identity'] = copy.deepcopy(identity)
    job = dict(Id='d'*64, Name='/'+spec['name'], Image=IMAGE,
        Config=dict(Image=IMAGE, Env=['BUILD_SHA='+SHA], User='10001:10001',
            Entrypoint=['python'], Cmd=spec['command'], Labels={
                module.LABEL: REQUEST, module.LABEL+'.build_sha': SHA,
                module.LABEL+'.phase': 'predeploy'}),
        HostConfig=dict(RestartPolicy=dict(Name='no'), PortBindings={}),
        NetworkSettings=dict(Networks={'isolated-fixture': {}}),
        Mounts=[dict(Destination='/backup', Type='volume', Source='/synthetic/backup', RW=True)],
        State=dict(Running=False, ExitCode=0, OOMKilled=False,
            StartedAt=(NOW-timedelta(seconds=50)).isoformat(),
            FinishedAt=(NOW-timedelta(seconds=1)).isoformat()))
    standing = copy.deepcopy(job)
    standing['Name'] = '/ai-trader-cloud-backup-1'
    monkeypatch.setattr(module, 'inspect', lambda kind, name:
        copy.deepcopy(standing if name=='ai-trader-cloud-backup-1' else job))
    directory = tmp_path/'backup-requests'
    directory.mkdir()
    request_path = directory/(REQUEST+'.json')
    request_path.write_text(json.dumps(dict(version=1, spec=spec,
        container_id=job['Id'], requested_at=(NOW-timedelta(seconds=60)).isoformat(),
        state='RUNNING_PENDING')))
    proof = dict(snapshot_id='e'*64, recovery_format=recovery_format,
        managed_request=dict(request_id=REQUEST, build_sha=SHA, predeploy=True,
            remote_commit='f'*40, started_at=(NOW-timedelta(seconds=40)).isoformat(),
            finished_at=(NOW-timedelta(seconds=2)).isoformat()))
    commands = []
    def synthetic(command, *a, **k):
        commands.append(command)
        assert command == ['docker', 'logs', '--tail', '20', spec['name']]
        return (json.dumps(proof)+'\n').encode()
    monkeypatch.setattr(module, 'run', synthetic)
    return module, proof, request_path, commands


@pytest.mark.parametrize('recovery_format', [1, 9, 10])
def test_completed_known_format_proof_keeps_all_request_source_and_clock_guards(
        tmp_path, monkeypatch, recovery_format):
    module, proof, request_path, commands = completed_backup(tmp_path, monkeypatch, recovery_format)
    assert module.managed_backup(SHA, IMAGE, REQUEST, 1) == proof
    assert json.loads(request_path.read_text())['state'] == 'VERIFIED_COMPLETE'
    assert len(commands) == 1  # no launch, stop, kill, remove or restart


@pytest.mark.parametrize('recovery_format', [True, False, 0, 11, '10', 10.0, None])
def test_unknown_or_nonstrict_format_cannot_complete_backup(tmp_path, monkeypatch, recovery_format):
    module, _, request_path, _ = completed_backup(tmp_path, monkeypatch, recovery_format)
    with pytest.raises(ValueError, match='managed_backup_recovery_format_invalid'):
        module.managed_backup(SHA, IMAGE, REQUEST, 1)
    assert json.loads(request_path.read_text())['state'] != 'VERIFIED_COMPLETE'


@pytest.mark.parametrize('damage', ['request', 'source', 'remote_commit', 'future_finish', 'before_job_start'])
def test_format10_does_not_relax_other_backup_proof_bindings(tmp_path, monkeypatch, damage):
    module, proof, request_path, commands = completed_backup(tmp_path, monkeypatch, 10)
    if damage == 'request':
        proof['managed_request']['request_id'] = '0'*32
    elif damage == 'source':
        proof['managed_request']['build_sha'] = '0'*40
    elif damage == 'remote_commit':
        proof['managed_request']['remote_commit'] = 'not-a-commit'
    elif damage == 'future_finish':
        proof['managed_request']['finished_at'] = (NOW+timedelta(seconds=1)).isoformat()
    else:
        proof['managed_request']['started_at'] = (NOW-timedelta(seconds=51)).isoformat()
    with pytest.raises(ValueError):
        module.managed_backup(SHA, IMAGE, REQUEST, 1)
    assert json.loads(request_path.read_text())['state'] != 'VERIFIED_COMPLETE'
    assert len(commands) == 1


def attempt(case, module, phase='PREDEPLOY_PENDING'):
    value = dict(version=1, sha=SHA, attempt_id=REQUEST, old_image=OLD,
        new_image=NEW, phase=phase)
    case.write(module.ROOT/'deployment-attempt.json', json.dumps(value).encode())
    return value


def portable_writes(module, case, monkeypatch):
    if sys.platform == 'win32':
        monkeypatch.setattr(module, 'atomic', lambda path, raw: case.write(path, raw))


@pytest.mark.parametrize('damage', ['artifact_sha', 'candidate_build', 'bridge_build',
    'pause_clock', 'pause_hash', 'pause_revision', 'marker', 'identity_module',
    'duplicate_phase', 'phase_source', 'fixture_bytes', 'candidate_archive',
    'cert_parent_writable', 'cert_wrong_owner', 'cert_duplicate_key'])
def test_reviewed_transition_rejects_independent_nested_and_runtime_mutations(
        controller, monkeypatch, damage):
    case = certificate_case(controller, monkeypatch)
    value = case.value
    actual_pause = copy.deepcopy(case.pause)
    monkeypatch.setattr(controller, 'paused_entry_proof', lambda: copy.deepcopy(actual_pause))
    if damage == 'artifact_sha': value['artifact_build_sha'] = 'f'*40
    elif damage == 'candidate_build': value['candidate_identity']['build_sha'] = 'f'*40
    elif damage == 'bridge_build': value['bridge_identity']['build_sha'] = 'f'*40
    elif damage == 'pause_clock': value['entry_pause']['updated_at'] = '2026-10-20T00:00:00+00:00'
    elif damage == 'pause_hash': value['entry_pause']['control_sha256'] = 'f'*64
    elif damage == 'pause_revision': value['entry_pause']['revision'] += 1
    elif damage == 'marker': case.write(controller.ROOT/'last-release', b'changed marker')
    elif damage == 'identity_module': value['identity_module_sha256'] = 'f'*64
    elif damage in ('duplicate_phase', 'phase_source'):
        rows = copy.deepcopy(case.phases)
        if damage == 'duplicate_phase': rows[1] = copy.deepcopy(rows[0])
        else: rows[1]['build_sha'] = 'f'*40
        raw = b'\n'.join(json.dumps(row).encode() for row in rows)
        case.write(case.folder/'results.jsonl', raw)
        value['proof_files']['results.jsonl'] = controller.hashlib.sha256(raw).hexdigest()
    elif damage == 'fixture_bytes': case.write(case.folder/'fixtures.tar.gz', b'changed fixtures')
    elif damage == 'candidate_archive': case.write(case.folder/value['candidate_archive']['filename'], b'changed')
    elif damage == 'cert_parent_writable':
        import stat
        case.changes[controller.ROOT] = {'st_mode': stat.S_IFDIR | 0o777}
    elif damage == 'cert_wrong_owner': case.changes[case.path] = {'st_uid': 1000}
    case.save()
    if damage == 'cert_duplicate_key':
        raw = case.path.read_bytes()
        case.write(case.path, b'{"version":1,'+raw[1:])
    with pytest.raises(ValueError):
        controller.validate_compatible_certificate(SHA, OLD, NEW)


def test_same_sha_healthy_bridge_rollback_does_not_skip_failed_latch(controller, monkeypatch, capsys):
    case = certificate_case(controller, monkeypatch)
    value = attempt(case, controller, 'ROLLED_BACK')
    value.update(rollback_image=BRIDGE)
    case.write(controller.ROOT/'deployment-attempt.json', json.dumps(value).encode())
    case.write(controller.ROOT/'last-release', (SHA+'\n'+BRIDGE+'\n'+OLD+'\n').encode())
    case.write(controller.ROOT/'failed-release', (SHA+'\n').encode())
    monkeypatch.setattr(controller.subprocess, 'check_output', lambda *a, **k: SHA+'\trefs/heads/main\n')
    monkeypatch.setattr(controller, 'healthy_roles', lambda *a: True)
    controller.poll(9)
    assert json.loads(capsys.readouterr().out)['status'] == 'BLOCKED_FAILED_RELEASE'
    assert (controller.ROOT/'failed-release').read_text() == SHA+'\n'


def test_frozen_bridge_rollback_remains_usable_when_certificate_expires(controller, monkeypatch):
    case = certificate_case(controller, monkeypatch)
    portable_writes(controller, case, monkeypatch)
    attempt(case, controller)
    assert controller.check_rollback(SHA, OLD, NEW, REQUEST) == BRIDGE
    controller.journal_update(SHA, REQUEST, 'ROLLING_BACK', NEW)
    case.value['expires_at'] = '2000-01-01T00:00:00+00:00'
    case.save()
    monkeypatch.setattr(controller, 'healthy_roles', lambda *a: True)
    commands = []
    def observed_marker(args, *a, **k):
        commands.append(args)
        return args[-1].encode()
    monkeypatch.setattr(controller, 'run', observed_marker)
    controller.record_bridge_rollback(SHA, BRIDGE, OLD, REQUEST)
    saved = json.loads((controller.ROOT/'last-rollback.json').read_bytes())
    assert saved['state'] == 'SUPPORTED_BRIDGE_NOT_COMPLETED_CANDIDATE'
    assert saved['entry_pause'] == case.pause
    assert len(commands) == 1 and 'ROLLBACK_BRIDGE:' in commands[0][-1]
    assert not controller.completed(SHA)


def test_commit_crash_after_certificate_consumption_can_rejoin_same_attempt(controller, monkeypatch):
    case = certificate_case(controller, monkeypatch)
    portable_writes(controller, case, monkeypatch)
    attempt(case, controller)
    assert controller.check_rollback(SHA, OLD, NEW, REQUEST) == BRIDGE
    controller.journal_update(SHA, REQUEST, 'COMMITTING', NEW)
    monkeypatch.setattr(controller, 'healthy_roles', lambda *a: True)
    def interrupted(*a, **k):
        raise RuntimeError('injected marker transport interruption after certificate consumption')
    monkeypatch.setattr(controller, 'run', interrupted)
    with pytest.raises(RuntimeError, match='injected marker'):
        controller.commit_release(SHA, NEW, OLD, REQUEST)
    consumed = case.folder/('consumed-'+REQUEST+'.json')
    assert consumed.is_file()
    assert json.loads((controller.ROOT/'deployment-attempt.json').read_bytes())['phase'] == 'COMMITTING'
    monkeypatch.setattr(controller, 'run', lambda *a, **k: SHA.encode())
    controller.commit_release(SHA, NEW, OLD, REQUEST)
    assert controller.completed(SHA)


@pytest.mark.parametrize('damage', ['missing', 'wrong_image', 'wrong_source', 'unhealthy', 'not_running', 'oom'])
def test_any_changed_actual_old_role_rejects_transition_before_new_selection(controller, monkeypatch, damage):
    case = certificate_case(controller, monkeypatch)
    inspect = controller.inspect
    def altered(kind, name):
        row = inspect(kind, name)
        if name.endswith('-monitor-1'):
            if damage == 'missing': return None
            if damage == 'wrong_image': row['Image'] = NEW
            elif damage == 'wrong_source': row['Config']['Env'] = ['BUILD_SHA='+'f'*40]
            elif damage == 'unhealthy': row['State']['Health']['Status'] = 'starting'
            elif damage == 'not_running': row['State']['Running'] = False
            else: row['State']['OOMKilled'] = True
        return row
    monkeypatch.setattr(controller, 'inspect', altered)
    with pytest.raises(ValueError):
        controller.validate_compatible_certificate(SHA, OLD, NEW)


@pytest.mark.parametrize('damage', ['revision', 'clock', 'hash'])
def test_frozen_rollback_cannot_report_success_after_pause_control_changes(controller, monkeypatch, damage):
    case = certificate_case(controller, monkeypatch)
    portable_writes(controller, case, monkeypatch)
    attempt(case, controller)
    assert controller.check_rollback(SHA, OLD, NEW, REQUEST) == BRIDGE
    controller.journal_update(SHA, REQUEST, 'ROLLING_BACK', NEW)
    changed = copy.deepcopy(case.pause)
    if damage == 'revision': changed['revision'] += 1
    elif damage == 'clock': changed['updated_at'] = '2026-10-20T00:00:00+00:00'
    else: changed['control_sha256'] = 'f'*64
    monkeypatch.setattr(controller, 'paused_entry_proof', lambda: changed)
    monkeypatch.setattr(controller, 'healthy_roles', lambda *a: True)
    with pytest.raises(ValueError, match='bridge_rollback_entry_pause_changed'):
        controller.record_bridge_rollback(SHA, BRIDGE, OLD, REQUEST)
    assert not (controller.ROOT/'last-rollback.json').exists()


@pytest.fixture
def deployer_harness(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('independent_ci_deployer_harness',
        ROOT/'scripts/test_deployment_bridge10_images.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('BRIDGE10_TEST_STATE', str(tmp_path))
    (tmp_path/'test.json').write_text(json.dumps(dict(sha=SHA, case='postwriter',
        candidate=NEW, project='disposable-witness', token='invented-token')))
    return module


def test_ci_transport_does_not_fetch_a_different_source(deployer_harness, tmp_path):
    with pytest.raises(AssertionError):
        deployer_harness.mapped_transport('curl', ['https://unapproved.invalid/source', '-o', str(tmp_path/'source')])
    assert not (tmp_path/'source').exists()


def test_ci_git_transport_requires_only_main_read(deployer_harness, capsys):
    assert deployer_harness.mapped_transport('git', ['ls-remote', 'https://github.com/AviramDahan/AI-Trader.git', 'refs/heads/main']) == 0
    assert capsys.readouterr().out == SHA+'\trefs/heads/main\n'
    with pytest.raises(AssertionError):
        deployer_harness.mapped_transport('git', ['push', 'origin', 'main'])


def test_ci_unreviewed_compose_verb_is_not_forwarded(deployer_harness, monkeypatch):
    monkeypatch.setattr(deployer_harness, 'docker', lambda *a, **k: pytest.fail('unreviewed compose invoked Docker'))
    with pytest.raises(AssertionError):
        deployer_harness.mapped_transport('docker', ['compose', 'down', '-v'])


def test_postwriter_transport_failure_occurs_after_api_replacement_only(deployer_harness, tmp_path, monkeypatch):
    (tmp_path/'deploy').mkdir()
    cert = tmp_path/'deploy/compatible-rollback-v1.json'
    cert.write_text(json.dumps(dict(expires_at='2099-01-01T00:00:00+00:00', proof='original')))
    calls = []
    monkeypatch.setattr(deployer_harness, 'witness', lambda state, role, image: calls.append((role, image)))
    monkeypatch.setenv('APP_IMAGE', NEW)
    assert deployer_harness.mapped_transport('docker', ['compose', 'up', '-d', 'api']) == 42
    assert calls == [('api', NEW)] and (tmp_path/'injected-postwriter').is_file()
    assert json.loads(cert.read_bytes())['expires_at'].startswith('2000-')
    monkeypatch.setenv('APP_IMAGE', BRIDGE)
    assert deployer_harness.mapped_transport('docker', ['compose', 'up', '-d', 'api']) == 0
    assert calls[-1] == ('api', BRIDGE)


def test_ci_owned_cleanup_refuses_foreign_sleeping_container(deployer_harness, monkeypatch):
    calls = []
    def actual_boundary(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps([dict(Config=dict(Labels={deployer_harness.LABEL:'foreign'}))]).encode())
    monkeypatch.setattr(deployer_harness, 'docker', actual_boundary)
    with pytest.raises(AssertionError):
        deployer_harness.cleanup(dict(project='disposable', token='ours', volume='disposable_vol'))
    assert len(calls) == 1 and calls[0][0] == 'inspect'


@pytest.mark.parametrize('damage', [None, 'pause', 'runtime', 'marker', 'other_role_stopped', 'wrong_phase'])
def test_post_backup_writer_boundary_rechecks_real_pause_and_current_runtime(controller, monkeypatch, damage):
    case = certificate_case(controller, monkeypatch)
    portable_writes(controller, case, monkeypatch)
    attempt(case, controller)
    assert controller.check_rollback(SHA, OLD, NEW, REQUEST) == BRIDGE
    controller.journal_update(SHA, REQUEST, 'DRAIN_PENDING' if damage!='wrong_phase' else 'PREDEPLOY_VERIFIED', NEW)
    inspect = controller.inspect
    def drained(kind, name):
        row = inspect(kind, name)
        if name.endswith('-backup-1') or (damage == 'other_role_stopped' and name.endswith('-scanner-1')):
            row['State']['Running'] = False
        return row
    monkeypatch.setattr(controller, 'inspect', drained)
    if damage == 'pause':
        changed = copy.deepcopy(case.pause); changed['revision'] += 1
        monkeypatch.setattr(controller, 'paused_entry_proof', lambda: changed)
    elif damage in ('runtime', 'marker'):
        case.write(controller.ROOT/('runtime.env' if damage=='runtime' else 'last-release'), b'changed after backup')
    if damage is None:
        controller.verify_rollback_selection(SHA, OLD, NEW, REQUEST)
    else:
        with pytest.raises(ValueError):
            controller.verify_rollback_selection(SHA, OLD, NEW, REQUEST)


def test_ci_generated_controller_and_transport_compile_without_host_io(deployer_harness, tmp_path, monkeypatch):
    monkeypatch.setattr(deployer_harness.os, 'chown', lambda *a: None, raising=False)
    monkeypatch.setenv('BRIDGE10_REAL_GIT', '/not-executed-fixture-git')
    monkeypatch.setattr(deployer_harness, 'command', lambda *a, **k: SimpleNamespace(stdout=b'not-executed-fixture-archive'))
    state = tmp_path/'generated'
    deployer_harness.configure(state, dict(old=dict(runnable_ref=OLD), candidate=dict(runnable_ref=NEW)),
        dict(source_commit=SHA, source_tree='f'*40), tmp_path, 'forward',
        dict(prefix='disposable', token='invented', network='internal', database='synthetic'))
    for name in ('controller-source.py', 'controller', 'bin/docker', 'bin/git', 'bin/curl'):
        raw = (state/name).read_bytes()
        compile(raw, name, 'exec')
        assert b'/opt/ai-trader-staging' not in raw and b'/usr/local/sbin/ai-trader-deploy' not in raw
    shell = (state/'deploy.sh').read_text()
    assert 'writers_stopped=1' in shell and '--verify-rollback-selection' in shell
    assert str(state/'controller-source.py') not in shell  # CLI takes actual flock, not direct functions.


def test_ci_source_archive_matches_github_single_root_strip_contract(deployer_harness, tmp_path, monkeypatch):
    import io
    import tarfile
    monkeypatch.setattr(deployer_harness.os, 'chown', lambda *a: None, raising=False)
    monkeypatch.setenv('BRIDGE10_REAL_GIT', '/not-executed-fixture-git')
    def git_archive(args, **kwargs):
        prefix = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--prefix=')), '')
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, data in (('service/server/cloud_runtime.py', b'SCHEMA_VERSION = 7\n'),
                    ('deploy/compose.yml', b'services: {}\n')):
                member = tarfile.TarInfo(prefix+name); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return SimpleNamespace(stdout=output.getvalue())
    monkeypatch.setattr(deployer_harness, 'command', git_archive)
    state = tmp_path/'github-layout'
    deployer_harness.configure(state, dict(old=dict(runnable_ref=OLD), candidate=dict(runnable_ref=NEW)),
        dict(source_commit=SHA, source_tree='f'*40), tmp_path, 'forward', dict(prefix='disposable', token='invented'))
    with tarfile.open(state/'source.tar.gz', 'r:gz') as archive:
        stripped = {member.name.split('/', 1)[1]: archive.extractfile(member).read()
            for member in archive if member.isfile() and '/' in member.name}
    assert stripped == {'service/server/cloud_runtime.py': b'SCHEMA_VERSION = 7\n',
        'deploy/compose.yml': b'services: {}\n'}


@pytest.mark.parametrize('role', ['bridge', 'candidate'])
def test_loaded_capability_command_executes_exact_role_semantics_with_invented_identity(
        tmp_path, monkeypatch, role):
    import builtins
    from contextlib import redirect_stdout
    import importlib.util
    import io
    spec = importlib.util.spec_from_file_location('independent_actual_retention',
        ROOT/'scripts/retain_entry_intraday_images.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    output = tmp_path/'artifacts'; output.mkdir()
    image = BRIDGE if role == 'bridge' else NEW
    identity = dict(version=1, kind='classic', runnable_ref=image, platform='linux/amd64',
        platform_manifest=None, config_digest=image, build_sha=SHA, user='10001:10001')
    caps = dict(build_role=role, independent_creation=role=='candidate', snapshot_formats=list(range(1,11)),
        audit_versions=['entry_discovery_v1','entry_discovery_intraday_v1'],
        execution_versions=['independent_entry_execution_v1','independent_entry_execution_intraday_v1'])
    capability = SimpleNamespace(__file__='/invented/capabilities.py', BUILD_ROLE=role,
        creation_allowed=lambda: role=='candidate', capabilities=lambda: copy.deepcopy(caps))
    file = SimpleNamespace(stat=lambda:SimpleNamespace(st_uid=0,st_mode=0o444),
        parent=SimpleNamespace(stat=lambda:SimpleNamespace(st_uid=0)))
    modules = dict(json=json, os=SimpleNamespace(environ={'BUILD_SHA':SHA}, geteuid=lambda:10001,
        access=lambda *a:False, W_OK=2), pathlib=SimpleNamespace(Path=lambda value:file),
        entry_discovery_capabilities=capability, entry_discovery=SimpleNamespace(enabled_ids=lambda:()))
    def controlled_import(name, *args, **kwargs):
        assert name in modules, 'unreviewed capability import'
        return modules[name]
    programs = []
    def observed(command, **kwargs):
        if command[:3] == ['bash','-o','pipefail'] and 'docker save' in command[4]:
            Path(command[-1]).write_bytes(b'invented compressed image bytes')
        elif command[:3] == ['docker','image','inspect']:
            return SimpleNamespace(stdout=image+'\n')
        elif command[:2] == ['docker','run']:
            code = command[-1]; programs.append(code)
            assert 'c.BUILD_ROLE' in code and 'ROLE_VALUE' not in code
            with redirect_stdout(io.StringIO()) as captured:
                exec(compile(code, '<actual retained capability program>', 'exec'),
                    {'__builtins__':dict(vars(builtins), __import__=controlled_import)})
            return SimpleNamespace(stdout=captured.getvalue())
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(module, 'run', observed)
    result = module.retain_role(role, dict(image_id=image, config_digest=image, identity=identity,
        build_sha=SHA), output, SimpleNamespace(resolve_image=lambda *a, **k:copy.deepcopy(identity)))
    assert len(programs) == 1 and result['loaded_capability_verified'] is True
    loaded = json.loads((output/('loaded-'+role+'-capability.json')).read_bytes())
    assert loaded['build_sha'] == SHA and loaded['capabilities'] == caps
