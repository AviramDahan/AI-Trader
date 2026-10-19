"""Immutable Docker identity regression; synthetic exports, no Docker/network."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'deploy'))


def module():
    spec = importlib.util.spec_from_file_location('_image_identity_test', ROOT / 'deploy/docker_image_identity.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def actual_identity():
    # Dated host evidence: these are three DISTINCT immutable digest domains.
    return dict(version=1, kind='oci', runnable_ref='sha256:3516aae133b45a0c42763dbe5ec22a15c664f664c250ecae17f18748090a5531',
        platform='linux/amd64', platform_manifest='sha256:792c40d1051531b5eaf41028d3e6ba81e7f86648408181cab3d318d6b7a5e31b',
        config_digest='sha256:2b9b86c02764023d2a859254c156fe26a91b9a97d337958018291d2f4fb86e0e',
        build_sha='73352136fcd79eb73bac567305434fc06a27bd88', user='10001:10001')


def runtime(identity=None):
    value = identity or actual_identity()
    return dict(Image='sha256:4143ad8375317cbd8dff0bf11b3a3e03344be2b6942857c4d13a43365fa3af21',
        Config=dict(Env=['BUILD_SHA=' + value['build_sha']], User='10001:10001', Image='sha256:' + '4' * 64),
        ImageManifestDescriptor=dict(digest=value['platform_manifest'],
            mediaType='application/vnd.oci.image.manifest.v1+json', platform=dict(os='linux', architecture='amd64')),
        State=dict(Running=True, OOMKilled=False, Health=dict(Status='healthy')))


def test_actual_legacy_handle_requires_exact_oci_runtime_descriptor():
    m = module()
    assert m.verify_container(runtime(), actual_identity(), require_healthy=True)


@pytest.mark.parametrize('change', ['manifest', 'platform', 'build', 'descriptor_missing', 'stopped', 'oom'])
def test_same_build_or_alias_never_substitutes_runtime_content(change):
    m, row = module(), runtime()
    if change == 'manifest': row['ImageManifestDescriptor']['digest'] = 'sha256:' + 'a' * 64
    elif change == 'platform': row['ImageManifestDescriptor']['platform']['architecture'] = 'arm64'
    elif change == 'build': row['Config']['Env'] = ['BUILD_SHA=' + 'a' * 40]
    elif change == 'descriptor_missing': row.pop('ImageManifestDescriptor')
    elif change == 'stopped': row['State']['Running'] = False
    else: row['State']['OOMKilled'] = True
    with pytest.raises(ValueError): m.verify_container(row, actual_identity(), require_healthy=True)


def test_classic_runtime_remains_strict():
    m, value = module(), actual_identity()
    value.update(kind='classic', runnable_ref=value['config_digest'], platform_manifest=None)
    row = runtime(value)
    row.pop('ImageManifestDescriptor')
    row['Image'] = value['config_digest']
    assert m.verify_container(row, value)
    row['Image'] = 'sha256:' + '5' * 64
    with pytest.raises(ValueError): m.verify_container(row, value)


def graph():
    metadata = {}
    def blob(value):
        raw = json.dumps(value, separators=(',', ':')).encode()
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        metadata['blobs/sha256/' + digest[7:]] = raw
        return digest
    config = blob(dict(os='linux', architecture='amd64', config=dict(Env=['BUILD_SHA=' + 'b' * 40], User='10001:10001')))
    manifest = blob(dict(schemaVersion=2, mediaType='application/vnd.oci.image.manifest.v1+json', config=dict(digest=config,
        mediaType='application/vnd.oci.image.config.v1+json', size=len(metadata['blobs/sha256/' + config[7:]]))))
    index = blob(dict(schemaVersion=2, mediaType='application/vnd.oci.image.index.v1+json', manifests=[
        dict(digest=manifest, mediaType='application/vnd.oci.image.manifest.v1+json',
            size=len(metadata['blobs/sha256/' + manifest[7:]]), platform=dict(os='linux', architecture='amd64'))]))
    return metadata, index, manifest, config


def test_hash_checked_graph_keeps_index_manifest_and_config_distinct():
    m = module()
    metadata, index, manifest, config = graph()
    value = m.verify_archive_metadata(metadata, index, manifest)
    assert (value['runnable_ref'], value['platform_manifest'], value['config_digest']) == (index, manifest, config)


@pytest.mark.parametrize('part', ['manifest', 'config', 'index'])
def test_corrupted_export_graph_is_rejected(part):
    m = module()
    metadata, index, manifest, config = graph()
    digest = dict(index=index, manifest=manifest, config=config)[part]
    metadata['blobs/sha256/' + digest[7:]] += b' '
    with pytest.raises(ValueError): m.verify_archive_metadata(metadata, index, manifest)


def test_missing_raw_id_can_only_resolve_tag_with_exact_runtime_manifest(monkeypatch):
    m, value = module(), actual_identity()
    calls = []
    def inspect(image, platform=False):
        calls.append(image)
        if image.startswith('ai-trader:'): return dict(Id=value['runnable_ref'])
        return None
    monkeypatch.setattr(m, '_inspect_image', inspect)
    monkeypatch.setattr(m, 'resolve_image', lambda *a, **k: copy.deepcopy(value))
    assert m.resolve_running(runtime())['runnable_ref'] == value['runnable_ref']
    assert calls[-1] == 'ai-trader:' + value['build_sha']
    value['platform_manifest'] = 'sha256:' + 'a' * 64
    with pytest.raises(ValueError): m.resolve_running(runtime())


def test_mutable_ref_not_accepted_by_resolve_image():
    with pytest.raises(ValueError): module().resolve_image('ai-trader:latest')


def controller(monkeypatch):
    if sys.platform == 'win32':
        monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda *a: None))
    spec = importlib.util.spec_from_file_location('_oci_controller_test', ROOT / 'deploy/hetzner-pull.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_all_five_health_and_commit_gate_use_manifest_not_legacy_raw_handle(monkeypatch):
    m, value = controller(monkeypatch), actual_identity()
    monkeypatch.setattr(m, 'image_identity', lambda *a: value)
    rows = {role: runtime(value) for role in ('api', 'scanner', 'monitor', 'telegram', 'backup')}
    monkeypatch.setattr(m, 'inspect', lambda kind, name: rows[name.removeprefix('ai-trader-cloud-').removesuffix('-1')])
    assert m.healthy_roles(value['build_sha'], value['runnable_ref'])
    rows['backup']['ImageManifestDescriptor']['digest'] = 'sha256:' + '9' * 64
    assert not m.healthy_roles(value['build_sha'], value['runnable_ref'])


def test_managed_backup_freezes_same_identity_without_adopting_raw_alias(monkeypatch):
    m, value = controller(monkeypatch), actual_identity()
    spec = m.backup_spec(value['build_sha'], value['runnable_ref'], 'a' * 32)
    spec['image_identity'] = value
    row = runtime(value)
    row.update(Name='/' + spec['name'], HostConfig=dict(RestartPolicy=dict(Name='no')),
        NetworkSettings=dict(Networks={'isolated': {}}), Mounts=[])
    row['Config'].update(Entrypoint=['python'], Cmd=spec['command'], Labels={
        m.LABEL: spec['request_id'], m.LABEL + '.build_sha': value['build_sha'], m.LABEL + '.phase': 'predeploy'})
    m.validate_backup_container(row, spec, row)
    row['ImageManifestDescriptor']['digest'] = 'sha256:' + '8' * 64
    with pytest.raises(ValueError): m.validate_backup_container(row, spec, row)


def test_export_keeps_original_index_graph_not_platform_filtered_rewrite(monkeypatch):
    # Actual Docker filtered export omitted the original immutable index blob.
    # Selection remains platform-specific INSPECT + hashed index membership;
    # SAVE must retain the FULL original graph, without mutable tag discovery.
    m = module()
    metadata, index, manifest, _ = graph()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, raw in metadata.items():
            item = tarfile.TarInfo(name)
            item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
    stream.seek(0)
    calls = []
    class Export:
        stdout = stream
        def wait(self, timeout=None): return 0
        def poll(self): return 0
        def kill(self): pytest.fail('completed export must not be killed')
    def popen(command, **kwargs):
        calls.append(command)
        assert command == ['docker', 'image', 'save', index]
        return Export()
    monkeypatch.setattr(m.subprocess, 'Popen', popen)
    result = m._export_metadata(index)
    assert m.verify_archive_metadata(result, index, manifest)['runnable_ref'] == index
    assert len(calls) == 1
