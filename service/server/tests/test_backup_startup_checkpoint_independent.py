"""Independent checkpoint review: synthetic files/Git/HTTP/export only."""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

AT=datetime(2026,11,8,13,30,tzinfo=timezone.utc)
SHA='a'*40;COMMIT='b'*40;RID='c'*32
CIPHER=b'age-encryption.org/v1\nsynthetic ciphertext'


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    if sys.platform=='win32':
        monkeypatch.setitem(sys.modules,'fcntl',NS(LOCK_EX=2,LOCK_NB=4,flock=lambda *a:None))
    policy={'synthetic_policy':'one'}
    recovery=NS(runtime_policy=lambda:dict(policy),
                export_postgres=Mock(return_value={'recovery_format':10,'snapshot_id':'d'*64,
                                                  'hold_coverage':{'order_ids':[]}}),
                encrypted_bytes=Mock(return_value=(CIPHER,{'encrypted_bytes':len(CIPHER)})))
    monkeypatch.setitem(sys.modules,'recovery_state',recovery)
    monkeypatch.setitem(sys.modules,'sec_history',NS(export_archive=Mock(return_value=None)))
    monkeypatch.setitem(sys.modules,'scanner_engine',NS(set_service_status=Mock()))
    path=Path(__file__).resolve().parents[1]/'recovery_backup.py'
    spec=importlib.util.spec_from_file_location('_independent_startup_backup',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    repo=tmp_path/'repository';(repo/'.git').mkdir(parents=True)
    monkeypatch.setenv('RECOVERY_WORKDIR',str(repo));monkeypatch.setenv('BUILD_SHA',SHA)
    monkeypatch.setenv('RECOVERY_GITHUB_REPO','synthetic/private')
    for env in ('DATABASE_URL_FILE','AGE_RECIPIENT_FILE'):
        f=tmp_path/env;f.write_text('synthetic');monkeypatch.setenv(env,str(f))
    monkeypatch.setattr(m.time,'time',lambda:AT.timestamp())
    monkeypatch.setattr(m,'datetime',NS(now=lambda *a:AT,fromisoformat=datetime.fromisoformat))
    marker=tmp_path/'health';monkeypatch.setattr(m,'HEALTH_MARKER',marker)
    http=Mock(return_value=NS(status_code=404));monkeypatch.setattr(m.requests,'get',http)
    commands=[]
    def command(*args,**kwargs):
        commands.append(args)
        if args[1:]==('remote','get-url','origin'):return b'git@github.com:synthetic/private.git\n'
        if args[1:]==('rev-parse','HEAD'):return (COMMIT+'\n').encode()
        if args[1:]==('ls-remote','origin','refs/heads/main'):return (COMMIT+'\trefs/heads/main\n').encode()
        if args[1]=='cat-file':return str(len(CIPHER)).encode()
        if args[1]=='show':return CIPHER
        if args[1:]==('branch','-r'):return b'origin/main'
        if args[1] in {'fetch','merge','add','push','-c'}:return b''
        raise AssertionError('unexpected synthetic command')
    monkeypatch.setattr(m,'command',command)
    status={'success_at':'2026-11-08T13:15:00+00:00','snapshot_id':'d'*64,
            'encrypted_bytes':len(CIPHER),'managed_request':{'version':1,'request_id':RID,'build_sha':SHA,
             'predeploy':True,'started_at':'2026-11-08T13:14:00+00:00',
             'finished_at':'2026-11-08T13:26:00+00:00','remote_commit':COMMIT},
            'startup_checkpoint':{'version':1,'build_sha':SHA,'request_id':RID,'remote_commit':COMMIT,
             'cipher_sha256':hashlib.sha256(CIPHER).hexdigest(),'cipher_bytes':len(CIPHER),
             'runtime_policy_sha256':m.policy_digest()}}
    status_path=tmp_path/'status.json';status_path.write_text(json.dumps(status))
    return NS(m=m,repo=repo,marker=marker,status=status,path=status_path,policy=policy,
              recovery=recovery,commands=commands,http=http,command=command)


def test_repeat_restart_retains_original_age_and_never_exports(isolated):
    f=isolated
    for _ in range(2):
        assert f.m.resume_predeploy_checkpoint() is True
        assert f.marker.stat().st_mtime==datetime.fromisoformat(f.status['success_at']).timestamp()
    f.recovery.export_postgres.assert_not_called();f.recovery.encrypted_bytes.assert_not_called()


def test_changed_policy_falls_back_before_any_remote_check(isolated):
    f=isolated;f.policy['synthetic_policy']='changed'
    assert f.m.resume_predeploy_checkpoint() is False
    assert not f.marker.exists() and f.commands==[];f.http.assert_not_called()


@pytest.mark.parametrize('fault',['http','git','git_decode','clock_back','clock_expired'])
def test_unavailable_remote_or_invalid_clock_cannot_certify_health(isolated,monkeypatch,fault):
    f=isolated
    if fault=='http':f.http.side_effect=f.m.requests.Timeout('private')
    if fault=='git':monkeypatch.setattr(f.m,'command',Mock(side_effect=subprocess.TimeoutExpired('synthetic',120)))
    if fault=='git_decode':monkeypatch.setattr(f.m,'command',Mock(return_value=b'\xff'))
    if fault=='clock_back':monkeypatch.setattr(f.m.time,'time',lambda:AT.timestamp()-3600)
    if fault=='clock_expired':monkeypatch.setattr(f.m.time,'time',lambda:AT.timestamp()+901)
    assert f.m.resume_predeploy_checkpoint() is False
    assert not f.marker.exists()


@pytest.mark.parametrize('existing',[False,True])
def test_health_stamp_failure_does_not_publish_fresh_or_replace_old_health(isolated,monkeypatch,existing):
    f=isolated
    if existing:f.marker.write_text('previous health')
    old=datetime(2026,11,8,10,tzinfo=timezone.utc).timestamp()
    if existing:f.m.os.utime(f.marker,(old,old))
    real_utime=f.m.os.utime
    def fail(path,times=None,**kwargs):
        if times is not None:raise OSError('synthetic historical stamp error')
        return real_utime(path,times,**kwargs)
    monkeypatch.setattr(f.m.os,'utime',fail)
    assert f.m.resume_predeploy_checkpoint() is False
    assert f.marker.exists() is existing
    if existing:assert f.marker.stat().st_mtime==old


def test_proof_must_still_be_recent_after_remote_verification(isolated,monkeypatch):
    f=isolated;clock=[AT.timestamp()]
    monkeypatch.setattr(f.m.time,'time',lambda:clock[0])
    def slow_git(*args,**kwargs):
        if args[1]=='show':clock[0]+=901
        return f.command(*args,**kwargs)
    monkeypatch.setattr(f.m,'command',slow_git)
    assert f.m.resume_predeploy_checkpoint() is False
    assert not f.marker.exists()


def test_clock_rollback_during_verification_cannot_make_completion_future(isolated,monkeypatch):
    f=isolated;clock=[AT.timestamp()]
    monkeypatch.setattr(f.m.time,'time',lambda:clock[0])
    def clock_rollback(*args,**kwargs):
        if args[1]=='show':clock[0]=datetime(2026,11,8,13,20,tzinfo=timezone.utc).timestamp()
        return f.command(*args,**kwargs)
    monkeypatch.setattr(f.m,'command',clock_rollback)
    assert f.m.resume_predeploy_checkpoint() is False
    assert not f.marker.exists()


@pytest.mark.parametrize('predeploy,request_id,expected',[(True,RID,True),(True,None,False),
                                                     (False,RID,False),(False,None,False)])
def test_actual_backup_creates_proof_only_for_verified_managed_predeploy(isolated,predeploy,request_id,expected):
    f=isolated;f.path.unlink()
    status=f.m.backup(predeploy,request_id=request_id)
    assert ('startup_checkpoint' in status) is expected
    assert json.loads(f.path.read_text())==status
    assert f.recovery.export_postgres.call_count==1 and f.recovery.encrypted_bytes.call_count==1
    if expected:
        proof=status['startup_checkpoint']
        assert proof['cipher_sha256']==hashlib.sha256(CIPHER).hexdigest()
        assert proof['remote_commit']==COMMIT and proof['build_sha']==SHA
        assert proof['request_id']==RID and proof['runtime_policy_sha256']==f.m.policy_digest()
        assert (f.repo/'predeploy/latest.json.gz.age').read_bytes()==CIPHER
    assert next(i for i,x in enumerate(f.commands) if x[1]=='push')<next(i for i,x in enumerate(f.commands) if x[1]=='ls-remote')


@pytest.mark.parametrize('fault',['push','remote_commit'])
def test_failed_remote_backup_never_publishes_new_checkpoint(isolated,monkeypatch,fault):
    f=isolated;before=f.path.read_bytes()
    def broken(*args,**kwargs):
        if args[1]=='push' and fault=='push':raise subprocess.CalledProcessError(1,'synthetic')
        if args[1]=='ls-remote' and fault=='remote_commit':return ('e'*40+'\trefs/heads/main').encode()
        return f.command(*args,**kwargs)
    monkeypatch.setattr(f.m,'command',broken)
    with pytest.raises((subprocess.SubprocessError,ValueError)):f.m.backup(True,request_id=RID)
    assert f.path.read_bytes()==before and not f.marker.exists()


@pytest.mark.parametrize('args',[['--once'],['--predeploy'],['--request-id',RID],
                               ['--once','--predeploy','--request-id',RID]])
def test_all_explicit_backup_modes_bypass_reuse(isolated,monkeypatch,args):
    f=isolated;calls=[]
    monkeypatch.setattr(f.m,'resume_predeploy_checkpoint',Mock(side_effect=AssertionError('explicit backup skipped')))
    def once(*a,**k):calls.append((a,k));raise KeyboardInterrupt()
    monkeypatch.setattr(f.m,'backup',once);monkeypatch.setattr(sys,'argv',['backup',*args])
    with pytest.raises(KeyboardInterrupt):f.m.main()
    f.m.resume_predeploy_checkpoint.assert_not_called()
    assert len(calls)==1


def test_backup_busy_prevents_proof_and_remote_calls(isolated,monkeypatch):
    f=isolated;before=f.path.read_bytes()
    monkeypatch.setattr(f.m,'acquire_backup_lock',Mock(side_effect=f.m.BackupBusy('busy')))
    with pytest.raises(f.m.BackupBusy):f.m.resume_predeploy_checkpoint()
    with pytest.raises(f.m.BackupBusy):f.m.backup(True,request_id=RID)
    f.http.assert_not_called();f.recovery.export_postgres.assert_not_called()
    assert f.commands==[] and f.path.read_bytes()==before and not f.marker.exists()


def test_cross_hour_start_never_extends_backup_interval_beyond_capture_plus_hour(isolated,monkeypatch):
    f=isolated;captured=datetime(2026,11,8,13,45,tzinfo=timezone.utc).timestamp()
    started=datetime(2026,11,8,14,5,tzinfo=timezone.utc).timestamp()
    f.marker.touch();f.m.os.utime(f.marker,(captured,captured))
    monkeypatch.setattr(f.m.time,'time',lambda:started)
    monkeypatch.setattr(f.m,'resume_predeploy_checkpoint',lambda:True)
    monkeypatch.setattr(f.m,'backup',Mock(side_effect=AssertionError('unexpected initial backup')))
    waits=[]
    def sleep(seconds):waits.append(seconds);raise KeyboardInterrupt()
    monkeypatch.setattr(f.m.time,'sleep',sleep);monkeypatch.setattr(sys,'argv',['backup'])
    with pytest.raises(KeyboardInterrupt):f.m.main()
    assert waits==[2400]  # 14:45 capture+hour, rather than 15:00 next UTC hour.
