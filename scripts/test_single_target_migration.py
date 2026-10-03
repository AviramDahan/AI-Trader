"""Execute the release Bash script, never a deployment.

Only its three absolute filesystem roots are relocated into a disposable folder.
Docker/Git/HTTP/flock are strict command doubles; embedded Python preflights run
unmodified against a read-only database double. PostgreSQL tests separately
verify the same preflight against the real catalog, and the image workflow
exercises the complete applications/real numbered DDL/age restore. This harness
proves shell ordering, failures and retries, not live Docker Compose readiness.
"""
import contextlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest

REPO = Path(__file__).resolve().parents[1]
OLD = 'sha256:' + '1' * 64
NEW = 'sha256:' + '2' * 64
TARGET = 'a' * 40
BRIDGE = 'b' * 40


def initial():
    columns = [dict(table_name=t, column_name=c, is_nullable='YES', data_type='double precision', column_default=None)
               for t, names in [('scanner_signals', ('tp2', 'tp3', 'rr2', 'rr3')), ('scanner_trades', ('tp2', 'tp3'))] for c in names]
    columns.append(dict(table_name='scanner_orders', column_name='plan_json', is_nullable='NO',
                        data_type='text', column_default="'{}'::text"))
    return dict(schema=5, versions=list(range(1, 6)), columns=columns, active=OLD, compatible=True,
                image_available=True, creation=False, checks=True, main=TARGET, locked=False,
                ddl=0, backups=0, stops=0, fail_start=False, fail_backup=False, commands=[])


def embedded(code, args, state, image):
    class Result:
        def __init__(self, rows): self.rows = rows
        def fetchone(self): return self.rows[0]
        def fetchall(self): return self.rows
        def __iter__(self): return iter(self.rows)
    class DB:
        readonly = False
        def execute(self, query, *params):
            q = query.lower()
            if q.startswith('set transaction'):
                assert 'read only' in q
                self.readonly = True
                return Result([])
            assert self.readonly and q.startswith('select'), 'preflight must be read-only'
            if 'max(version)' in q: return Result([dict(version=state['schema'])])
            if 'schema_migrations' in q:
                return Result([dict(version=v, applied_at='2026-01-01T00:00:00Z') for v in state['versions']])
            if 'information_schema.columns' in q: return Result(state['columns'])
            raise AssertionError('unexpected SQL: ' + query)
    @contextlib.contextmanager
    def connection(): yield DB()
    database = types.ModuleType('database'); database.get_db_connection = connection
    cloud = types.ModuleType('cloud_runtime')
    cloud.SCHEMA_VERSION = 5 if image == OLD else 6
    cloud.SUPPORTED_SCHEMAS = (5, 6) if state['compatible'] else (5,)
    cloud.SINGLE_TARGET_ROLLBACK_CAPABILITY = 'v2-format3-holds-legacy-v1' if state['compatible'] else 'old'
    cloud.assert_schema = lambda: None  # real application readiness covered by image workflow
    gate = types.ModuleType('single_target_activation'); gate.CREATION_CAPABLE = image != OLD
    gate.enabled = lambda: gate.CREATION_CAPABLE and state['creation']
    sys.modules.update(database=database, cloud_runtime=cloud, single_target_activation=gate)
    sys.path.insert(0, str(REPO / 'service/server'))
    os.environ['BUILD_SHA'] = BRIDGE if image == OLD else TARGET
    os.environ['STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED'] = str(state['creation']).lower()
    sys.argv = ['-c', *args]
    if 'deployed-release' in code:
        state['marker'] = args[0]
    else:
        exec(code, {})


