"""Disposable Linux CI deployer proof, NOT a Production release tool.

Real three image identities, controller certificate/OCI/pause checks, shell,
kernel flock, PostgreSQL retained state and marker writes execute. The five
roles are explicitly NONTRADING sleeping witnesses, not runtime workers.
Only source/HTTP/Compose transport and managed-backup completion are mapped.
The separate ordered16 job proves actual trading and encrypted restore.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tarfile

REPO = Path(__file__).resolve().parents[1]
ROLES = ('api', 'scanner', 'monitor', 'telegram', 'backup')
LABEL = 'ai-trader.bridge10-deployer-proof'
OLD_SHA = '74d09b2dba654bf29136a9b13020f36903c5dd3d'


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def command(args, *, check=True, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=kwargs.pop('timeout', 60), **kwargs)
    if check and result.returncode:
        raise RuntimeError('disposable_deployment_command_failed: '+str(args[:3]))
    return result


def write(path, raw, mode=0o600):
    path.write_bytes(raw)
    path.chmod(mode)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(state, event, **fields):
    with (state/'transport.jsonl').open('ab') as stream:
        stream.write(wire(dict(event=event, **fields))+b'\n')


def docker(args, **kwargs):
    return command([os.environ['BRIDGE10_REAL_DOCKER'], *args], **kwargs)


def git(args, **kwargs):
    # sudo/root does not inherit the checkout owner's global safe.directory.
    # Authorize this exact checkout per call; never mutate global Git config.
    return command([os.environ['BRIDGE10_REAL_GIT'], '-c', 'safe.directory='+str(REPO),
        '-C', str(REPO), *args], **kwargs)


def witness(state, role, image):
    config = json.loads((state/'test.json').read_bytes())
    name = config['project']+'-'+role+'-1'
    existing = docker(['container', 'inspect', name], check=False)
    if existing.returncode == 0:
        row = json.loads(existing.stdout)[0]
        assert row['Config']['Labels'].get(LABEL) == config['token']
        docker(['rm', '-f', name])  # Exact owned sleeping witness only.
    args = ['run', '--pull=never', '-d', '--name', name, '--network', config['network'],
        '--label', LABEL+'='+config['token'], '--label', 'com.docker.compose.project='+config['project'],
        '--label', 'com.docker.compose.service='+role, '--restart=no', '--read-only',
        '--cpus', '0.25', '--memory', '192m', '--memory-swap', '192m', '--pids-limit', '64',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--env-file', str(state/'deploy/runtime.env'), '-e', 'DATABASE_URL='+config['database'],
        '-v', str(state/'role-runtime')+':/app/.runtime',
        '-v', config['volume']+':/backup', '--tmpfs', '/tmp:size=32m,mode=1777',
        '--health-cmd', 'python -c "pass"', '--health-interval', '1s',
        '--health-timeout', '3s', '--health-retries', '10',
        '--entrypoint', 'python', image, '-c', 'import time; time.sleep(3600)']
    docker(args)
    for _ in range(100):
        row = json.loads(docker(['container', 'inspect', name]).stdout)[0]
        if row['State'].get('Health', {}).get('Status') == 'healthy':
            return row
        __import__('time').sleep(.1)
    raise AssertionError('sleeping_witness_health_timeout')


def mapped_transport(kind, args):
    """No providers/network. Docker except Compose is the real Linux binary."""
    state = Path(os.environ['BRIDGE10_TEST_STATE'])
    config = json.loads((state/'test.json').read_bytes())
    if kind == 'git':
        assert args[:1] == ['ls-remote'] and args[-1] == 'refs/heads/main'
        print(config['sha']+'\trefs/heads/main')
        return 0
    if kind == 'curl':
        if '-o' in args:
            assert 'https://github.com/AviramDahan/AI-Trader/archive/'+config['sha']+'.tar.gz' in args
            shutil.copyfile(state/'source.tar.gz', args[args.index('-o')+1])
            record(state, 'EXACT_LOCAL_GIT_ARCHIVE_TRANSPORT')
        else:
            assert args[-1].endswith('/health')
            record(state, 'PUBLIC_HEALTH_TRANSPORT_NOT_A_SERVER_HTTP_PROOF')
        return 0
    assert kind == 'docker'
    if not args or args[0] != 'compose':
        result = docker(args, check=False, timeout=240)
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        return result.returncode
    # Read original shell verbs, but replace cloud Compose with owned witnesses.
    verbs = [i for i, arg in enumerate(args) if arg in ('up', 'stop', 'run')]
    assert len(verbs) == 1, 'unreviewed_compose_transport'
    index = verbs[0]
    verb, tail = args[index], args[index+1:]
    if verb == 'run':
        assert tail[-1] == 'migrate'
        record(state, 'MIGRATION_TRANSPORT_NOOP_SAME_SCHEMA_SYNTHETIC_DB')
        return 0
    roles = [arg for arg in tail if arg in ROLES]
    assert roles and len(set(roles)) == len(roles)
    if verb == 'stop':
        for role in roles:
            docker(['stop', '--time', '5', config['project']+'-'+role+'-1'])
        record(state, 'COMPOSE_STOP_WITNESSES', roles=roles)
        return 0
    image = os.environ['APP_IMAGE']
    for role in roles:
        witness(state, role, image)
        record(state, 'COMPOSE_REPLACED_WITNESS', role=role, image=image)
        if (config['case'] == 'postwriter' and role == 'api' and image == config['candidate']
                and not (state/'injected-postwriter').exists()):
            write(state/'injected-postwriter', b'first API was really replaced')
            # Simulate a long forward attempt: live cert both expires and changes.
            path = state/'deploy/compatible-rollback-v1.json'
            value = json.loads(path.read_bytes())
            value['expires_at'] = '2000-01-01T00:00:00+00:00'
            value['proof'] = 'REPLACED_AFTER_DURABLE_SELECTION_MUST_NOT_BE_REUSED'
            write(path, wire(value))
            return 42
    return 0


def controller_transport(args):
    state = Path(os.environ['BRIDGE10_TEST_STATE'])
    config = json.loads((state/'test.json').read_bytes())
    module = load(state/'controller-source.py', 'actual_disposable_controller')
    # Source lookup transport is exact local committed Git, not GitHub/network.
    def tree(sha):
        assert sha == config['sha']
        return config['tree']
    module.repository_tree = tree
    def exact_check_transport(request, timeout):
        assert request.full_url == ('https://api.github.com/repos/AviramDahan/AI-Trader/actions/runs?head_sha='+
            config['sha']+'&branch=main&event=push&per_page=100')
        record(state, 'GITHUB_CHECK_TRANSPORT_SYNTHETIC_NOT_RELEASE_APPROVAL')
        rows = [dict(head_sha=config['sha'], head_branch='main', event='push',
            head_repository=dict(full_name='AviramDahan/AI-Trader'), name=name, conclusion='success')
            for name in ('CI', 'Cloud readiness (no deployment)')]
        return io.BytesIO(wire(dict(workflow_runs=rows)))
    module.urllib.request.urlopen = exact_check_transport
    if '--backup-only' in args:
        assert args[args.index('--sha')+1] == config['sha']
        assert args[args.index('--image')+1] == config['candidate']
        record(state, 'MANAGED_BACKUP_COMPLETION_TRANSPORT_SYNTHETIC_NOT_ENCRYPTED_PROOF')
        print(json.dumps(dict(status='VERIFIED_COMPLETE', boundary='SYNTHETIC_COMPLETION_TRANSPORT')))
        return 0
    module.main(args)  # Real global flock, validators, files, Docker, DB checks.
    if '--journal-begin' in args:
        env = dict(os.environ)
        env.pop('AI_TRADER_DEPLOY_LOCK_FD', None)
        contender = command([sys.executable, str(state/'controller'), '--resolve-running',
            '--role', 'api', '--print-ref'], env=env, check=False)
        assert contender.returncode == 75, 'actual_parent_flock_not_exclusive'
        record(state, 'REAL_KERNEL_FLOCK_CONTENDER_REJECTED')
    if ('--stop-backup-idle' in args and config['case'] == 'prewriter'
            and not (state/'injected-prewriter').exists()):
        write(state/'injected-prewriter', b'actual old backup stopped while idle')
        record(state, 'INJECTED_AFTER_REAL_PREWRITER_BACKUP_DRAIN')
        return 43
    return 0


def configure(state, images, source, artifacts, case, common):
    sha, tree = source['source_commit'], source['source_tree']
    project = common['prefix']+'-'+case
    config = dict(common, case=case, sha=sha, tree=tree, project=project,
        volume=project+'_recovery_backup', candidate=images['candidate']['runnable_ref'])
    state.mkdir(mode=0o700)
    write(state/'test.json', wire(config))
    (state/'deploy').mkdir(mode=0o700)
    (state/'bin').mkdir(mode=0o700)
    role_runtime = state/'role-runtime'
    role_runtime.mkdir(mode=0o700)
    os.chown(role_runtime, 10001, 10001)
    write(role_runtime/'deployed-release', OLD_SHA.encode(), 0o644)
    root = state/'deploy'
    # Exact transport-name/path substitutions only. No certificate/trading gates
    # or lifecycle algorithms are patched, stubbed or bypassed.
    original = (REPO/'deploy/hetzner-pull.py').read_text()
    mapped = original.replace('/opt/ai-trader-staging/deploy', root.as_posix()).replace(
        '/run/lock/ai-trader-deploy.lock', (state/'deploy.lock').as_posix()).replace(
        '/usr/local/sbin/ai-trader-deploy', (state/'deploy.sh').as_posix()).replace(
        "WORK_PARENT = Path('/opt')", 'WORK_PARENT = Path('+repr(str(state))+')').replace(
        'ai-trader-cloud', project)
    assert mapped != original and '/opt/ai-trader-staging' not in mapped
    write(state/'controller-source.py', mapped.encode(), 0o700)
    write(state/'docker_image_identity.py', (REPO/'deploy/docker_image_identity.py').read_bytes(), 0o755)
    wrapper = ('#!'+sys.executable+'\nimport runpy,sys\nn=runpy.run_path('+repr(str(Path(__file__).resolve()))+
        ')\nsys.exit(n["controller_transport"](sys.argv[1:]))\n')
    # The main program catches Busy itself; all failures retain a nonzero code.
    write(state/'controller', wrapper.encode(), 0o700)
    shell = (REPO/'deploy/hetzner-deploy.sh').read_text().replace(
        '/opt/ai-trader-staging', state.as_posix()).replace('/usr/local/sbin/ai-trader-pull', (state/'controller').as_posix()).replace(
        '/run/lock/ai-trader-deploy.lock', (state/'deploy.lock').as_posix()).replace('ai-trader-cloud', project)
    assert '/opt/ai-trader-staging' not in shell and '/usr/local/sbin/ai-trader-pull' not in shell
    write(state/'deploy.sh', shell.encode(), 0o700)
    for kind in ('docker', 'git', 'curl'):
        raw = ('#!'+sys.executable+'\nimport runpy,sys\nn=runpy.run_path('+repr(str(Path(__file__).resolve()))+
            ')\nsys.exit(n["mapped_transport"]('+repr(kind)+',sys.argv[1:]))\n')
        write(state/'bin'/kind, raw.encode(), 0o700)
    write(state/'deploy.lock', b'')
    write(root/'compose.yml', (REPO/'deploy/compose.yml').read_bytes())
    write(root/'runtime.env', b'AI_TRADER_CLOUD=true\nSTOCK_SCANNER_ENABLED=false\n'
        b'STOCK_SCANNER_VCP_DISCOVERY_ENABLED=true\nSTOCK_SCANNER_MOMENTUM_BURST_ENABLED=true\n'
        b'STOCK_SCANNER_PULLBACK_RECLAIM_ENABLED=true\nSTOCK_SCANNER_RS_LEADER_ENABLED=true\n'
        b'STOCK_SCANNER_PEAD_ENABLED=false\nSTOCK_SCANNER_INDEPENDENT_INTRADAY_ENABLED=false\n'
        b'STOCK_SCANNER_INTRADAY_RVOL_CONTEXT_ENABLED=false\nSTOCK_SCANNER_TELEGRAM_ENABLED=false\n')
    write(root/'last-release', (OLD_SHA+'\n'+images['old']['runnable_ref']+'\n').encode())
    # Match GitHub archive layout: the unchanged real shell strips ONE root.
    archive = git(['archive', '--format=tar.gz', '--prefix=AI-Trader-'+sha+'/', sha], timeout=60).stdout
    write(state/'source.tar.gz', archive)
    return config


def committed_fixtures(sha):
    """Raw committed fixtures used by the preceding actual ordered16 step."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as target:
        for prefix, revision in (('old', OLD_SHA), ('candidate', sha)):
            paths = ['service/server/tests', 'service/server/tests_pg']
            if prefix == 'candidate': paths += ['scripts/entry_intraday_compatibility_probe.py']
            listing = git(['ls-tree', '-r', '-z', revision, '--', *paths]).stdout
            expected = {}
            for item in listing.split(b'\0'):
                if not item: continue
                head, name = item.split(b'\t', 1)
                mode, kind, blob = head.split(b' ')
                assert mode in (b'100644', b'100755') and kind == b'blob'
                expected[name.decode()] = blob.decode()
            raw = git(['-c', 'core.autocrlf=false', 'archive', '--format=tar', revision, *paths]).stdout
            assert len(raw) < 64*1024*1024
            seen = set()
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as source:
                for member in source:
                    if member.isdir(): continue
                    assert member.isfile() and member.size <= 8*1024*1024 and member.name in expected and member.name not in seen
                    seen.add(member.name)
                    data = source.extractfile(member).read()
                    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest() == expected[member.name]
                    entry = tarfile.TarInfo(prefix+'/'+member.name)
                    entry.size, entry.mode, entry.mtime = len(data), 0o444, 0
                    target.addfile(entry, io.BytesIO(data))
            assert seen == set(expected)
    assert len(output.getvalue()) < 64*1024*1024
    return gzip.compress(output.getvalue(), mtime=0)


