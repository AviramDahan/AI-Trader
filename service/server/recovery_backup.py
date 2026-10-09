"""Hourly encrypted active-state backups to one dedicated private Git repository.

Normal Git history is deliberately NOT rewritten. Size warnings include historical
objects, not only retained files. No decryption key belongs on the source server.
"""
import argparse
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import recovery_state


def command(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, timeout=120).stdout


def retention_paths(now, predeploy=False):
    paths=[f'hourly/{now:%Y%m%dT%H}Z.json.gz.age',f'daily/{now:%Y%m%d}.json.gz.age',
           f'weekly/{now:%G-W%V}.json.gz.age']
    if predeploy:
        paths.append('predeploy/latest.json.gz.age')
    return paths


def prune(repo):
    for kind,count in (('hourly',24),('daily',7),('weekly',4)):
        for path in sorted((repo/kind).glob('*.json.gz.age'),reverse=True)[count:]:
            path.unlink()


def backup(predeploy=False):
    repo=Path(os.getenv('RECOVERY_WORKDIR','/backup/repository'))
    slug=os.environ['RECOVERY_GITHUB_REPO']
    # Never upload to a repo readable anonymously. API outages fail closed.
    if requests.get('https://api.github.com/repos/'+slug,timeout=20).status_code!=404:
        raise ValueError('private_repository_check_failed')
    repo.parent.mkdir(parents=True,exist_ok=True)
    with (repo.parent/'backup.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        os.environ['GIT_SSH_COMMAND']='ssh -i /run/secrets/recovery_deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/run/secrets/github_known_hosts'
        remote='git@github.com:'+slug+'.git'
        if not (repo/'.git').exists():
            command('git','clone',remote,str(repo))
        if command('git','remote','get-url','origin',cwd=repo).decode().strip()!=remote:
            raise ValueError('unexpected_backup_remote')
        command('git','fetch','origin',cwd=repo)
        branches=command('git','branch','-r',cwd=repo).decode()
        if 'origin/main' in branches:
            command('git','merge','--ff-only','origin/main',cwd=repo)
        url=Path(os.environ['DATABASE_URL_FILE']).read_text().strip()
        recipient=Path(os.environ['AGE_RECIPIENT_FILE']).read_text().strip()
        data=recovery_state.export_postgres(url)
        encrypted,sizes=recovery_state.encrypted_bytes(data,recipient)
        now=datetime.now(timezone.utc)
        from sec_history import export_archive
        sec_archive = export_archive(url, repo, recipient, predeploy=predeploy, now=now)
        for relative in retention_paths(now,predeploy):
            path=repo/relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(encrypted)
        prune(repo)
        command('git','add','hourly','daily','weekly',*(['predeploy'] if (repo/'predeploy').exists() else []),cwd=repo)
        if sec_archive:
            command('git','add','-A','sec',cwd=repo)
        command('git','-c','user.name=AI-Trader Recovery','-c','user.email=recovery@localhost',
                'commit','-m','Encrypted active recovery '+now.isoformat(),cwd=repo)
        command('git','push','origin','HEAD:main',cwd=repo)
        commit = command('git','rev-parse','HEAD',cwd=repo).decode().strip()
        if command('git','ls-remote','origin','refs/heads/main',cwd=repo).decode().split()[0] != commit:
            raise ValueError('backup_remote_commit_not_verified')
        retention = None
        if sec_archive:
            sec_archive['remote_commit'] = commit
            # The rollback bridge archives SEC but never deletes analytical data.
            import cloud_runtime
            if not hasattr(cloud_runtime, 'SEC_SCHEMA7_ROLLBACK_CAPABILITY'):
                from sec_retention import prune_archived
                retention = prune_archived(url, repo, sec_archive)
        history_bytes=sum(p.stat().st_size for p in (repo/'.git').rglob('*') if p.is_file())
        status={'success_at':now.isoformat(),**sizes,'retained_files':len(list(repo.glob('*/*.age'))),
                'recovery_format':data['recovery_format'],
                'held_orders':len(data['hold_coverage']['order_ids']),
                'git_bytes':history_bytes,'warning':history_bytes>=int(os.getenv('RECOVERY_GIT_WARN_BYTES','104857600')),
                'retention':'24 hourly / 7 daily / 4 weekly / latest predeploy',
                'snapshot_id':data['snapshot_id']}
        if sec_archive:
            status['sec_history'] = {'format': 1, 'captured_at': sec_archive['manifest']['captured_at'],
                'manifest': sec_archive['manifest_path'], 'counts': sec_archive['manifest']['counts'],
                'remote_commit': commit, 'retention': retention}
        (repo.parent/'status.json').write_text(json.dumps(status))
        Path('/tmp/backup-ok').touch()
        from scanner_engine import set_service_status
        set_service_status('backup','ok','Encrypted off-server recovery state verified',success=True)
        print(json.dumps(status),flush=True)
        return status


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--predeploy',action='store_true')
    args=parser.parse_args()
    while True:
        try:
            backup(args.predeploy)
        except Exception as exc:
            try:
                from scanner_engine import set_service_status
                set_service_status('backup','error','Recovery backup failed')
            except Exception:
                pass
            # Never log database URLs, SSH details, source rows or provider errors.
            print(json.dumps({'backup':'failed','error_type':type(exc).__name__}),flush=True)
            if args.once: raise SystemExit(1)
            time.sleep(60)
            continue
        if args.once: return
        time.sleep(max(1,3600-time.time()%3600))


if __name__=='__main__':
    main()
