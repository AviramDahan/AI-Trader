"""Run the real release shell with isolated command doubles, no live services."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
OLD = 'sha256:' + '1' * 64
NEW = 'sha256:' + '2' * 64
SHA = 'a' * 40


def dispatch():
    path = Path(os.environ['BACKUP_TEST_STATE'])
    state = json.loads(path.read_text())
    name, args = sys.argv[2], sys.argv[3:]
    state['commands'].append([name, *args])
    try:
        if name == 'flock':
            return 75 if state.get('locked') else 0
        if name == 'git':
            print(state.get('head', SHA) + '\trefs/heads/main')
        elif name == 'curl':
            if '-o' in args:
                shutil.copyfile(os.environ['BACKUP_TEST_ARCHIVE'], args[args.index('-o') + 1])
        elif name == 'docker':
            if args[0] == 'inspect':
                if '{{.State.Health.Status}}' in args:
                    print('starting' if state.get('silent_starting') and state['active']==NEW and args[-1].endswith('-backup-1') else 'healthy')
                else:
                    print(state['active'])
            elif args[:2] == ['image', 'inspect']:
                print(NEW)
            elif args[0] == 'exec':
                if 'SCHEMA_VERSION' in args[-1]:
                    print(state.get('schema', 7))
            elif args[0] in ('build', 'tag'):
                pass
            else:
                assert args[:2] == ['compose', '-f'], args
                args = args[5:]
                if args[0] == 'run':
                    if args[-1] == 'migrate':
                        state['migrations'] += 1
                    else:
                        assert args[-3:] == ['backup', '--once', '--predeploy']
                        state['backups'] += 1
                        if state.get('fail_prebackup'):
                            return 8
                elif args[0] == 'stop':
                    state['stops'] += 1
                elif args[0] == 'up':
                    image = os.environ['APP_IMAGE']
                    state['active'] = image
                    timeout = int(args[args.index('--wait-timeout') + 1])
                    services = args[args.index('--wait-timeout') + 2:]
                    if image == NEW and state.get('fail_api') and 'api' in services:
                        return 9
                    if 'backup' in services:
                        duration = state['backup_seconds'] if image == NEW else 235
                        if duration > timeout:
                            return 7
                else:
                    raise AssertionError(args)
        else:
            raise AssertionError(name)
        return 0
    finally:
        path.write_text(json.dumps(state))


class BackupReleaseReadinessTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.state_path = self.root / 'state.json'
        self.state = dict(active=OLD, backup_seconds=235, backups=0, stops=0,
                          migrations=0, commands=[], database='unchanged', reservations=123)
        self.bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        self.assertTrue(self.bash, 'Bash required; not silently skipped')
        for name in ('docker', 'curl', 'git', 'flock'):
            call = [sys.executable.replace('\\', '/'), str(Path(__file__).resolve()).replace('\\', '/'), '--command', name]
            path = self.bin / name
            path.write_text('#!/usr/bin/env bash\nexec ' + shlex.join(call) + ' "$@"\n', newline='\n')
            path.chmod(0o755)
        source = self.root / 'candidate'
        (source / 'service/server').mkdir(parents=True)
        (source / 'deploy').mkdir()
        (source / 'service/server/cloud_runtime.py').write_text('SCHEMA_VERSION = 7\n')
        (source / 'deploy/compose.yml').write_text('candidate: true\n')
        self.archive = self.root / 'source.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive:
            archive.add(source, arcname='candidate')
        self.server = self.root / 'server'
        (self.server / 'deploy').mkdir(parents=True)
        (self.server / 'deploy/compose.yml').write_text('previous: true\n')

    def run_release(self, source=None):
        text = source or (ROOT / 'deploy/hetzner-deploy.sh').read_text()
        for old, new in (('/opt/ai-trader-staging', self.server),
                         ('/run/lock/ai-trader-deploy.lock', self.root / 'lock'),
                         ('/opt/ai-trader-release.XXXXXXXX', self.root / 'release.XXXXXXXX')):
            text = text.replace(old, new.as_posix())
        script = self.root / 'release.sh'
        script.write_text(text, newline='\n')
        self.state_path.write_text(json.dumps(self.state))
        env = dict(os.environ, BACKUP_TEST_STATE=str(self.state_path),
                   BACKUP_TEST_ARCHIVE=str(self.archive), MSYS_NO_PATHCONV='1')
        env.pop('APP_IMAGE', None)
        prefix = self.bin.as_posix()
        if os.name == 'nt':
            prefix = '/' + prefix[0].lower() + prefix[2:]
            env['TAR_OPTIONS'] = '--force-local'
        launch = 'export PATH=' + shlex.quote(prefix) + ':"$PATH"; exec bash "$@"'
        run = subprocess.run([self.bash, '--noprofile', '--norc', '-c', launch,
                              'harness', str(script), SHA], env=env, capture_output=True,
                             text=True, timeout=40)
        self.state = json.loads(self.state_path.read_text())
        self.assertEqual((self.state['database'], self.state['reservations']), ('unchanged', 123))
        return run

    def test_old_budget_failure_then_fixed_slow_backup_success(self):
        fixed = (ROOT / 'deploy/hetzner-deploy.sh').read_text()
        old = fixed.replace('backup_wait_seconds=600', 'backup_wait_seconds=180')
        result = self.run_release(old)
        self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
        self.assertEqual(self.state['active'], OLD)
        self.assertFalse((self.server / 'deploy/last-release').exists())
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.server / 'deploy/last-release').read_text().splitlines(), [SHA, NEW, OLD])
        self.assertEqual(self.state['active'], NEW)

    def test_failed_backup_remains_bounded_and_restores_previous_version(self):
        self.state['backup_seconds'] = 601
        result = self.run_release()
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual(self.state['active'], OLD)
        self.assertEqual((self.server / 'deploy/compose.yml').read_text(), 'previous: true\n')
        self.assertFalse((self.server / 'deploy/last-release').exists())
        self.assertIn('database never rewound', result.stdout)

    def test_zero_exit_from_compose_without_health_is_not_success(self):
        self.state['silent_starting'] = True
        result = self.run_release()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.state['active'], OLD)
        self.assertFalse((self.server / 'deploy/last-release').exists())
        self.assertIn('backup is not healthy', result.stdout)

    def test_prebackup_failure_never_stops_workers(self):
        self.state['fail_prebackup'] = True
        result = self.run_release()
        self.assertEqual(result.returncode, 8)
        self.assertEqual((self.state['stops'], self.state['migrations'], self.state['active']), (0, 0, OLD))

    def test_api_failure_rolls_back_without_waiting_for_new_backup(self):
        self.state['fail_api'] = True
        result = self.run_release()
        self.assertEqual(result.returncode, 9, result.stdout + result.stderr)
        self.assertEqual(self.state['active'], OLD)

    def test_normal_workers_still_have_180_second_gates(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = [c for c in self.state['commands'] if c[0] == 'docker' and '--wait-timeout' in c]
        for c in commands:
            index = c.index('--wait-timeout')
            self.assertEqual(c[index + 1], '600' if c[index + 2:] == ['backup'] else '180')

    def test_lock_main_schema_guards_unchanged(self):
        for change, code in ((dict(locked=True), 75), (dict(head='b' * 40), 65), (dict(schema=6), 66)):
            with self.subTest(change=change):
                self.state.update(change)
                result = self.run_release()
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertEqual((self.state['stops'], self.state['migrations']), (0, 0))
                self.state.update(locked=False, head=SHA, schema=7)

    def test_health_requires_a_fresh_completed_backup_marker(self):
        # Run the exact Compose health expression, relocated to a disposable path.
        import yaml
        compose = yaml.safe_load((ROOT / 'deploy/compose.yml').read_text())
        check = compose['services']['backup']['healthcheck']
        self.assertEqual((check['interval'], check['start_period'], check['retries']), ('15s', '600s', 2))
        marker = self.root / 'backup-ok'
        expression = check['test'][-1].replace('/tmp/backup-ok', marker.as_posix())
        def health():
            return subprocess.run([sys.executable, '-c', expression], capture_output=True).returncode
        self.assertNotEqual(health(), 0)
        marker.touch()
        self.assertEqual(health(), 0)
        import time
        os.utime(marker, (time.time() - 7501, time.time() - 7501))
        self.assertNotEqual(health(), 0)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--command':
        raise SystemExit(dispatch())
    unittest.main()