def certificate(state, images, source, artifacts, controller):
    root = state/'deploy'
    sha = source['source_commit']
    folder = root/'entry-intraday-rollback-v1'/sha
    folder.mkdir(mode=0o700, parents=True)
    folder.parent.chmod(0o700)
    names = ('source-proof.json', 'ordered-proof.json', 'results.jsonl',
        'rollback-artifact.json', 'candidate-artifact.json', 'images.json')
    files = {}
    for name in names:
        raw = (artifacts/name).read_bytes()
        write(folder/name, raw)
        files[name] = digest(raw)
    archives = {}
    for role, name in (('bridge', 'rollback-artifact.json'), ('candidate', 'candidate-artifact.json')):
        info = json.loads((artifacts/name).read_bytes())
        raw_path = artifacts/info['retained_filename']
        shutil.copyfile(raw_path, folder/raw_path.name)
        (folder/raw_path.name).chmod(0o600)
        archives[role] = dict(filename=raw_path.name, bytes=info['archive_bytes'],
            sha256=info['archive_sha256'], config_digest=info['config_digest'])
    # The real ordered16 has just executed these exact committed fixture blobs.
    fixtures = (state.parent/'committed-fixtures.tar.gz').read_bytes()
    write(folder/'fixtures.tar.gz', fixtures)
    pause = controller.paused_entry_proof()
    phases = [json.loads(line) for line in (artifacts/'results.jsonl').read_bytes().splitlines()]
    phases = [{key: row[key] for key in ('phase', 'status', 'build_sha', 'probe_sha256')} for row in phases]
    now = datetime.now(timezone.utc)
    value = dict(version=1, candidate_sha=sha, artifact_build_sha=sha, source_tree=source['source_tree'],
        verified_at=now.isoformat(), expires_at=(now+timedelta(hours=6)).isoformat(),
        actual_old_identity=images['old'], runtime_sha256=digest((root/'runtime.env').read_bytes()),
        marker_sha256=digest((root/'last-release').read_bytes()),
        identity_module_sha256=digest(controller._identity_raw), bridge_identity=images['bridge'],
        candidate_identity=images['candidate'], bridge_archive=archives['bridge'],
        candidate_archive=archives['candidate'], probe_sha256=source['file_sha256']['scripts/entry_intraday_compatibility_probe.py'],
        fixtures_sha256=digest(fixtures), proof='TARGET_ISOLATED16_FORMAT10_PHASES_PASS',
        capabilities=controller.binary_capabilities(images['bridge']['runnable_ref'], immutable=True)['capabilities'],
        entry_pause=pause, proof_files=files)
    target = {key: value[key] for key in ('version', 'candidate_sha', 'source_tree', 'actual_old_identity',
        'bridge_identity', 'candidate_identity', 'runtime_sha256', 'marker_sha256',
        'identity_module_sha256', 'probe_sha256', 'fixtures_sha256', 'entry_pause')}
    target['phases'] = phases
    write(folder/'target-proof.json', wire(target))
    value['target_proof_sha256'] = digest(wire(target))
    write(root/'compatible-rollback-v1.json', wire(value))
    return value