def command(name, args, state):
    state['commands'].append([name, *args])
    if name == 'flock': return 75 if state['locked'] else 0
    if name == 'git':
        assert args[0] == 'ls-remote'; print(state['main'] + '\trefs/heads/main'); return 0
    if name == 'curl':
        url = next(a for a in args if a.startswith('https://'))
        if '/actions/runs?' in url:
            print(json.dumps(dict(workflow_runs=[dict(name=n, head_sha=TARGET, head_branch='main', event='push',
                head_repository=dict(full_name='AviramDahan/AI-Trader'), conclusion='success' if state['checks'] else 'failure')
                for n in ('CI', 'Cloud readiness (no deployment)')])))
        elif '/archive/' in url:
            shutil.copyfile(os.environ['HARNESS_ARCHIVE'], args[args.index('-o') + 1])
        else: assert url.endswith('/health')
        return 0
    assert name == 'docker', name
    if args[0] == 'inspect': print(state['active']); return 0
    if args[:2] == ['image', 'inspect']:
        if not state['image_available']: return 1
        if '--format' in args: print(NEW)
        return 0
    if args[0] in ('build', 'tag'): return 0
    if args[0] == 'exec':
        ix = args.index('-c'); embedded(args[ix + 1], args[ix + 2:], state, state['active']); return 0
    assert args[:2] == ['compose', '-f'], args
    args = args[5:]
    image = os.environ.get('APP_IMAGE', state['active'])
    if args[0] == 'run':
        if '-c' in args:
            ix = args.index('-c'); embedded(args[ix + 1], args[ix + 2:], state, image)
        elif args[-1] == 'migrate':
            state['ddl'] += 1; state['schema'] = 6; state['versions'] = list(range(1, 7))
        else:
            assert args[-3:] == ['backup', '--once', '--predeploy'], args
            if state['fail_backup']: return 1
            state['backups'] += 1
    elif args[0] == 'stop': state['stops'] += 1
    elif args[0] == 'up':
        if image == NEW and state['fail_start']:
            state['fail_start'] = False; return 7
        state['active'] = image
    else: raise AssertionError(args)
    return 0


def dispatch():
    sys.stdout.reconfigure(newline='\n')
    path = Path(os.environ['HARNESS_STATE']); state = json.loads(path.read_text())
    try: return command(sys.argv[2], sys.argv[3:], state)
    finally: path.write_text(json.dumps(state))


class ReleaseScriptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.bin = self.root / 'bin'; self.bin.mkdir()
        self.state_path = self.root / 'state.json'; self.state = initial(); self.save()
        self.bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        self.assertTrue(self.bash, 'Bash is required, not skipped')
        for name in ('docker', 'curl', 'git', 'flock', 'python3'):
            call = [sys.executable] if name == 'python3' else [sys.executable, str(Path(__file__).resolve()), '--command', name]
            path = self.bin / name; path.write_text('#!/usr/bin/env bash\nexec ' + shlex.join([x.replace('\\', '/') for x in call]) + ' "$@"\n', newline='\n'); path.chmod(0o755)
        source = self.root / 'candidate'; (source / 'service/server').mkdir(parents=True); (source / 'deploy').mkdir()
        (source / 'service/server/cloud_runtime.py').write_text('SCHEMA_VERSION = 6\n')
        (source / 'deploy/compose.yml').write_text('synthetic: true\n')
        self.archive = self.root / 'candidate.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive: archive.add(source, arcname='candidate')
        self.work = self.root / 'server'; (self.work / 'deploy').mkdir(parents=True)
        (self.work / 'deploy/compose.yml').write_text('synthetic: true\n')

    def save(self): self.state_path.write_text(json.dumps(self.state))
    def run_script(self, mode='--approved-schema-5-to-6', script=None):
        self.save()
        text = script if script is not None else (REPO / 'deploy/migrate-single-target.sh').read_text()
        for old, new in [('/opt/ai-trader-staging', self.work), ('/run/lock/ai-trader-deploy.lock', self.root/'lock'),
                         ('/opt/ai-trader-migration006.XXXXXXXX', self.root/'migration.XXXXXXXX'),
                         ('/opt/ai-trader-release.XXXXXXXX', self.root/'release.XXXXXXXX')]:
            text = text.replace(old, new.as_posix())
        path = self.root / 'release.sh'; path.write_text(text, newline='\n')
        env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                   HARNESS_STATE=str(self.state_path), HARNESS_ARCHIVE=str(self.archive), MSYS_NO_PATHCONV='1')
        env.pop('APP_IMAGE', None)
        if os.name == 'nt': env['TAR_OPTIONS'] = '--force-local'
        prefix = self.bin.as_posix()
        if os.name == 'nt': prefix = '/' + prefix[0].lower() + prefix[2:]
        launch = 'export PATH=' + shlex.quote(prefix) + ':"$PATH"; exec bash "$@"'
        result = subprocess.run([self.bash, '--noprofile', '--norc', '-c', launch, 'harness', str(path), TARGET, mode, OLD], env=env, capture_output=True, text=True, timeout=40)
        self.state = json.loads(self.state_path.read_text())
        return result

    def test_reproduce_reviewed_retry_dead_end(self):
        old = subprocess.check_output(['git', 'show', '7ae71679e7c8e9243a80788b1d4ace84e21d2b87:deploy/migrate-single-target.sh'], cwd=REPO, text=True)
        self.state['fail_start'] = True
        first = self.run_script(script=old)
        self.assertNotEqual(first.returncode, 0)
        self.assertEqual((self.state['schema'], self.state['active'], self.state['ddl']), (6, OLD, 1), str(first.returncode) + first.stdout + first.stderr + str(self.state['commands']))
        retry = self.run_script(script=old)
        self.assertNotEqual(retry.returncode, 0, retry.stdout)
        self.assertIn('AssertionError', retry.stderr)
        self.assertEqual(self.state['ddl'], 1)
        normal = (REPO / 'deploy/hetzner-deploy.sh').read_text()
        retry = self.run_script(script=normal)
        self.assertEqual(retry.returncode, 66, retry.stdout + retry.stderr)
        self.assertIn('Schema change requires operator-approved migration', retry.stdout)

    def test_failure_006_rollback_failed_resume_then_success_without_ddl(self):
        self.state['fail_start'] = True
        first = self.run_script()
        self.assertEqual(first.returncode, 7, first.stdout + first.stderr)
        self.assertEqual((self.state['schema'], self.state['active'], self.state['ddl']), (6, OLD, 1))
        self.assertEqual(self.state['marker'], BRIDGE)
        self.state['fail_start'] = True
        again = self.run_script('--approved-resume-schema-6')
        self.assertEqual(again.returncode, 7, again.stdout + again.stderr)
        self.assertEqual((self.state['schema'], self.state['active'], self.state['ddl']), (6, OLD, 1))
        result = self.run_script('--approved-resume-schema-6')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.state['schema'], self.state['active'], self.state['ddl']), (6, NEW, 1))
        self.assertEqual(self.state['backups'], 4)  # preflight each try + successful postflight
        self.assertEqual(self.state['marker'], TARGET)
        self.assertEqual((self.work/'deploy/last-release').read_text().splitlines(), [TARGET, NEW, OLD])
        self.assertEqual((self.work/'deploy/single-target-compatible-image').read_text().splitlines(), [BRIDGE, OLD])

    def test_invalid_schema6_and_unsafe_bridge_rejected_before_stop(self):
        for damaged in ('missing_006', 'missing_earlier', 'future_version', 'missing_column', 'not_nullable', 'wrong_type', 'wrong_default',
                        'incompatible_bridge', 'missing_image', 'creation_on', 'checks_failed', 'stale_sha', 'competing_release', 'backup_failed'):
            with self.subTest(damaged=damaged):
                self.state = initial(); self.state.update(schema=6, versions=list(range(1, 7)))
                if damaged == 'missing_006': self.state['versions'].remove(6)
                if damaged == 'missing_earlier': self.state['versions'].remove(4)
                if damaged == 'future_version': self.state['versions'].append(7)
                if damaged == 'missing_column': self.state['columns'].pop()
                if damaged == 'not_nullable': self.state['columns'][0]['is_nullable'] = 'NO'
                if damaged == 'wrong_type': self.state['columns'][-1]['data_type'] = 'jsonb'
                if damaged == 'wrong_default': self.state['columns'][-1]['column_default'] = None
                if damaged == 'incompatible_bridge': self.state['compatible'] = False
                if damaged == 'missing_image': self.state['image_available'] = False
                if damaged == 'creation_on': self.state['creation'] = True
                if damaged == 'checks_failed': self.state['checks'] = False
                if damaged == 'stale_sha': self.state['main'] = BRIDGE
                if damaged == 'competing_release': self.state['locked'] = True
                if damaged == 'backup_failed': self.state['fail_backup'] = True
                result = self.run_script('--approved-resume-schema-6')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual((self.state['active'], self.state['ddl'], self.state['stops']), (OLD, 0, 0))

    def test_wrong_mode_does_not_guess_schema(self):
        result = self.run_script('--approved-resume-schema-6')
        self.assertNotEqual(result.returncode, 0)
        self.state.update(schema=6, versions=list(range(1, 7)))
        result = self.run_script('--approved-schema-5-to-6')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.state['ddl'], self.state['stops']), (0, 0))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--command': sys.exit(dispatch())
    unittest.main()
