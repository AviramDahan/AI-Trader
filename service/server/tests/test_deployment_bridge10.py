"""Isolated deployment transition controls; no Docker, host, DB or provider IO."""
import copy
import importlib.util
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
SHA = 'a'*40
OLD = 'sha256:'+'1'*64
NEW = 'sha256:'+'2'*64
BRIDGE = 'sha256:'+'3'*64


@pytest.fixture
def controller(tmp_path, monkeypatch):
    if sys.platform == 'win32':
        monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda *a: None))
    spec = importlib.util.spec_from_file_location('bridge10_controller', REPO/'deploy/hetzner-pull.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    value.ROOT = tmp_path
    monkeypatch.setattr(value, 'run', lambda *a, **k: pytest.fail('unexpected command IO'))
    monkeypatch.setattr(value.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('unexpected network IO'))
    return value


def canonical(image, build=SHA):
    return dict(version=1, kind='classic', runnable_ref=image, platform='linux/amd64',
                platform_manifest=None, config_digest=image, build_sha=build, user='10001:10001')


def test_certificate_absence_keeps_normal_candidate_build_without_io(controller):
    assert controller.compatible_candidate(SHA, OLD) == '-'


def test_invalid_certificate_is_not_silently_treated_as_absent(controller, monkeypatch):
    (controller.ROOT/controller.COMPATIBLE_CERTIFICATE).write_text('{}')
    monkeypatch.setattr(controller, 'validate_compatible_certificate', lambda *a, **k:
                        (_ for _ in ()).throw(ValueError('synthetic invalid certificate')))
    with pytest.raises(ValueError, match='synthetic invalid certificate'):
        controller.compatible_candidate(SHA, OLD)


def test_approved_candidate_returns_exact_loaded_identity_not_a_rebuild(controller, monkeypatch):
    (controller.ROOT/controller.COMPATIBLE_CERTIFICATE).write_text('{}')
    proof = dict(candidate_identity=canonical(NEW))
    monkeypatch.setattr(controller, 'validate_compatible_certificate', lambda *a, **k: proof)
    assert controller.compatible_candidate(SHA, OLD) == NEW


def certificate_case(controller, monkeypatch):
    """Invented protected artifacts; real readers/hashes/schema checks execute.

    Only the root-owner precondition (and Windows POSIX modes) is doubled for
    these actual temporary files. No helper claims actual image/target proof.
    External Docker/capability/DB/source observations are synthetic boundaries.
    """
    c = controller
    now = datetime.now(timezone.utc)
    old = canonical(OLD, 'b'*40)
    bridge, candidate = canonical(BRIDGE), canonical(NEW)
    tree, probe = 'c'*40, 'd'*64
    folder = c.ROOT/'entry-intraday-rollback-v1'/SHA
    folder.mkdir(parents=True, mode=0o700)
    folder.parent.chmod(0o700); c.ROOT.chmod(0o700)
    owned, changes = set(), {}
    def write(path, raw):
        path.write_bytes(raw); path.chmod(0o600); owned.add(path.stat().st_ino)
    def encoded(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    def digest(raw): return hashlib.sha256(raw).hexdigest()
    write(c.ROOT/'runtime.env', b'STOCK_SCANNER_INDEPENDENT_INTRADAY_ENABLED=false\n')
    write(c.ROOT/'last-release', ('b'*40+'\n'+OLD+'\n').encode())
    fixtures = b'invented literal-source fixture archive bytes'
    write(folder/'fixtures.tar.gz', fixtures)
    pause = dict(revision=3, updated_at=(now-timedelta(minutes=2)).isoformat(), control_sha256='e'*64)
    caps = dict(build_role='bridge', independent_creation=False, snapshot_formats=list(range(1,11)),
        audit_version='entry_discovery_intraday_v1', audit_versions=['entry_discovery_v1','entry_discovery_intraday_v1'],
        execution_version='independent_entry_execution_intraday_v1',
        execution_versions=['independent_entry_execution_v1','independent_entry_execution_intraday_v1'],
        emergency_entry_version='paper_entry_emergency_v1')
    archives = {}
    for role, proof in (('bridge',bridge),('candidate',candidate)):
        raw = ('invented '+role+' archive bytes; not a Docker image').encode()
        name = 'entry-intraday-'+role+'-tested.tar.gz'
        write(folder/name, raw)
        archives[role] = dict(filename=name, sha256=digest(raw), bytes=len(raw),config_digest=proof['config_digest'])
    phases = [dict(phase=p,status='PASS',build_sha=old['build_sha'] if p in ('old_seed','old_reader_refused10') else SHA,
                   probe_sha256=probe) for p in c.COMPATIBLE_PHASES]
    documents = {
        'source-proof.json': dict(source_commit=SHA,source_tree=tree,file_sha256={'scripts/entry_intraday_compatibility_probe.py':probe}),
        'ordered-proof.json': dict(source_commit=SHA,actual_pass_count=16,recovery_format=10,phases=list(c.COMPATIBLE_PHASES)),
        'images.json': [dict(role=r,build_sha=p['build_sha'],image_id=p['config_digest'],config_digest=p['config_digest'])
                        for r,p in (('old',old),('bridge',bridge),('candidate',candidate))],
    }
    for role, proof in (('bridge',bridge),('candidate',candidate)):
        a=archives[role]
        documents['rollback-artifact.json' if role=='bridge' else 'candidate-artifact.json'] = dict(
            source_commit=SHA,archive_sha256=a['sha256'],archive_bytes=a['bytes'],retained_filename=a['filename'],
            verified_loaded_image_id=proof['config_digest'],loaded_capability_verified=True,
            status='TESTED_FORMAT10_'+role.upper()+'_ARCHIVE_RETAINED_ONE_DAY')
    files={}
    for name,value in documents.items():
        raw=encoded(value);write(folder/name,raw);files[name]=digest(raw)
    raw=b'\n'.join(encoded(row) for row in phases)
    write(folder/'results.jsonl',raw);files['results.jsonl']=digest(raw)
    value=dict(version=1,candidate_sha=SHA,artifact_build_sha=SHA,source_tree=tree,
        verified_at=(now-timedelta(minutes=1)).isoformat(),expires_at=(now+timedelta(hours=5)).isoformat(),
        actual_old_identity=old,runtime_sha256=digest((c.ROOT/'runtime.env').read_bytes()),
        marker_sha256=digest((c.ROOT/'last-release').read_bytes()),identity_module_sha256=digest(c._identity_raw),
        bridge_identity=bridge,candidate_identity=candidate,bridge_archive=archives['bridge'],
        candidate_archive=archives['candidate'],probe_sha256=probe,fixtures_sha256=digest(fixtures),
        proof='TARGET_ISOLATED16_FORMAT10_PHASES_PASS',capabilities=caps,entry_pause=pause,proof_files=files)
    target={key:copy.deepcopy(value[key]) for key in ('version','candidate_sha','source_tree','actual_old_identity',
        'bridge_identity','candidate_identity','runtime_sha256','marker_sha256','identity_module_sha256',
        'probe_sha256','fixtures_sha256','entry_pause')}
    target['phases']=copy.deepcopy(phases)
    raw=encoded(target);write(folder/'target-proof.json',raw);value['target_proof_sha256']=digest(raw)
    path=c.ROOT/c.COMPATIBLE_CERTIFICATE
    def save():write(path,encoded(value))
    save()
    original_lstat, original_fstat = Path.lstat, os.fstat
    def as_root(info, path=None):
        data={key:getattr(info,key) for key in ('st_mode','st_uid','st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')}
        data['st_uid']=0
        if os.name=='nt':data['st_mode']=stat.S_IFMT(info.st_mode)|(0o700 if stat.S_ISDIR(info.st_mode) else 0o600)
        if path in changes:data.update(changes[path])
        return SimpleNamespace(**data)
    def lstat(path):
        info=original_lstat(path)
        return as_root(info,path) if path.is_relative_to(c.ROOT) else info
    def fstat(fd):
        info=original_fstat(fd)
        return as_root(info) if info.st_ino in owned else info
    monkeypatch.setattr(Path,'lstat',lstat)
    monkeypatch.setattr(c.os,'fstat',fstat)
    identities={OLD:old,BRIDGE:bridge,NEW:candidate}
    monkeypatch.setattr(c,'image_identity',lambda image,sha=None:copy.deepcopy(identities[image]))
    role_calls=[]
    def inspect(kind,name):
        role_calls.append(name)
        return dict(Image=OLD,Config=dict(Env=['BUILD_SHA='+old['build_sha']],User='10001:10001'),
                    State=dict(Running=True,OOMKilled=False,Health=dict(Status='healthy')))
    monkeypatch.setattr(c,'inspect',inspect)
    monkeypatch.setattr(c,'repository_tree',lambda sha:tree)
    monkeypatch.setattr(c,'paused_entry_proof',lambda:copy.deepcopy(pause))
    def binary(image,immutable=False):
        proof=identities[image]
        observed=copy.deepcopy(caps)
        if image==NEW:observed.update(build_role='candidate',independent_creation=True)
        if image==OLD:observed.update(snapshot_formats=list(range(1,10)),audit_version='entry_discovery_v1',execution_version='independent_entry_execution_v1')
        return dict(build_sha=proof['build_sha'],capabilities=observed,immutable_file_and_parent_verified=True)
    monkeypatch.setattr(c,'binary_capabilities',binary)
    return SimpleNamespace(value=value,folder=folder,path=path,save=save,write=write,identities=identities,
                           changes=changes,role_calls=role_calls,phases=phases,pause=pause)


def test_valid_protected_certificate_checks_actual_files_and_all_old_roles(controller,monkeypatch):
    case=certificate_case(controller,monkeypatch)
    proof=controller.validate_compatible_certificate(SHA,OLD,NEW)
    assert proof['bridge_identity']['runnable_ref']==BRIDGE
    assert proof['candidate_identity']['runnable_ref']==NEW
    assert len(proof['certificate_sha256'])==64
    assert len(case.role_calls)==5


@pytest.mark.parametrize('damage',['wrong_sha','wrong_tree','stale','future','less_than2h','bool_version',
    'extra_key','old_changed','runtime_changed','archive_changed','target_changed','proof_changed',
    'malformed_pause','wrong_new','capability_changed','unprotected_cert'])
def test_invalid_transition_certificate_never_selects_a_bridge(controller,monkeypatch,damage):
    case=certificate_case(controller,monkeypatch)
    v=case.value;new=NEW;now=datetime.now(timezone.utc)
    if damage=='wrong_sha':v['candidate_sha']='f'*40
    elif damage=='wrong_tree':v['source_tree']='f'*40
    elif damage=='stale':v['verified_at']=(now-timedelta(hours=7)).isoformat()
    elif damage=='future':v['verified_at']=(now+timedelta(minutes=1)).isoformat()
    elif damage=='less_than2h':v['expires_at']=(now+timedelta(hours=1)).isoformat()
    elif damage=='bool_version':v['version']=True
    elif damage=='extra_key':v['unchecked_extra']='no'
    elif damage=='old_changed':v['actual_old_identity']=canonical(OLD,'f'*40)
    elif damage=='runtime_changed':case.write(controller.ROOT/'runtime.env',b'changed runtime')
    elif damage=='archive_changed':case.write(case.folder/v['bridge_archive']['filename'],b'changed archive')
    elif damage=='target_changed':case.write(case.folder/'target-proof.json',b'{}')
    elif damage=='proof_changed':case.write(case.folder/'ordered-proof.json',b'{}')
    elif damage=='malformed_pause':v['entry_pause']['revision']=True
    elif damage=='wrong_new':new='sha256:'+'9'*64
    elif damage=='capability_changed':v['capabilities']['independent_creation']=True
    elif damage=='unprotected_cert':case.changes[case.path]={'st_mode':stat.S_IFREG|0o644}
    case.save()
    with pytest.raises(ValueError):controller.validate_compatible_certificate(SHA,OLD,new)


def test_incompatible_old_remains_distinct_from_frozen_supported_rollback(controller,monkeypatch):
    case=certificate_case(controller,monkeypatch)
    attempt='f'*32
    case.write(controller.ROOT/'deployment-attempt.json',json.dumps(dict(version=1,sha=SHA,attempt_id=attempt,
        old_image=OLD,new_image=NEW,phase='PREDEPLOY_PENDING')).encode())
    # Windows cannot fsync directory descriptors; substitute only durable write
    # primitive here. The actual validator/read/hash/selection paths stay real.
    if os.name=='nt':monkeypatch.setattr(controller,'atomic_json',lambda p,v:case.write(p,json.dumps(v).encode()))
    assert controller.check_rollback(SHA,OLD,NEW,attempt)==BRIDGE
    value=json.loads((controller.ROOT/'deployment-attempt.json').read_bytes())
    assert value['old_image']==OLD and value['observed_old_identity']['runnable_ref']==OLD
    assert value['rollback_image']==BRIDGE and value['rollback_mode']=='CERTIFIED_FORMAT10_BRIDGE'
    assert value['entry_pause']==case.pause


@pytest.mark.parametrize('phase,image',[('ROLLED_BACK',BRIDGE),('ROLLING_BACK',BRIDGE),
    ('COMPLETE',BRIDGE),('COMMITTING',NEW)])
def test_same_sha_bridge_or_uncommitted_journal_is_not_completed_candidate(controller,monkeypatch,phase,image):
    case=certificate_case(controller,monkeypatch)
    case.write(controller.ROOT/'last-release',(SHA+'\n'+image+'\n'+OLD+'\n').encode())
    case.write(controller.ROOT/'deployment-attempt.json',json.dumps(dict(sha=SHA,phase=phase,
        new_image=NEW,rollback_image=BRIDGE,old_image=OLD)).encode())
    # Even a misleading healthy marker/source cannot bypass the actual frozen
    # candidate-image and terminal COMPLETE journal requirement.
    monkeypatch.setattr(controller,'healthy_roles',lambda *a:True)
    monkeypatch.setattr(controller,'run',lambda *a,**k:SHA.encode())
    assert controller.completed(SHA) is False


def test_exact_candidate_complete_and_internal_committing_checks_are_distinct(controller,monkeypatch):
    case=certificate_case(controller,monkeypatch)
    case.write(controller.ROOT/'last-release',(SHA+'\n'+NEW+'\n'+BRIDGE+'\n'+OLD+'\n').encode())
    journal=controller.ROOT/'deployment-attempt.json'
    value=dict(sha=SHA,phase='COMMITTING',new_image=NEW,rollback_image=BRIDGE,old_image=OLD)
    case.write(journal,json.dumps(value).encode())
    monkeypatch.setattr(controller,'healthy_roles',lambda *a:True)
    monkeypatch.setattr(controller,'run',lambda *a,**k:SHA.encode())
    assert not controller.completed(SHA)
    assert controller.completed(SHA,allow_committing=True)
    value['phase']='COMPLETE';case.write(journal,json.dumps(value).encode())
    assert controller.completed(SHA)


def test_success_consumes_exact_certificate_and_marks_supported_bridge_not_observed_old(controller,monkeypatch):
    case=certificate_case(controller,monkeypatch)
    attempt='f'*32
    frozen=dict(version=1,sha=SHA,attempt_id=attempt,old_image=OLD,new_image=NEW,phase='COMMITTING',
        rollback_image=BRIDGE,rollback_identity=canonical(BRIDGE),rollback_mode='CERTIFIED_FORMAT10_BRIDGE',
        rollback_certificate_sha256=hashlib.sha256(case.path.read_bytes()).hexdigest())
    case.write(controller.ROOT/'deployment-attempt.json',json.dumps(frozen).encode())
    monkeypatch.setattr(controller,'healthy_roles',lambda *a:True)
    monkeypatch.setattr(controller,'run',lambda *a,**k:SHA.encode())
    if os.name=='nt':
        monkeypatch.setattr(controller,'atomic',lambda p,raw:case.write(p,raw))
    controller.commit_release(SHA,NEW,OLD,attempt)
    assert (controller.ROOT/'last-release').read_text().splitlines()==[SHA,NEW,BRIDGE,OLD]
    assert not case.path.exists()
    assert (case.folder/f'consumed-{attempt}.json').is_file()
    assert json.loads((controller.ROOT/'deployment-attempt.json').read_bytes())['phase']=='COMPLETE'
    assert controller.completed(SHA)


def test_needed_frozen_bridge_rollback_does_not_recheck_certificate_expiry_or_resume(controller,monkeypatch):
    case=certificate_case(controller,monkeypatch)
    attempt='f'*32
    frozen=dict(version=1,sha=SHA,attempt_id=attempt,old_image=OLD,new_image=NEW,phase='ROLLING_BACK',
        rollback_image=BRIDGE,rollback_identity=canonical(BRIDGE),rollback_mode='CERTIFIED_FORMAT10_BRIDGE',
        rollback_certificate_sha256='9'*64,entry_pause=case.pause)
    case.write(controller.ROOT/'deployment-attempt.json',json.dumps(frozen).encode())
    case.value['expires_at']='2020-01-01T00:00:00Z';case.save()
    monkeypatch.setattr(controller,'validate_compatible_certificate',lambda *a,**k:pytest.fail('needed rollback reread expiring certificate'))
    monkeypatch.setattr(controller,'healthy_roles',lambda *a:True)
    commands=[]
    def command(args,*a,**k):
        commands.append(args)
        return args[-1].encode()
    monkeypatch.setattr(controller,'run',command)
    if os.name=='nt':monkeypatch.setattr(controller,'atomic_json',lambda p,v:case.write(p,json.dumps(v).encode()))
    controller.record_bridge_rollback(SHA,BRIDGE,OLD,attempt)
    marker=commands[0][-1]
    assert marker.startswith('ROLLBACK_BRIDGE:') and marker!=SHA
    result=json.loads((controller.ROOT/'last-rollback.json').read_bytes())
    assert result['state']=='SUPPORTED_BRIDGE_NOT_COMPLETED_CANDIDATE'
    assert result['entry_pause']==case.pause
    assert not controller.completed(SHA)
    assert all('set_paused' not in str(command) for command in commands)


def test_print_ref_protocol_keeps_selection_metadata_on_stderr(controller,monkeypatch,capsys):
    monkeypatch.setattr(controller,'deployment_lock',lambda:nullcontext(9))
    def selection(*a):
        controller.emit('SYNTHETIC_SELECTION_METADATA')
        return BRIDGE
    monkeypatch.setattr(controller,'check_rollback',selection)
    controller.main(['--check-rollback','--sha',SHA,'--image',OLD,'--new-image',NEW,
                     '--request-id','f'*32,'--print-ref'])
    result=capsys.readouterr()
    assert result.out==BRIDGE+'\n'
    assert json.loads(result.err)['status']=='SYNTHETIC_SELECTION_METADATA'


def test_direct_compatible_old_path_does_not_need_or_read_certificate(controller,monkeypatch):
    case=certificate_case(controller,monkeypatch)
    case.write(case.path,b'not a certificate')
    caps=copy.deepcopy(case.value['capabilities'])
    monkeypatch.setattr(controller,'binary_capabilities',lambda image,**k:
        dict(build_sha='b'*40 if image==OLD else SHA,capabilities=caps))
    monkeypatch.setattr(controller,'validate_compatible_certificate',lambda *a,**k:pytest.fail('compatible old path read optional certificate'))
    assert controller.check_rollback(SHA,OLD,NEW)==OLD


def test_source_tree_resolution_binds_fixed_repo_and_exact_requested_commit(controller,monkeypatch):
    import io
    calls=[]
    def response(request,**kwargs):
        calls.append((request.full_url,kwargs['timeout']))
        return io.BytesIO(json.dumps(dict(sha=SHA,tree={'sha':'b'*40})).encode())
    monkeypatch.setattr(controller.urllib.request,'urlopen',response)
    assert controller.repository_tree(SHA)=='b'*40
    assert calls==[('https://api.github.com/repos/AviramDahan/AI-Trader/git/commits/'+SHA,15)]
    monkeypatch.setattr(controller.urllib.request,'urlopen',lambda *a,**k:
        io.BytesIO(json.dumps(dict(sha='c'*40,tree={'sha':'b'*40})).encode()))
    with pytest.raises(ValueError,match='compatible_repository_sha_mismatch'):
        controller.repository_tree(SHA)