def fingerprint(pg):
    raw = docker(['exec', pg, 'pg_dump', '-U', 'isolated', '--data-only', '--no-owner',
        '--no-privileges', 'isolated_entry']).stdout
    # PostgreSQL random dump restore-guard tokens are not database state.
    raw = b'\n'.join(line for line in raw.splitlines()
        if not line.startswith((b'\\restrict ', b'\\unrestrict ')))
    return digest(raw)


def execute_case(state, case, images, source, artifacts, common):
    config = configure(state, images, source, artifacts, case, common)
    os.environ['BRIDGE10_TEST_STATE'] = str(state)
    os.environ['PATH'] = str(state/'bin')+os.pathsep+os.environ['BRIDGE10_ORIGINAL_PATH']
    docker(['volume', 'create', '--label', LABEL+'='+config['token'], config['volume']])
    mount = json.loads(docker(['volume', 'inspect', config['volume']]).stdout)[0]['Mountpoint']
    write(Path(mount)/'backup.lock', b'')
    for role in ROLES:
        witness(state, role, images['old']['runnable_ref'])
    controller = load(state/'controller-source.py', 'real_disposable_case_controller')
    controller.repository_tree = lambda sha: source['source_tree'] if sha == source['source_commit'] else None
    cert = certificate(state, images, source, artifacts, controller)
    controller.validate_compatible_certificate(source['source_commit'], images['old']['runnable_ref'], images['candidate']['runnable_ref'])
    before = fingerprint(common['pg'])
    old_ids = {r: json.loads(docker(['inspect', config['project']+'-'+r+'-1']).stdout)[0]['Id'] for r in ROLES}
    env = dict(os.environ)
    env.pop('AI_TRADER_DEPLOY_LOCK_FD', None)
    result = command([str(state/'controller')],
        env=env, timeout=720, check=False)
    write(state/'private-shell-stdout', result.stdout)
    write(state/'private-shell-stderr', result.stderr)
    journal = json.loads((state/'deploy/deployment-attempt.json').read_bytes())
    assert fingerprint(common['pg']) == before, 'synthetic_DB_rewound_or_changed'
    assert controller.paused_entry_proof() == cert['entry_pause'], 'pause_resumed_or_changed'
    transport = [json.loads(line) for line in (state/'transport.jsonl').read_bytes().splitlines()]
    assert any(r['event'] == 'REAL_KERNEL_FLOCK_CONTENDER_REJECTED' for r in transport)
    if case == 'forward':
        assert result.returncode == 0 and journal['phase'] == 'COMPLETE'
        assert controller.completed(source['source_commit'])
        expected = images['candidate']
        release = (state/'deploy/last-release').read_text().splitlines()
        assert release == [source['source_commit'], expected['runnable_ref'],
            images['bridge']['runnable_ref'], images['old']['runnable_ref']]
    elif case == 'prewriter':
        assert result.returncode != 0 and journal['phase'] == 'ROLLED_BACK'
        expected = images['old']
        for role in ROLES:
            row = json.loads(docker(['inspect', config['project']+'-'+role+'-1']).stdout)[0]
            assert row['Id'] == old_ids[role], 'prewriter_failure_replaced_old_role'
        assert not any(r['event'] == 'COMPOSE_REPLACED_WITNESS' for r in transport)
    else:
        assert result.returncode != 0 and journal['phase'] == 'ROLLED_BACK'
        expected = images['bridge']
        assert journal['rollback_identity'] == expected and journal['observed_old_identity'] == images['old']
        rollback = json.loads((state/'deploy/last-rollback.json').read_bytes())
        assert rollback['state'] == 'SUPPORTED_BRIDGE_NOT_COMPLETED_CANDIDATE'
        assert not controller.completed(source['source_commit'])
        assert (state/'deploy/failed-release').read_text().splitlines()[0] == source['source_commit']
        failure = json.loads((state/'deploy/failed-releases'/(source['source_commit']+'.json')).read_bytes())
        assert failure['sha'] == source['source_commit'] and failure['exit_code'] != 0
        # The actual poll must honor the failure latch despite same BUILD_SHA.
        with __import__('contextlib').redirect_stdout(__import__('io').StringIO()) as captured:
            controller.poll(9)
        assert json.loads(captured.getvalue())['status'] == 'BLOCKED_FAILED_RELEASE'
        assert (state/'deploy/failed-release').exists()
    for role in ROLES:
        controller.verify_role(role, expected['runnable_ref'], expected['build_sha'])
    return dict(case=case, status='PASS', shell_exit=result.returncode, journal_phase=journal['phase'],
        actual_old_identity=images['old'], final_identity=expected, candidate_identity=images['candidate'],
        bridge_identity=images['bridge'], pause_unchanged=True, database_fingerprint_unchanged=True,
        real_kernel_flock=True, candidate_completed=case == 'forward',
        failure_latch_preserved=case == 'postwriter', nontrading_sleeping_role_witnesses=5,
        source_transport_sha256=digest((state/'controller-source.py').read_bytes()),
        shell_transport_sha256=digest((state/'deploy.sh').read_bytes()))


