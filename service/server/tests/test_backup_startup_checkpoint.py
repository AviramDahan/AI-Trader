"""Same-build startup checkpoint reuse; synthetic ciphertext and fake Git only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[3]
SHA='a'*40
COMMIT='b'*40
REQUEST='c'*32
CIPHER=b'age-encryption.org/v1\nsynthetic-encrypted-payload'

@pytest.fixture
def fixture(tmp_path,monkeypatch):
    if sys.platform=='win32':
        monkeypatch.setitem(sys.modules,'fcntl',SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *a:None))
    monkeypatch.setitem(sys.modules,'recovery_state',SimpleNamespace(runtime_policy=lambda:{}))
    spec=importlib.util.spec_from_file_location('_startup_checkpoint_backup',ROOT/'service/server/recovery_backup.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    repo=tmp_path/'repository';(repo/'.git').mkdir(parents=True)
    monkeypatch.setenv('RECOVERY_WORKDIR',str(repo));monkeypatch.setenv('RECOVERY_GITHUB_REPO','synthetic/private')
    monkeypatch.setenv('BUILD_SHA',SHA)
    monkeypatch.setattr(m.time,'time',lambda:1794144600.0)  # 2026-11-08T13:30Z
    marker=tmp_path/'backup-ok';monkeypatch.setattr(m,'HEALTH_MARKER',marker,raising=False)
    status={'success_at':'2026-11-08T13:15:00+00:00','snapshot_id':'d'*64,'recovery_format':9,
      'encrypted_bytes':len(CIPHER),'managed_request':{'version':1,'request_id':REQUEST,'build_sha':SHA,
       'predeploy':True,'started_at':'2026-11-08T13:14:00+00:00','finished_at':'2026-11-08T13:26:00+00:00','remote_commit':COMMIT},
      'startup_checkpoint':{'version':1,'build_sha':SHA,'request_id':REQUEST,'remote_commit':COMMIT,
       'cipher_sha256':hashlib.sha256(CIPHER).hexdigest(),'cipher_bytes':len(CIPHER),
       'runtime_policy_sha256':m.policy_digest()}}
    path=tmp_path/'status.json';path.write_text(json.dumps(status))
    requests=Mock(return_value=SimpleNamespace(status_code=404));monkeypatch.setattr(m.requests,'get',requests)
    commands=[]
    def command(*args,**kw):
        commands.append(args)
        assert kw.get('cwd')==repo
        if args==('git','remote','get-url','origin'):return b'git@github.com:synthetic/private.git\n'
        if args==('git','rev-parse','HEAD'):return (COMMIT+'\n').encode()
        if args==('git','ls-remote','origin','refs/heads/main'):return (COMMIT+'\trefs/heads/main\n').encode()
        if args==('git','cat-file','-s',COMMIT+':predeploy/latest.json.gz.age'):return str(len(CIPHER)).encode()
        if args==('git','show',COMMIT+':predeploy/latest.json.gz.age'):return CIPHER
        raise AssertionError('Unexpected command '+str(args))
    monkeypatch.setattr(m,'command',command)
    def write():path.write_text(json.dumps(status))
    return SimpleNamespace(m=m,status=status,path=path,write=write,marker=marker,commands=commands,requests=requests)

def test_verified_checkpoint_skips_export_and_preserves_original_health_age(fixture):
    f=fixture;before=f.path.read_bytes()
    assert f.m.resume_predeploy_checkpoint() is True
    assert f.path.read_bytes()==before
    assert f.marker.stat().st_mtime==1794143700.0  # actual capture, never startup time
    assert len(f.commands)==5
    assert all(not set(cmd)&{'push','fetch','commit','merge'} for cmd in f.commands)
    assert f.requests.call_args.kwargs=={'timeout':20}

@pytest.mark.parametrize('mutate',[
 lambda s:s.pop('startup_checkpoint'),
 lambda s:s['startup_checkpoint'].update(version=2),
 lambda s:s['startup_checkpoint'].update(build_sha='e'*40),
 lambda s:s['startup_checkpoint'].update(request_id='f'*32),
 lambda s:s['startup_checkpoint'].update(remote_commit='e'*40),
 lambda s:s['startup_checkpoint'].update(cipher_sha256='e'*64),
 lambda s:s['startup_checkpoint'].update(cipher_bytes=0),
 lambda s:s['startup_checkpoint'].update(cipher_bytes=16*1024*1024+1),
 lambda s:s['startup_checkpoint'].update(runtime_policy_sha256='e'*64),
 lambda s:s['managed_request'].update(predeploy=False),
 lambda s:s['managed_request'].update(version=True),
 lambda s:s['managed_request'].update(build_sha='e'*40),
 lambda s:s['managed_request'].update(request_id='invalid'),
 lambda s:s['managed_request'].update(finished_at='2026-11-08T13:31:00+00:00'),
 lambda s:s['managed_request'].update(started_at='2026-11-08T13:16:00+00:00'),
 lambda s:s.update(success_at='2026-11-08T12:59:59+00:00'),
 lambda s:s.update(success_at='2026-11-08T13:31:00+00:00'),
 lambda s:s.update(success_at='2026-11-08T13:15:00'),
 lambda s:s.update(snapshot_id='bad'),
 lambda s:s.update(encrypted_bytes=999),
])
def test_invalid_checkpoint_falls_back_without_health_or_status_refresh(fixture,mutate):
    f=fixture;mutate(f.status);f.write();before=f.path.read_bytes()
    assert f.m.resume_predeploy_checkpoint() is False
    assert f.path.read_bytes()==before and not f.marker.exists()

@pytest.mark.parametrize('kind',['remote_head','local_head','origin','size','cipher','public_repo','missing','malformed','oversize'])
def test_external_or_local_proof_failure_never_creates_health(fixture,monkeypatch,kind):
    f=fixture;original=f.m.command
    if kind=='public_repo':monkeypatch.setattr(f.m.requests,'get',lambda *a,**k:SimpleNamespace(status_code=200))
    elif kind=='missing':f.path.unlink()
    elif kind=='malformed':f.path.write_text('{')
    elif kind=='oversize':f.path.write_text(' '*32769)
    else:
        def command(*args,**kw):
            if kind=='remote_head' and args[1]=='ls-remote':return ('e'*40+'\trefs/heads/main').encode()
            if kind=='local_head' and args[1]=='rev-parse':return ('e'*40).encode()
            if kind=='origin' and args[1]=='remote':return b'git@github.com:other/repo.git'
            if kind=='size' and args[1]=='cat-file':return b'999999999'
            if kind=='cipher' and args[1]=='show':return b'corrupt'
            return original(*args,**kw)
        monkeypatch.setattr(f.m,'command',command)
    assert f.m.resume_predeploy_checkpoint() is False
    assert not f.marker.exists()

def test_valid_backup_lock_owner_is_preserved(fixture,monkeypatch):
    f=fixture
    def busy(*a):raise f.m.BackupBusy('backup_lock_busy')
    monkeypatch.setattr(f.m,'acquire_backup_lock',busy)
    with pytest.raises(f.m.BackupBusy):f.m.resume_predeploy_checkpoint()
    f.requests.assert_not_called();assert not f.marker.exists()

@pytest.mark.parametrize('args',[['--once'],['--once','--predeploy','--request-id',REQUEST]])
def test_managed_or_once_backup_cannot_reuse_checkpoint(fixture,monkeypatch,args):
    f=fixture;called=[]
    monkeypatch.setattr(f.m,'resume_predeploy_checkpoint',lambda:pytest.fail('mandatory once backup was skipped'))
    monkeypatch.setattr(f.m,'backup',lambda *a,**k:called.append((a,k)))
    monkeypatch.setattr(sys,'argv',['recovery_backup.py',*args]);f.m.main()
    assert len(called)==1

def test_resumed_daemon_waits_only_until_existing_hourly_schedule(fixture,monkeypatch):
    f=fixture;calls=[]
    f.marker.touch();os.utime(f.marker,(1794143700.0,1794143700.0))
    monkeypatch.setattr(f.m,'resume_predeploy_checkpoint',lambda:True)
    monkeypatch.setattr(f.m,'backup',lambda *a,**k:pytest.fail('redundant startup export'))
    def sleep(seconds):calls.append(seconds);raise KeyboardInterrupt()
    monkeypatch.setattr(f.m.time,'sleep',sleep);monkeypatch.setattr(sys,'argv',['recovery_backup.py'])
    with pytest.raises(KeyboardInterrupt):f.m.main()
    assert calls==[1800]

def test_unavailable_checkpoint_uses_full_existing_backup(fixture,monkeypatch):
    f=fixture;calls=[]
    monkeypatch.setattr(f.m,'resume_predeploy_checkpoint',lambda:False)
    monkeypatch.setattr(f.m,'backup',lambda *a,**k:calls.append(True))
    monkeypatch.setattr(f.m.time,'sleep',lambda seconds:(_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(sys,'argv',['recovery_backup.py'])
    with pytest.raises(KeyboardInterrupt):f.m.main()
    assert calls==[True]
