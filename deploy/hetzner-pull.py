#!/usr/bin/env python3
"""Root-installed, outbound-only release gate. No GitHub token or inbound access."""
import json,subprocess,urllib.request
from pathlib import Path

REPO='AviramDahan/AI-Trader'
ROOT=Path('/opt/ai-trader-staging/deploy')
def main():
    sha=subprocess.check_output(['git','ls-remote',f'https://github.com/{REPO}.git','refs/heads/main'],text=True,timeout=30).split()[0]
    if len(sha)!=40 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('Invalid SHA')
    for name in ('last-release','failed-release'):
        path=ROOT/name
        if path.exists() and path.read_text().splitlines()[0]==sha:return
    request=urllib.request.Request(f'https://api.github.com/repos/{REPO}/actions/runs?head_sha={sha}&branch=main&event=push&per_page=100',headers={'User-Agent':'AI-Trader-release-gate'})
    with urllib.request.urlopen(request,timeout=30) as r:runs=json.load(r)['workflow_runs']
    selected={}
    for run in runs:
        if run['head_sha']==sha and run['head_branch']=='main' and run['event']=='push' and run['head_repository']['full_name']==REPO:
            selected.setdefault(run['name'],run['conclusion'])
    if any(selected.get(name)!='success' for name in ('CI','Cloud readiness (no deployment)')):return
    result=subprocess.run(['/usr/local/sbin/ai-trader-deploy',sha])
    if result.returncode:
        (ROOT/'failed-release').write_text(sha+'\n')
        raise SystemExit(result.returncode)

if __name__=='__main__':main()