def cleanup(config):
    for role in ROLES:
        name = config['project']+'-'+role+'-1'
        result = docker(['inspect', name], check=False)
        if result.returncode:
            continue
        assert json.loads(result.stdout)[0]['Config']['Labels'].get(LABEL) == config['token']
        docker(['rm', '-f', name])
    info = docker(['volume', 'inspect', config['volume']], check=False)
    if info.returncode == 0:
        assert json.loads(info.stdout)[0]['Labels'].get(LABEL) == config['token']
        docker(['volume', 'rm', config['volume']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve(strict=True)
    assert sys.platform == 'linux' and os.geteuid() == 0
    assert artifacts == Path('/tmp/intraday-artifacts') and os.environ.get('GITHUB_ACTIONS') == 'true'
    assert os.environ.get('GITHUB_REPOSITORY') == 'AviramDahan/AI-Trader'
    os.environ['BRIDGE10_REAL_DOCKER'] = shutil.which('docker') or ''
    os.environ['BRIDGE10_REAL_GIT'] = shutil.which('git') or ''
    os.environ['BRIDGE10_ORIGINAL_PATH'] = os.environ['PATH']
    assert os.environ['BRIDGE10_REAL_DOCKER']
    sha = git(['rev-parse', 'HEAD']).stdout.decode().strip()
    source = json.loads((artifacts/'source-proof.json').read_bytes())
    assert source['source_commit'] == sha and source['source_tree'] == git(['rev-parse', 'HEAD^{tree}']).stdout.decode().strip()
    identity = load(REPO/'deploy/docker_image_identity.py', 'real_ci_deployment_identity')
    image_rows = json.loads((artifacts/'images.json').read_bytes())
    images = {r['role']: {k: v for k, v in identity.resolve_image(r['image_id'], expected_build=r['build_sha']).items()
        if k in identity.FIELDS} for r in image_rows}
    assert set(images) == {'old', 'bridge', 'candidate'} and len({r['runnable_ref'] for r in images.values()}) == 3
    assert images['old']['build_sha'] == OLD_SHA and images['bridge']['build_sha'] == images['candidate']['build_sha'] == sha
    token = os.urandom(8).hex()
    prefix = 'bridge10-deployer-'+token
    directory = Path(tempfile.mkdtemp(prefix=prefix+'-', dir='/tmp'))
    write(directory/'committed-fixtures.tar.gz', committed_fixtures(sha))
    network, pg = prefix+'-net', prefix+'-pg'
    assert docker(['network', 'inspect', network], check=False).returncode != 0
    assert docker(['container', 'inspect', pg], check=False).returncode != 0
    docker(['network', 'create', '--internal', '--label', LABEL+'='+token, network])
    proof = directory/'proof'
    proof.mkdir(mode=0o700)
    mounted = False
    common = dict(prefix=prefix, network=network, pg=pg, token=token,
        database='postgresql://isolated:disposable@entry-discovery-pg:5432/isolated_entry')
    results = []
    jobs = (prefix+'-seed', prefix+'-pause')
    try:
        docker(['run', '--pull=never', '-d', '--name', pg, '--label', LABEL+'='+token,
            '--network', network, '--network-alias', 'entry-discovery-pg',
            '--cpus', '1', '--memory', '512m', '--memory-swap', '512m',
            '--tmpfs', '/var/lib/postgresql/data:size=256m,mode=0700',
            '-e', 'POSTGRES_USER=isolated', '-e', 'POSTGRES_PASSWORD=disposable',
            '-e', 'POSTGRES_DB=isolated_entry', 'postgres:17-bookworm'])
        for _ in range(30):
            if docker(['exec', pg, 'pg_isready', '-U', 'isolated'], check=False).returncode == 0:
                break
            __import__('time').sleep(1)
        else: raise AssertionError('disposable_postgres_not_ready')
        command(['mount', '-t', 'tmpfs', '-o', 'size=64m,mode=0700,uid=10001,gid=10001', 'tmpfs', str(proof)])
        mounted = True
        seed = docker(['run', '--pull=never', '--rm', '--name', jobs[0], '--label', LABEL+'='+token,
            '--network', network, '--read-only', '--cpus', '1', '--memory', '512m', '--memory-swap', '512m',
            '--pids-limit', '128', '--tmpfs', '/tmp:size=64m,mode=1777',
            '-e', 'DATABASE_URL='+common['database'], '-e', 'STOCK_SCANNER_EXIT_STRATEGY=single',
            '-e', 'STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED=true', '-e', 'STOCK_SCANNER_MAX_TOTAL_EXPOSURE=10000',
            '-e', 'STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED=true', '-e', 'STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED=true',
            '-e', 'STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED=true',
            '-v', '/tmp/intraday-old/service/server/tests:/fixtures/tests:ro',
            '-v', '/tmp/intraday-old/service/server/tests_pg:/fixtures/tests_pg:ro',
            '-v', str(REPO/'scripts/entry_intraday_compatibility_probe.py')+':/probe.py:ro',
            '-v', str(proof)+':/proof', '--entrypoint', 'python', images['old']['runnable_ref'], '/probe.py', 'old_seed'], timeout=180)
        seed_rows = [json.loads(line) for line in seed.stdout.splitlines()]
        assert len(seed_rows) == 1 and seed_rows[0]['phase'] == 'old_seed' and seed_rows[0]['status'] == 'PASS'
        assert seed_rows[0]['build_sha'] == OLD_SHA
        assert seed_rows[0]['probe_sha256'] == source['file_sha256']['scripts/entry_intraday_compatibility_probe.py']
        count = docker(['exec', pg, 'psql', '-U', 'isolated', '-d', 'isolated_entry', '-At', '-c',
            "SELECT (SELECT count(*) FROM scanner_trades WHERE ticker='V1_ACTIVE'), "
            "(SELECT count(*) FROM scanner_orders WHERE status='recovery_uncertain')"]).stdout.decode().strip()
        assert count == '2|1', 'nonempty_retained_open_and_uncertain_fixture_required'
        code = 'import entry_emergency; entry_emergency.set_paused(True,expected_revision=0); print("synthetic_pause_created")'
        docker(['run', '--pull=never', '--rm', '--name', jobs[1], '--label', LABEL+'='+token,
            '--network', network, '--read-only', '--cpus', '.25', '--memory', '192m', '--memory-swap', '192m',
            '--pids-limit', '64', '--tmpfs', '/tmp:size=32m,mode=1777', '-e', 'DATABASE_URL='+common['database'],
            '--entrypoint', 'python', images['old']['runnable_ref'], '-c', code])
        for case in ('forward', 'prewriter', 'postwriter'):
            state = directory/case
            try:
                results.append(execute_case(state, case, images, source, artifacts, common))
            finally:
                if (state/'test.json').is_file():
                    cleanup(json.loads((state/'test.json').read_bytes()))
        output = dict(status='PASS', source_commit=sha, source_tree=source['source_tree'],
            script_sha256=digest(Path(__file__).read_bytes()), cases=results,
            actual_images=images, production_execution=False,
            boundaries=['NONTRADING_SLEEP_WITNESSES_NOT_CLOUD_WORKERS',
                'SOURCE_HTTP_COMPOSE_TRANSPORT_MAPPED', 'GITHUB_CHECK_TRANSPORT_SYNTHETIC_NOT_RELEASE_APPROVAL',
                'MANAGED_BACKUP_COMPLETION_TRANSPORT_SYNTHETIC',
                'ACTUAL_ENCRYPTED_RESTORE_AND_TRADING_PROOF_IS_SEPARATE_ORDERED16',
                'CI_ONLY_NOT_HOST_PIN_OR_PROFITABILITY_PROOF'])
        write(artifacts/'deployment-proof.json', wire(output), 0o644)
        print(json.dumps(dict(status='PASS', cases=3, source_commit=sha, production_execution=False)))
    finally:
        os.environ['PATH'] = os.environ['BRIDGE10_ORIGINAL_PATH']
        for name in jobs:
            row = docker(['inspect', name], check=False)
            if row.returncode == 0:
                assert json.loads(row.stdout)[0]['Config']['Labels'].get(LABEL) == token
                docker(['rm', '-f', name])
        row = docker(['inspect', pg], check=False)
        if row.returncode == 0:
            assert json.loads(row.stdout)[0]['Config']['Labels'].get(LABEL) == token
            docker(['rm', '-f', pg])
        info = json.loads(docker(['network', 'inspect', network]).stdout)[0]
        assert info['Internal'] is True and info['Labels'].get(LABEL) == token and not info['Containers']
        docker(['network', 'rm', network])
        if mounted:
            assert command(['findmnt', '-n', '-o', 'FSTYPE', '--target', str(proof)]).stdout.strip() == b'tmpfs'
            command(['umount', str(proof)])


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--transport':
        raise SystemExit(mapped_transport(sys.argv[2], sys.argv[3:]))
    main()
