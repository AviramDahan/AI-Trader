"""Real Docker Compose readiness, disposable network-none containers, no workers.

Uses the built Linux application image and exact backup health expression.
Only archive completion and timing are simulated (60x time compression).
Real PostgreSQL/age/Git backup integration is covered separately in tests_pg.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main(image):
    health = yaml.safe_load((ROOT / 'deploy/compose.yml').read_text())['services']['backup']['healthcheck']
    assert health['interval'] == '15s' and health['start_period'] == '1200s' and health['retries'] == 2
    cases = [('old_timeout', 11, '10s', '250ms', 10, False),
             ('slow_verified_completion', 11, '20s', '250ms', 20, True),
             ('no_completion', 60, '20s', '250ms', 20, False)]
    with tempfile.TemporaryDirectory(prefix='backup-health-test-') as temp:
        for name, delay, grace, interval, timeout, expected in cases:
            project = 'backup-proof-' + str(os.getpid()) + '-' + name.replace('_', '-')
            definition = {'services': {'backup': {
                'image': image, 'network_mode': 'none', 'read_only': True,
                'tmpfs': ['/tmp'], 'restart': 'no',
                'entrypoint': ['python', '-c',
                    'import time;from pathlib import Path;time.sleep('+str(delay)+
                    ');Path("/tmp/backup-ok").touch();time.sleep(60)'],
                'healthcheck': dict(health, start_period=grace, interval=interval, timeout='1s')
            }}}
            path = Path(temp) / (name + '.json')
            path.write_text(json.dumps(definition))
            command = ['docker','compose','-p',project,'-f',str(path)]
            try:
                run = subprocess.run(command + ['up','-d','--no-build','--wait',
                    '--wait-timeout',str(timeout)], capture_output=True, text=True, timeout=timeout+20)
                rows = json.loads(subprocess.check_output(command + ['ps','--all','--format','json'], text=True))
                if isinstance(rows, dict): rows = [rows]
                assert len(rows) == 1
                # Match the release script's mandatory independent inspection.
                # Compose versions may return zero at a wait timeout while
                # health is still starting. That MUST remain a release failure.
                effective_success = run.returncode == 0 and rows[0]['Health'] == 'healthy'
                assert effective_success == expected, name + ': ' + str(rows) + run.stdout + run.stderr
                assert (rows[0]['Health'] == 'healthy') == expected, rows
                print(json.dumps({'case':name,'status':'PASS','actual_healthy':expected,
                                  'compose_exit':run.returncode,'effective_release_success':effective_success,
                                  'live_archive_verified':False}), flush=True)
            finally:
                subprocess.run(command + ['down','--timeout','1'], capture_output=True, check=True, timeout=15)


if __name__ == '__main__':
    main(sys.argv[1])
