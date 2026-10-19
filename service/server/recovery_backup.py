"""Hourly encrypted active-state backups to one dedicated private Git repository.

Normal Git history is deliberately NOT rewritten. Size warnings include historical
objects, not only retained files. No decryption key belongs on the source server.
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import recovery_state


MAX_LOCK_WAIT_SECONDS = 900


class BackupBusy(BlockingIOError):
    """A valid writer still owns the shared lock; no backup has failed."""


def acquire_backup_lock(lock, wait_seconds=0):
    """Bound our wait, never the lifetime of an already running backup."""
    if type(wait_seconds) is not int or not 0 <= wait_seconds <= MAX_LOCK_WAIT_SECONDS:
        raise ValueError('invalid_backup_lock_wait')
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackupBusy('backup_lock_busy') from None
            time.sleep(min(0.25, remaining))


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


def backup(predeploy=False, *, lock_wait_seconds=0, request_id=None):
    if request_id is not None and not re.fullmatch('[0-9a-f]{32}', request_id):
        raise ValueError('invalid_backup_request_id')
    build_sha = os.getenv('BUILD_SHA', '')
    if request_id is not None and not re.fullmatch('[0-9a-f]{40}', build_sha):
        raise ValueError('managed_backup_build_sha_missing')
    repo=Path(os.getenv('RECOVERY_WORKDIR','/backup/repository'))
    slug=os.environ['RECOVERY_GITHUB_REPO']
    repo.parent.mkdir(parents=True,exist_ok=True)
    with (repo.parent/'backup.lock').open('a') as lock:
        acquire_backup_lock(lock, lock_wait_seconds)
        started_at = datetime.now(timezone.utc)
        # A busy contender performs no provider call or status mutation. The
        # actual writer still checks anonymity on every real backup attempt.
        if requests.get('https://api.github.com/repos/'+slug,timeout=20).status_code!=404:
            raise ValueError('private_repository_check_failed')
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
                import psycopg
                try:
                    retention = prune_archived(url, repo, sec_archive)
                except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as exc:
                    # Archive delivery succeeded; optional cleanup rolls back
                    # atomically and defers without hiding the maintenance gap.
                    retention = {'deferred': type(exc).__name__, 'deleted': {}}
                from scanner_engine import set_service_status
                set_service_status('sec_history_retention', 'degraded' if 'deferred' in retention else 'ok',
                                   'SEC archive verified; cleanup deferred' if 'deferred' in retention
                                   else 'SEC archive verified; protected history retention checked',
                                   success='deferred' not in retention)
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
        if request_id is not None:
            status['managed_request'] = {'version': 1, 'request_id': request_id,
                'build_sha': build_sha, 'predeploy': bool(predeploy),
                'started_at': started_at.isoformat(),
                'finished_at': datetime.now(timezone.utc).isoformat(),
                'remote_commit': commit}
        # Readers never observe half a proof. This contains metadata only,
        # never a plaintext recovery snapshot or a credential.
        descriptor, temporary = tempfile.mkstemp(prefix='.status-', suffix='.next', dir=repo.parent)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(status, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, repo.parent/'status.json')
        Path('/tmp/backup-ok').touch()
        from scanner_engine import set_service_status
        set_service_status('backup','ok','Encrypted off-server recovery state verified',success=True)
        print(json.dumps(status),flush=True)
        return status


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--predeploy',action='store_true')
    parser.add_argument('--lock-wait-seconds',type=int,default=0)
    parser.add_argument('--request-id')
    args=parser.parse_args()
    if not 0 <= args.lock_wait_seconds <= MAX_LOCK_WAIT_SECONDS:
        parser.error('lock wait must be between 0 and 900 seconds')
    if args.request_id is not None and not re.fullmatch('[0-9a-f]{32}', args.request_id):
        parser.error('request id must be 32 lowercase hexadecimal characters')
    while True:
        try:
            backup(args.predeploy, lock_wait_seconds=args.lock_wait_seconds,
                   request_id=args.request_id)
        except BackupBusy:
            # Contention does not overwrite the last successful snapshot or
            # publish a spurious backup error. The owning writer is untouched.
            print(json.dumps({'backup':'busy','reason':'backup_lock_busy'}),flush=True)
            if args.once:
                raise SystemExit(75)
            time.sleep(60)
            continue
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
