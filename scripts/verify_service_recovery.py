"""Explicitly inject a local PAPER-service outage and check automatic recovery.

Run only during planned testing: --component children or --component supervisor.
"""
import argparse
import json
import time
from pathlib import Path

import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', choices=['children', 'supervisor'], required=True)
    args = parser.parse_args()
    old = {name: int((RUNTIME / f'{name}.pid').read_text()) for name in ['supervisor', 'backend', 'tunnel']}
    if args.component == 'supervisor':
        process = psutil.Process(old['supervisor'])
        assert any(str(ROOT).lower() in arg.lower() and 'supervise_ai_trader.py' in arg for arg in process.cmdline())
        process.terminate()
    else:
        for name in ['backend', 'tunnel']:
            meta = json.loads((RUNTIME / f'{name}.process.json').read_text())
            process = psutil.Process(meta['pid'])
            assert abs(process.create_time() - meta['created']) < .001
            process.terminate()
    print(f'Injected controlled {args.component} outage', flush=True)
    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            current = {name: int((RUNTIME / f'{name}.pid').read_text()) for name in old}
            if args.component == 'supervisor' and current['supervisor'] == old['supervisor']:
                time.sleep(3)
                continue
            if any(current[name] == old[name] for name in ['backend', 'tunnel']):
                time.sleep(3)
                continue
            url = (RUNTIME / 'backend-url.txt').read_text().strip()
            response = requests.get(url + '/health', timeout=8)
            assert response.ok and response.json()['status'] == 'ok'
            owned = {current['backend']} | {p.pid for p in psutil.Process(current['backend']).children(recursive=True)}
            listeners = [c for c in psutil.net_connections('tcp') if c.status == 'LISTEN' and c.laddr.port == 8000]
            assert len(listeners) == 1 and listeners[0].pid in owned, 'Orphan or duplicate listener'
            print('PASS automatic recovery: new owned processes, exactly one API listener, public HTTPS healthy', flush=True)
            return
        except (OSError, ValueError, KeyError, AssertionError, requests.RequestException, psutil.Error):
            time.sleep(3)
    raise SystemExit('FAIL recovery deadline exceeded')


if __name__ == '__main__':
    main()
