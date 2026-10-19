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
        elif name == 'controller':
            def option(key):
                return args[args.index(key) + 1]
            if '--journal-begin' in args:
                state['attempts'] = state.get('attempts', 0) + 1
                work = path.parent / ('owned-release-' + str(state['attempts']))
                work.mkdir(exist_ok=True)
                state['work'] = str(work)
                state['phase'] = 'STARTED'
                print('\t'.join(['c' * 32, work.as_posix(), OLD, '-', 'STARTED']))
            elif '--journal-update' in args:
                state['phase'] = option('--phase')
            elif '--backup-only' in args:
                state['backups'] += 1
                if state.get('fail_prebackup'):
                    return 8
                if state.get('busy_prebackup'):
                    return 75
                print(json.dumps({'status': 'VERIFIED_COMPLETE', 'synthetic_double': True}))
            elif '--stop-backup-idle' in args:
                state['drains'] = state.get('drains', 0) + 1
                if state.get('busy_drain'):
                    return 75
                state['backup_running'] = False
            elif '--check-rollback' in args:
                if state.get('unsafe_old_image'):
                    return 67
            elif '--resolve-running' in args:
                print(state['images'].get(option('--role'), OLD))
            elif '--verify-role' in args:
                role = option('--role')
                image = state['images'].get(role, OLD)
                if image != option('--image'):
                    return 1
                if '--allow-stopped' not in args:
                    if role == 'backup' and not state.get('backup_running', True):
                        return 1
                    if image == NEW and ((role == 'backup' and state.get('silent_starting')) or
                            (role == 'api' and (state.get('stopped_healthy') or state.get('oom_healthy')))):
                        return 1
            elif '--commit-release' in args:
                assert all(state['images'].get(role, OLD) == NEW for role in ('api', 'monitor', 'scanner', 'telegram', 'backup'))
                server = Path(os.environ['BACKUP_TEST_SERVER'])
                (server / 'deploy/last-release').write_text(SHA + '\n' + NEW + '\n' + OLD + '\n')
                state['phase'] = 'COMPLETE'
            else:
                raise AssertionError(args)
        elif name == 'curl':
            if '-o' in args:
                shutil.copyfile(os.environ['BACKUP_TEST_ARCHIVE'], args[args.index('-o') + 1])
        elif name == 'docker':
            if args[0] == 'inspect':
                role = args[-1].removeprefix('ai-trader-cloud-').removesuffix('-1')
                image = state['images'].get(role, OLD)
                if '{{.State.Health.Status}}' in args:
                    print('starting' if state.get('silent_starting') and image==NEW and role=='backup' else 'healthy')
                elif '{{.State.Running}}' in args:
                    running = state.get('backup_running', True) if role == 'backup' else True
                    if image == NEW and role == 'api' and state.get('stopped_healthy'):
                        running = False
                    print('true' if running else 'false')
                elif '{{.State.OOMKilled}}' in args:
                    print('true' if image == NEW and role == 'api' and state.get('oom_healthy') else 'false')
                else:
                    print(image)
            elif args[:2] == ['image', 'inspect']:
                print(NEW)
            elif args[0] == 'exec':
                if 'SCHEMA_VERSION' in args[-1]:
                    print(state.get('schema', 7))
            elif args[0] in ('build', 'tag'):
                pass
            elif args[0] == 'start':
                assert args[-1] == 'ai-trader-cloud-backup-1'
                state['backup_running'] = True
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
                    timeout = int(args[args.index('--wait-timeout') + 1])
                    services = args[args.index('--wait-timeout') + 2:]
                    for service in services:
                        state['images'][service] = image
                    state['active'] = state['images'].get('api', OLD)
                    if 'backup' in services:
                        state['backup_running'] = True
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
                          migrations=0, commands=[], database='unchanged', reservations=123,
                          images={}, backup_running=True)
        self.bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
        self.assertTrue(self.bash, 'Bash required; not silently skipped')
        for name in ('docker', 'curl', 'git', 'flock', 'controller'):
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
                         ('/usr/local/sbin/ai-trader-pull', self.bin / 'controller')):
            text = text.replace(old, new.as_posix())
        script = self.root / 'release.sh'
        script.write_text(text, newline='\n')
        self.state_path.write_text(json.dumps(self.state))
        env = dict(os.environ, BACKUP_TEST_STATE=str(self.state_path),
                   BACKUP_TEST_ARCHIVE=str(self.archive), BACKUP_TEST_SERVER=str(self.server),
                   MSYS_NO_PATHCONV='1')
        env.pop('APP_IMAGE', None)
        env.pop('AI_TRADER_DEPLOY_LOCK_FD', None)
        prefix = self.bin.as_posix()
        if os.name == 'nt':
            prefix = '/' + prefix[0].lower() + prefix[2:]
            env['TAR_OPTIONS'] = '--force-local'
        launch = 'export PATH=' + shlex.quote(prefix) + ':"$PATH"; exec bash "$@"'
        run = subprocess.run([self.bash, '--noprofile', '--norc', '-c', launch,
                              'harness', str(script), SHA], env=env, capture_output=True,
                             # Git Bash starts a Python double for every Docker
                             # inspection; four explicit role guards add real
                             # Windows startup cost, not simulated service wait.
                             # Keep a finite harness-only backstop. Production
                             # stage/unit budgets and Linux controls are intact.
                             text=True, timeout=90 if os.name == 'nt' else 40)
        self.state = json.loads(self.state_path.read_text())
        self.assertEqual((self.state['database'], self.state['reservations']), ('unchanged', 123))
        return run

    def test_old_budget_failure_then_fixed_slow_backup_success(self):
        fixed = (ROOT / 'deploy/hetzner-deploy.sh').read_text()
        old = fixed.replace('backup_wait_seconds=1200', 'backup_wait_seconds=180')
        result = self.run_release(old)
        self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
        self.assertEqual(self.state['active'], OLD)
        self.assertFalse((self.server / 'deploy/last-release').exists())
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.server / 'deploy/last-release').read_text().splitlines(), [SHA, NEW, OLD])
        self.assertEqual(self.state['active'], NEW)

    def test_failed_backup_remains_bounded_and_restores_previous_version(self):
        self.state['backup_seconds'] = 1201
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
        self.assertIn('backup is not healthy/running', result.stdout)

    def test_stopped_or_oom_candidate_with_stale_healthy_marker_is_not_success(self):
        for flag in ('stopped_healthy', 'oom_healthy'):
            with self.subTest(flag=flag):
                self.state[flag] = True
                result = self.run_release()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(self.state['active'], OLD)
                self.assertFalse((self.server / 'deploy/last-release').exists())
                self.state[flag] = False

    def test_prebackup_failure_never_stops_workers(self):
        self.state['fail_prebackup'] = True
        result = self.run_release()
        self.assertEqual(result.returncode, 8)
        self.assertEqual((self.state['stops'], self.state['migrations'], self.state['active']), (0, 0, OLD))

    def test_unknown_old_image_capability_aborts_before_backup_or_writers(self):
        self.state['unsafe_old_image'] = True
        result = self.run_release()
        self.assertEqual(result.returncode, 67, result.stdout + result.stderr)
        self.assertEqual((self.state['backups'], self.state['stops'], self.state['migrations']), (0, 0, 0))
        self.assertEqual(self.state['phase'], 'FAILED', 'explicit exit67 must not bypass the durable failure handler')

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
            self.assertEqual(c[index + 1], '1200' if c[index + 2:] == ['backup'] else '180')

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
        self.assertEqual((check['interval'], check['start_period'], check['retries']), ('15s', '1200s', 2))
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
