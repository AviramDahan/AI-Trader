"""Reviewer-owned canonical image controls, with no Docker/host/network IO."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'deploy/docker_image_identity.py'
BUILD = '73352136fcd79eb73bac567305434fc06a27bd88'
LEGACY = 'sha256:4143ad8375317cbd8dff0bf11b3a3e03344be2b6942857c4d13a43365fa3af21'
INDEX_TYPE = 'application/vnd.oci.image.index.v1+json'
MANIFEST_TYPE = 'application/vnd.oci.image.manifest.v1+json'
CONFIG_TYPE = 'application/vnd.oci.image.config.v1+json'


@pytest.fixture
def identity_module():
    assert SOURCE.is_file(), 'Canonical runtime identity module is required'
    spec = importlib.util.spec_from_file_location('reviewer_oci_identity', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def path(value):
    return 'blobs/sha256/' + value.split(':')[1]


def graph(*, architecture='amd64', os_name='linux', duplicate_platform=False, marker='original'):
    config = raw({'architecture': architecture, 'os': os_name,
                  'config': {'Env': ['BUILD_SHA=' + BUILD], 'User': '10001:10001', 'Labels': {'fixture': marker}},
                  'rootfs': {'type': 'layers', 'diff_ids': []}})
    config_id = digest(config)
    manifest = raw({'schemaVersion': 2, 'mediaType': MANIFEST_TYPE,
                    'config': {'mediaType': CONFIG_TYPE, 'digest': config_id, 'size': len(config)}, 'layers': []})
    manifest_id = digest(manifest)
    descriptor = {'mediaType': MANIFEST_TYPE, 'digest': manifest_id, 'size': len(manifest),
                  'platform': {'os': os_name, 'architecture': architecture}}
    descriptors = [descriptor]
    if duplicate_platform:
        descriptors.append(dict(descriptor))
    index = raw({'schemaVersion': 2, 'mediaType': INDEX_TYPE, 'manifests': descriptors})
    index_id = digest(index)
    metadata = {path(config_id): config, path(manifest_id): manifest, path(index_id): index}
    return metadata, dict(version=1, kind='oci', runnable_ref=index_id, platform='linux/amd64',
                          platform_manifest=manifest_id, config_digest=config_id, build_sha=BUILD,
                          user='10001:10001')


def row_for(identity):
    return {'Id': 'f' * 64, 'Name': '/ai-trader-cloud-api-1', 'Image': LEGACY,
            'Config': {'Image': LEGACY, 'Env': ['BUILD_SHA=' + BUILD], 'User': '10001:10001'},
            'ImageManifestDescriptor': {'mediaType': MANIFEST_TYPE, 'digest': identity['platform_manifest'],
                                        'platform': {'os': 'linux', 'architecture': 'amd64'}},
            'State': {'Running': True, 'Health': {'Status': 'healthy'}, 'OOMKilled': False}}


def test_hashed_graph_links_unresolvable_legacy_container_to_runnable_index(identity_module):
    metadata, expected = graph()
    actual = identity_module.verify_archive_metadata(metadata, expected['runnable_ref'], expected['platform_manifest'])
    for name, value in expected.items():
        assert actual[name] == value
    assert LEGACY not in (actual['runnable_ref'], actual['platform_manifest'], actual['config_digest'])
    identity_module.verify_container(row_for(actual), actual, require_healthy=True)


@pytest.mark.parametrize('attack', ['bad_config_hash', 'bad_manifest_hash', 'bad_index_hash', 'missing_config',
                                  'missing_index', 'unrelated_child', 'descriptor_size', 'config_size'])
def test_archive_graph_tamper_is_not_same_content(identity_module, attack):
    metadata, expected = graph()
    if attack.startswith('bad_'):
        selected = {'bad_config_hash': expected['config_digest'], 'bad_manifest_hash': expected['platform_manifest'],
                    'bad_index_hash': expected['runnable_ref']}[attack]
        metadata[path(selected)] += b' '
    elif attack == 'missing_config':
        del metadata[path(expected['config_digest'])]
    elif attack == 'missing_index':
        del metadata[path(expected['runnable_ref'])]
    elif attack in ('unrelated_child', 'descriptor_size'):
        index = json.loads(metadata[path(expected['runnable_ref'])])
        if attack == 'unrelated_child': index['manifests'][0]['digest'] = 'sha256:' + 'a' * 64
        else: index['manifests'][0]['size'] += 1
        value = raw(index)
        expected['runnable_ref'] = digest(value)
        metadata[path(expected['runnable_ref'])] = value
    else:
        manifest = json.loads(metadata[path(expected['platform_manifest'])])
        manifest['config']['size'] += 1
        value = raw(manifest)
        old_manifest = expected['platform_manifest']
        expected['platform_manifest'] = digest(value)
        metadata[path(expected['platform_manifest'])] = value
        index = json.loads(metadata[path(expected['runnable_ref'])])
        assert index['manifests'][0]['digest'] == old_manifest
        index['manifests'][0].update(digest=expected['platform_manifest'], size=len(value))
        value = raw(index)
        expected['runnable_ref'] = digest(value)
        metadata[path(expected['runnable_ref'])] = value
    with pytest.raises(ValueError):
        identity_module.verify_archive_metadata(metadata, expected['runnable_ref'], expected['platform_manifest'])


@pytest.mark.parametrize('kwargs', [dict(architecture='arm64'), dict(os_name='windows'), dict(duplicate_platform=True)])
def test_wrong_or_ambiguous_platform_is_not_a_runnable_equivalent(identity_module, kwargs):
    metadata, expected = graph(**kwargs)
    with pytest.raises(ValueError):
        identity_module.verify_archive_metadata(metadata, expected['runnable_ref'], expected['platform_manifest'])


def test_same_build_alias_with_different_content_cannot_manage_old_runtime(identity_module):
    first_metadata, first = graph()
    other_metadata, other = graph(marker='different-binary-same-build')
    old = identity_module.verify_archive_metadata(first_metadata, first['runnable_ref'], first['platform_manifest'])
    alias = identity_module.verify_archive_metadata(other_metadata, other['runnable_ref'], other['platform_manifest'])
    assert old['build_sha'] == alias['build_sha'] and old['platform_manifest'] != alias['platform_manifest']
    with pytest.raises(ValueError):
        identity_module.verify_container(row_for(old), alias, require_healthy=True)


@pytest.mark.parametrize('attack', ['wrong_manifest', 'wrong_architecture', 'missing_descriptor',
                                  'wrong_source', 'wrong_user', 'stopped_healthy', 'oom_healthy'])
def test_runtime_association_and_actual_health_are_both_mandatory(identity_module, attack):
    metadata, expected = graph()
    identity = identity_module.verify_archive_metadata(metadata, expected['runnable_ref'], expected['platform_manifest'])
    row = row_for(identity)
    if attack == 'wrong_manifest': row['ImageManifestDescriptor']['digest'] = 'sha256:' + 'b' * 64
    elif attack == 'wrong_architecture': row['ImageManifestDescriptor']['platform']['architecture'] = 'arm64'
    elif attack == 'missing_descriptor': del row['ImageManifestDescriptor']
    elif attack == 'wrong_source': row['Config']['Env'] = ['BUILD_SHA=' + 'c' * 40]
    elif attack == 'wrong_user': row['Config']['User'] = '0:0'
    elif attack == 'stopped_healthy': row['State']['Running'] = False
    else: row['State']['OOMKilled'] = True
    with pytest.raises(ValueError):
        identity_module.verify_container(row, identity, require_healthy=True)


def test_classic_identity_requires_exact_config_id_not_same_source_alias(identity_module):
    _, expected = graph()
    classic = dict(expected, kind='classic', runnable_ref=expected['config_digest'], platform_manifest=None)
    identity_module.validate_identity(classic)
    row = row_for(expected)
    del row['ImageManifestDescriptor']
    row['Image'] = row['Config']['Image'] = classic['config_digest']
    identity_module.verify_container(row, classic, require_healthy=True)
    row['Image'] = LEGACY
    with pytest.raises(ValueError):
        identity_module.verify_container(row, classic, require_healthy=True)


def test_canonical_record_cannot_change_runnable_or_config_without_revalidation(identity_module):
    _, expected = graph()
    bad = copy.deepcopy(expected)
    bad['runnable_ref'] = 'ai-trader:' + BUILD
    with pytest.raises(ValueError): identity_module.validate_identity(bad)
    bad = copy.deepcopy(expected)
    bad['config_digest'] = 'not-a-digest'
    with pytest.raises(ValueError): identity_module.validate_identity(bad)


@pytest.mark.parametrize('version', [True, '1', None, 2])
def test_canonical_version_is_a_strict_integer(identity_module, version):
    _, bad = graph()
    bad['version'] = version
    with pytest.raises(ValueError): identity_module.validate_identity(bad)


def test_classic_record_has_complete_explicit_schema(identity_module):
    _, value = graph()
    classic = dict(value, kind='classic', runnable_ref=value['config_digest'], platform_manifest=None)
    del classic['platform_manifest']
    with pytest.raises(ValueError): identity_module.validate_identity(classic)


def install_runtime_doubles(monkeypatch, module, metadata, identity, *, alias_identity=None):
    inspections, exports = [], []
    selected = alias_identity or identity

    def inspection(reference, platform=False):
        inspections.append((reference, platform))
        if reference == LEGACY:
            return None
        if reference == 'ai-trader:' + BUILD:
            return {'Id': selected['runnable_ref']}
        assert reference == selected['runnable_ref'], 'No unpinned or different image may be inspected'
        return {'Id': selected['platform_manifest'] if platform else selected['runnable_ref'],
                'Descriptor': {'mediaType': MANIFEST_TYPE if platform else INDEX_TYPE,
                               'digest': selected['platform_manifest'] if platform else selected['runnable_ref']},
                'Config': {'Env': ['BUILD_SHA=' + BUILD], 'User': '10001:10001'},
                'Os': 'linux', 'Architecture': 'amd64'}

    def export(reference):
        exports.append(reference)
        assert reference == selected['runnable_ref'], 'Export must use an immutable pinned ref'
        return metadata

    monkeypatch.setattr(module, '_inspect_image', inspection)
    monkeypatch.setattr(module, '_export_metadata', export)
    return inspections, exports


def test_actual_legacy_shape_uses_manifest_proof_and_never_exports_mutable_tag(identity_module, monkeypatch):
    metadata, expected = graph()
    inspections, exports = install_runtime_doubles(monkeypatch, identity_module, metadata, expected)
    identity = identity_module.resolve_running(row_for(expected))
    assert identity['raw_image_observed'] == LEGACY
    for key, value in expected.items(): assert identity[key] == value
    assert inspections[:2] == [(LEGACY, False), ('ai-trader:' + BUILD, False)]
    assert exports == [expected['runnable_ref']]


def test_changed_same_build_tag_cannot_select_other_runtime_content(identity_module, monkeypatch):
    _, original = graph()
    other_metadata, alias = graph(marker='tag-now-points-elsewhere')
    install_runtime_doubles(monkeypatch, identity_module, other_metadata, original, alias_identity=alias)
    with pytest.raises(ValueError, match='runtime_platform_manifest_mismatch'):
        identity_module.resolve_running(row_for(original))


def test_missing_runtime_manifest_cannot_be_recovered_by_build_tag(identity_module, monkeypatch):
    metadata, expected = graph()
    inspections, exports = install_runtime_doubles(monkeypatch, identity_module, metadata, expected)
    row = row_for(expected)
    del row['ImageManifestDescriptor']
    with pytest.raises(ValueError): identity_module.resolve_running(row)
    assert inspections == [(LEGACY, False)] and not exports


def test_expected_build_stays_mandatory_after_full_hashed_graph(identity_module, monkeypatch):
    metadata, expected = graph()
    install_runtime_doubles(monkeypatch, identity_module, metadata, expected)
    with pytest.raises(ValueError, match='image_expected_source_mismatch'):
        identity_module.resolve_image(expected['runnable_ref'], expected_build='f' * 40)


def test_export_keeps_immutable_outer_index_instead_of_filtered_docker_save_profile(identity_module, monkeypatch):
    metadata, expected = graph()
    actual_export = identity_module._export_metadata
    install_runtime_doubles(monkeypatch, identity_module, metadata, expected)
    monkeypatch.setattr(identity_module, '_export_metadata', actual_export)
    commands = []

    def popen(command, *, stdout, stderr):
        commands.append(command)
        assert command[:3] == ['docker', 'image', 'save'] and command[-1] == expected['runnable_ref']
        # Actual target's filtered SAVE profile omitted the immutable original
        # outer index. Model that format without inventing unretained raw bytes.
        exported = dict(metadata)
        if '--platform' in command: del exported[path(expected['runnable_ref'])]
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, content in exported.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        stream.seek(0)
        return SimpleNamespace(stdout=stream, wait=lambda **kwargs: 0, poll=lambda: 0,
                               kill=lambda: pytest.fail('Completed synthetic export must not be killed'))

    monkeypatch.setattr(identity_module.subprocess, 'Popen', popen)
    actual = identity_module.resolve_image(expected['runnable_ref'], expected_build=BUILD)
    assert actual['platform_manifest'] == expected['platform_manifest']
    assert actual['config_digest'] == expected['config_digest']
    assert len(commands) == 1 and '--platform' not in commands[0]


def reviewed_controller(tmp_path, monkeypatch):
    if os.name == 'nt': monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace())
    spec = importlib.util.spec_from_file_location('reviewer_prewriter_controller', ROOT / 'deploy/hetzner-pull.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    real_lstat = Path.lstat
    def owned(path):
        value = real_lstat(path)
        if path.is_relative_to(tmp_path):
            fields = list(value); fields[4] = fields[5] = 0
            if os.name == 'nt':
                fields[0] = stat.S_IFMT(value.st_mode) | (0o700 if stat.S_ISDIR(value.st_mode) else 0o600)
            return os.stat_result(fields)
        return value
    # Nonroot Linux doubles only the root-owner precondition; atomic write,
    # rename/fsync and modes remain real. Windows also doubles POSIX modes and
    # directory-fsync preconditions, not native permission/durability proof.
    monkeypatch.setattr(Path, 'lstat', owned)
    if os.name == 'nt': monkeypatch.setattr(module, 'atomic', lambda path, data: path.write_bytes(data))
    metadata, proof = graph()
    monkeypatch.setattr(module, 'image_identity', lambda image, *a: copy.deepcopy(proof))
    row = row_for(proof)
    monkeypatch.setattr(module, 'inspect', lambda kind, name: copy.deepcopy(row) if name.startswith('ai-trader-cloud-') else None)
    module.WORK_PARENT = tmp_path
    work = tmp_path / 'ai-trader-release.reviewer'; work.mkdir(mode=0o700)
    attempt = dict(version=1, sha='a' * 40, attempt_id='b' * 32, old_image=LEGACY,
                   phase='PREDEPLOY_PENDING', work=str(work), new_image='sha256:' + 'c' * 64)
    journal = tmp_path / 'deployment-attempt.json'
    journal.write_text(json.dumps(attempt))
    latch = tmp_path / 'failed-release'; latch.write_bytes(b'unchanged-historical-failed-source\n')
    other = tmp_path / 'failed-releases'; other.mkdir(); (other / ('a' * 40 + '.json')).write_bytes(b'{"history":true}')
    return module, proof, row, attempt, journal, work


@pytest.mark.parametrize('crash', ['none', 'archive_before_failed', 'failed_before_ack'])
def test_review_close_preserves_real_original_and_rejoins_both_crash_boundaries(tmp_path, monkeypatch, crash):
    module, proof, row, attempt, journal, work = reviewed_controller(tmp_path, monkeypatch)
    original = journal.read_bytes()
    acknowledgements = []
    real_atomic_json = module.atomic_json
    once = []
    def atomic_json(path, value):
        if path == journal and crash == 'archive_before_failed' and not once:
            once.append(True); raise RuntimeError('synthetic crash after original archive')
        real_atomic_json(path, value)
    def emit(status, **fields):
        if crash == 'failed_before_ack' and not once:
            once.append(True); raise RuntimeError('synthetic crash after FAILED')
        acknowledgements.append(dict(status=status, **fields))
    monkeypatch.setattr(module, 'atomic_json', atomic_json)
    monkeypatch.setattr(module, 'emit', emit)
    if crash != 'none':
        with pytest.raises(RuntimeError): module.review_close_prewriter(attempt['sha'], attempt['attempt_id'], proof['runnable_ref'])
        assert json.loads(journal.read_bytes())['phase'] == ('PREDEPLOY_PENDING' if crash == 'archive_before_failed' else 'FAILED')
    module.review_close_prewriter(attempt['sha'], attempt['attempt_id'], proof['runnable_ref'])
    module.review_close_prewriter(attempt['sha'], attempt['attempt_id'], proof['runnable_ref'])
    archived = tmp_path / 'reviewed-attempts' / (attempt['attempt_id'] + '.json')
    assert archived.read_bytes() == original
    final = json.loads(journal.read_bytes())
    assert final['phase'] == 'FAILED' and final['old_image'] == LEGACY
    assert final['review']['archive_sha256'] == hashlib.sha256(original).hexdigest()
    assert final['review']['old_identity'] == proof
    assert all(ack['status'] == 'REVIEWED_PREWRITER_FAILED' for ack in acknowledgements)
    assert (tmp_path / 'failed-release').read_bytes() == b'unchanged-historical-failed-source\n'
    assert (tmp_path / 'failed-releases' / ('a' * 40 + '.json')).read_bytes() == b'{"history":true}'


@pytest.mark.parametrize('damage', ['wrong_phase', 'wrong_sha', 'request_exists', 'job_exists',
                                  'active_pending', 'previous_compose', 'changed_runtime'])
def test_review_close_never_relabels_unproven_prewriter_state(tmp_path, monkeypatch, damage):
    module, proof, row, attempt, journal, work = reviewed_controller(tmp_path, monkeypatch)
    requested_sha = attempt['sha']
    if damage == 'wrong_phase':
        attempt['phase'] = 'REPLACING'; journal.write_text(json.dumps(attempt))
    elif damage == 'wrong_sha': requested_sha = 'f' * 40
    elif damage in ('request_exists', 'active_pending'):
        requests = tmp_path / 'backup-requests'; requests.mkdir()
        name = attempt['attempt_id'] + '.json' if damage == 'request_exists' else 'active.json'
        (requests / name).write_text(json.dumps(dict(version=1, request_id='d' * 32, state='RUNNING_PENDING')))
    elif damage == 'job_exists':
        monkeypatch.setattr(module, 'inspect', lambda *args: dict(State=dict(Running=True)))
    elif damage == 'previous_compose': (work / 'previous-compose.yml').write_bytes(b'writer replacement began')
    else:
        row['ImageManifestDescriptor']['digest'] = 'sha256:' + 'e' * 64
        monkeypatch.setattr(module, 'inspect', lambda *args: copy.deepcopy(row) if args[1].startswith('ai-trader-cloud-') else None)
    original = journal.read_bytes()
    monkeypatch.setattr(module, 'emit', lambda *args, **kwargs: pytest.fail('Unproven review cannot acknowledge success'))
    with pytest.raises(ValueError): module.review_close_prewriter(requested_sha, attempt['attempt_id'], proof['runnable_ref'])
    assert journal.read_bytes() == original
    assert not (tmp_path / 'reviewed-attempts' / (attempt['attempt_id'] + '.json')).exists()


def alter_lstat(monkeypatch, target, *, uid=None, mode=None):
    prior = Path.lstat
    def changed(path):
        value = prior(path)
        if path == target:
            fields = list(value)
            if uid is not None: fields[4] = uid
            if mode is not None: fields[0] = mode
            return os.stat_result(fields)
        return value
    monkeypatch.setattr(Path, 'lstat', changed)


@pytest.mark.parametrize('damage', ['foreign_owner', 'broad_mode', 'symlink'])
def test_first_review_refuses_preexisting_unprotected_original_archive(tmp_path, monkeypatch, damage):
    module, proof, row, attempt, journal, work = reviewed_controller(tmp_path, monkeypatch)
    original = journal.read_bytes()
    archive = tmp_path / 'reviewed-attempts' / (attempt['attempt_id'] + '.json')
    archive.parent.mkdir(mode=0o700); archive.write_bytes(original)
    if damage == 'foreign_owner': alter_lstat(monkeypatch, archive, uid=1000)
    else: alter_lstat(monkeypatch, archive, mode=(stat.S_IFLNK | 0o777) if damage == 'symlink' else (stat.S_IFREG | 0o644))
    monkeypatch.setattr(module, 'emit', lambda *a, **k: pytest.fail('Unprotected archive cannot acknowledge review'))
    with pytest.raises(ValueError): module.review_close_prewriter(attempt['sha'], attempt['attempt_id'], proof['runnable_ref'])
    assert journal.read_bytes() == original and archive.read_bytes() == original


@pytest.mark.parametrize('damage', ['foreign_owner', 'broad_mode', 'symlink', 'wrong_parent', 'wrong_name'])
def test_review_refuses_unproven_work_directory(tmp_path, monkeypatch, damage):
    module, proof, row, attempt, journal, work = reviewed_controller(tmp_path, monkeypatch)
    if damage == 'foreign_owner': alter_lstat(monkeypatch, work, uid=1000)
    elif damage in ('broad_mode', 'symlink'):
        alter_lstat(monkeypatch, work, mode=(stat.S_IFLNK | 0o777) if damage == 'symlink' else (stat.S_IFDIR | 0o755))
    else:
        parent = tmp_path / 'unapproved-parent' if damage == 'wrong_parent' else tmp_path
        parent.mkdir(exist_ok=True)
        work = parent / ('ai-trader-release.foreign' if damage == 'wrong_parent' else 'other-purpose')
        work.mkdir(mode=0o700); attempt['work'] = str(work); journal.write_text(json.dumps(attempt))
    original = journal.read_bytes()
    monkeypatch.setattr(module, 'emit', lambda *a, **k: pytest.fail('Unproven work path cannot acknowledge review'))
    with pytest.raises(ValueError): module.review_close_prewriter(attempt['sha'], attempt['attempt_id'], proof['runnable_ref'])
    assert journal.read_bytes() == original
    assert not (tmp_path / 'reviewed-attempts' / (attempt['attempt_id'] + '.json')).exists()


def test_controller_executes_current_identity_source_not_timestamp_matched_bytecode(tmp_path, monkeypatch):
    import py_compile
    if os.name == 'nt': monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace())
    identity_path = tmp_path / 'docker_image_identity.py'
    identity_path.write_bytes(b"ORIGIN = 'BAD'\n")
    timestamp = identity_path.stat().st_mtime_ns
    py_compile.compile(str(identity_path), doraise=True)
    identity_path.write_bytes(b"ORIGIN = 'NEW'\n")
    os.utime(identity_path, ns=(timestamp, timestamp))
    source = (ROOT / 'deploy/hetzner-pull.py').read_bytes()
    namespace = dict(__file__=str(tmp_path / 'hetzner-pull.py'), __name__='reviewer_exact_source_loader')
    exec(compile(source, namespace['__file__'], 'exec'), namespace)
    assert namespace['identity'].ORIGIN == 'NEW', 'Reviewed source, not matching-size/mtime stale pyc, must execute'


@pytest.mark.parametrize('case', ['valid_oci_legacy_handle', 'wrong_manifest', 'same_build_other_graph', 'wrong_source', 'classic'])
def test_managed_backup_keeps_frozen_identity_across_runtime_handle_domains(tmp_path, monkeypatch, case):
    module, proof, row, attempt, journal, work = reviewed_controller(tmp_path, monkeypatch)
    if case == 'classic':
        proof.update(kind='classic', platform_manifest=None, runnable_ref=proof['config_digest'])
        row['Image'] = proof['config_digest']; row.pop('ImageManifestDescriptor')
    spec = module.backup_spec(BUILD, proof['runnable_ref'], 'a' * 32)
    spec['image_identity'] = proof
    row['Name'] = '/' + spec['name']
    row['Config'].update(Entrypoint=['python'], Cmd=spec['command'], Labels={module.LABEL: spec['request_id'],
                       module.LABEL + '.build_sha': BUILD, module.LABEL + '.phase': 'predeploy'})
    row['HostConfig'] = dict(RestartPolicy=dict(Name='no'), PortBindings={})
    row['NetworkSettings'] = dict(Networks={'isolated': {}})
    row['Mounts'] = [dict(Destination='/backup', Type='volume', Source='/exact/test/backup', RW=True)]
    standing = copy.deepcopy(row)
    if case == 'wrong_manifest': row['ImageManifestDescriptor']['digest'] = 'sha256:' + 'd' * 64
    elif case == 'same_build_other_graph':
        _, other = graph(marker='same-source-distinct-content')
        row['ImageManifestDescriptor']['digest'] = other['platform_manifest']
    elif case == 'wrong_source': row['Config']['Env'] = ['BUILD_SHA=' + 'e' * 40]
    if case in ('valid_oci_legacy_handle', 'classic'): module.validate_backup_container(row, spec, standing)
    else:
        with pytest.raises(ValueError): module.validate_backup_container(row, spec, standing)


def test_oci_managed_request_without_original_frozen_proof_cannot_be_adopted(tmp_path, monkeypatch):
    module, proof, row, attempt, journal, work = reviewed_controller(tmp_path, monkeypatch)
    request = 'a' * 32
    directory = tmp_path / 'backup-requests'; directory.mkdir(mode=0o700)
    saved = dict(version=1, spec=module.backup_spec(BUILD, proof['runnable_ref'], request), state='RUNNING_PENDING')
    path = directory / (request + '.json'); path.write_text(json.dumps(saved)); original = path.read_bytes()
    monkeypatch.setattr(module, 'run', lambda *a, **k: pytest.fail('Unproved historical OCI job cannot launch, kill or remove anything'))
    with pytest.raises(ValueError, match='managed_backup_request_conflict'):
        module.managed_backup(BUILD, proof['runnable_ref'], request, 1)
    assert path.read_bytes() == original and not (directory / 'active.json').exists()
