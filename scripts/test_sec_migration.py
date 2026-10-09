"""Run the SEC migration Bash entrypoint against disposable command doubles.

This proves sequencing and resume without touching Production. PostgreSQL and
real-image compatibility remain separate required release checks.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
OLD = 'sha256:' + '1' * 64
NEW = 'sha256:' + '2' * 64
TARGET = 'a' * 40
BRIDGE = 'b' * 40


def initial():
    return dict(schema=6, active=OLD, compatible=True, complete=True, sec_off=True,
                checks=True, main=TARGET, locked=False, ddl=0, backups=0,
                stops=0, fail_start=False, commands=[])


def embedded(code, args, state, image):
    if 'SEC_SCHEMA7_ROLLBACK_CAPABILITY' in code:
        assert image == OLD and state['compatible']
        assert state['schema'] == int(args[0])
        assert state['schema'] != 7 or state['complete']
    elif 'mode()' in code:
        assert image == NEW and state['sec_off']
    elif 'assert_schema' in code:
        assert state['schema'] == 7 and state['complete']
    elif 'deployed-release' in code:
        state['marker'] = args[0]
    else:
        raise AssertionError('unexpected embedded command')


def command(name, args, state):
    state['commands'].append([name, *args])
    if name == 'flock': return 75 if state['locked'] else 0
    if name == 'git':
        print(state['main'] + '\trefs/heads/main'); return 0
    if name == 'curl':
        url = next(a for a in args if a.startswith('https://'))
        if '/actions/runs?' in url:
            print(json.dumps(dict(workflow_runs=[dict(name=n, head_sha=TARGET,
                head_branch='main', event='push', head_repository=dict(full_name='AviramDahan/AI-Trader'),
                conclusion='success' if state['checks'] else 'failure')
                for n in ('CI', 'Cloud readiness (no deployment)')])))
        elif '/archive/' in url:
            shutil.copyfile(os.environ['HARNESS_ARCHIVE'], args[args.index('-o') + 1])
        else: assert url.endswith('/health')
        return 0
    assert name == 'docker', name
    if args[0] == 'inspect': print(state['active']); return 0
    if args[:2] == ['image', 'inspect']:
        if '--format' in args: print(NEW)
        return 0
    if args[0] in ('build', 'tag'): return 0
    if args[0] == 'exec':
        ix = args.index('-c')
        if 'BUILD_SHA' in args[ix+1]: print(BRIDGE)
        else: embedded(args[ix+1], args[ix+2:], state, state['active'])
        return 0
    assert args[:2] == ['compose', '-f'], args
    args = args[5:]
    image = os.environ.get('APP_IMAGE', state['active'])
    if args[0] == 'run':
        if '-c' in args:
            ix = args.index('-c'); embedded(args[ix+1], args[ix+2:], state, image)
        elif args[-1] == 'migrate':
            assert state['schema'] == 6
            state['schema'] = 7; state['ddl'] += 1
        else:
            assert args[-3:] == ['backup', '--once', '--predeploy']
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


class SecMigrationScriptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.bin = self.root/'bin'; self.bin.mkdir()
        self.state_path = self.root/'state.json'; self.state = initial()
        self.bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        assert self.bash
        for name in ('docker', 'curl', 'git', 'flock', 'python3'):
            call = [sys.executable] if name == 'python3' else [sys.executable, str(Path(__file__).resolve()), '--command', name]
            path = self.bin/name
            path.write_text('#!/usr/bin/env bash\nexec ' + shlex.join([x.replace('\\','/') for x in call]) + ' "$@"\n', newline='\n')
            path.chmod(0o755)
        source = self.root/'candidate'; (source/'service/server').mkdir(parents=True)
        (source/'deploy').mkdir()
        (source/'service/server/cloud_runtime.py').write_text('SCHEMA_VERSION = 7\n')
        (source/'deploy/compose.yml').write_text('synthetic: true\n')
        self.archive = self.root/'candidate.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive: archive.add(source, arcname='candidate')
        self.work = self.root/'server'; (self.work/'deploy').mkdir(parents=True)
        (self.work/'deploy/compose.yml').write_text('synthetic: true\n')

    def run_script(self, mode='--approved-schema-6-to-7'):
        self.state_path.write_text(json.dumps(self.state))
        text = (REPO/'deploy/migrate-sec-intelligence.sh').read_text()
        for old, new in [('/opt/ai-trader-staging', self.work),
                         ('/run/lock/ai-trader-deploy.lock', self.root/'lock'),
                         ('/opt/ai-trader-sec007.XXXXXXXX', self.root/'migration.XXXXXXXX')]:
            text = text.replace(old, new.as_posix())
        path = self.root/'release.sh'; path.write_text(text, newline='\n')
        env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                   HARNESS_STATE=str(self.state_path), HARNESS_ARCHIVE=str(self.archive), MSYS_NO_PATHCONV='1')
        env.pop('APP_IMAGE', None)
        if os.name == 'nt': env['TAR_OPTIONS'] = '--force-local'
        prefix = self.bin.as_posix()
        if os.name == 'nt': prefix = '/' + prefix[0].lower() + prefix[2:]
        launch = 'export PATH=' + shlex.quote(prefix) + ':"$PATH"; exec bash "$@"'
        result = subprocess.run([self.bash, '--noprofile', '--norc', '-c', launch, 'harness',
            str(path), TARGET, mode, OLD], env=env, capture_output=True, text=True, timeout=45)
        self.state = json.loads(self.state_path.read_text())
        return result

    def test_failure_after_007_rolls_back_and_resume_never_reruns_ddl(self):
        self.state['fail_start'] = True
        first = self.run_script()
        self.assertEqual(first.returncode, 7, first.stdout + first.stderr)
        self.assertEqual((self.state['schema'], self.state['active'], self.state['ddl']), (7, OLD, 1))
        retry = self.run_script('--approved-resume-schema-7')
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertEqual((self.state['schema'], self.state['active'], self.state['ddl']), (7, NEW, 1))
        self.assertEqual(self.state['marker'], TARGET)
        self.assertEqual((self.work/'deploy/sec-schema7-compatible-image').read_text().splitlines(), [BRIDGE, OLD])

    def test_partial_007_or_wrong_bridge_refused_before_stop(self):
        for failure in ('partial', 'bridge', 'checks', 'stale_sha', 'sec_enabled'):
            with self.subTest(failure=failure):
                self.state = initial(); self.state['schema'] = 7
                if failure == 'partial': self.state['complete'] = False
                if failure == 'bridge': self.state['compatible'] = False
                if failure == 'checks': self.state['checks'] = False
                if failure == 'stale_sha': self.state['main'] = BRIDGE
                if failure == 'sec_enabled': self.state['sec_off'] = False
                result = self.run_script('--approved-resume-schema-7')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.state['active'], self.state['ddl'], self.state['stops']), (OLD, 0, 0))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--command': sys.exit(dispatch())
    unittest.main()
