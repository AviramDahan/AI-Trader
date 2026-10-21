"""Strict retained-CI-file gate. No Docker/network/provider or database IO."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('tested_ci_retention', ROOT / 'scripts/retain_entry_intraday_images.py')
RETENTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RETENTION)
SHA = 'a' * 40


@pytest.fixture
def retained(tmp_path):
    images = []
    for index, role in enumerate(('bridge', 'candidate'), start=1):
        image = 'sha256:' + str(index) * 64
        identity = dict(version=1, kind='classic', runnable_ref=image, platform='linux/amd64',
                        platform_manifest=None, config_digest=image, build_sha=SHA, user='10001:10001')
        row = dict(role=role, image_id=image, config_digest=image, identity=identity, build_sha=SHA)
        images.append(row)
        filename = 'entry-intraday-' + role + '-tested.tar.xz'
        data = ('synthetic archive ' + role).encode()
        (tmp_path / filename).write_bytes(data)
        manifest = dict(status='TESTED_FORMAT10_' + role.upper() + '_ARCHIVE_RETAINED_ONE_DAY',
            source_commit=SHA, loaded_capability_verified=True, verified_loaded_image_id=image,
            config_digest=image, image_identity=identity, bound_bytes=RETENTION.BOUND,
            archive_bytes=len(data), archive_sha256=hashlib.sha256(data).hexdigest(),
            recovery_format=10, role=role, retained_filename=filename)
        name = 'rollback-artifact.json' if role == 'bridge' else 'candidate-artifact.json'
        (tmp_path / name).write_text(json.dumps(manifest))
        loaded = dict(build_sha=SHA, immutable_file_and_parent_verified=True,
            capabilities=dict(build_role=role, independent_creation=role == 'candidate',
                snapshot_formats=list(range(1, 11)), audit_versions=['entry_discovery_intraday_v1'],
                execution_versions=['independent_entry_execution_intraday_v1']))
        (tmp_path / ('loaded-' + role + '-capability.json')).write_text(json.dumps(loaded))
    (tmp_path / 'images.json').write_text(json.dumps(images))
    return tmp_path


def test_both_retained_loaded_role_specific_archives_are_required(retained):
    assert RETENTION.validate_retained(retained, SHA) > 0
    (retained / 'candidate-artifact.json').unlink()
    with pytest.raises(FileNotFoundError):
        RETENTION.validate_retained(retained, SHA)


@pytest.mark.parametrize('field,value', [
    ('archive_sha256', '0' * 64), ('archive_bytes', True), ('bound_bytes', True),
    ('archive_bytes', 0), ('loaded_capability_verified', False),
    ('verified_loaded_image_id', 'sha256:' + '9' * 64), ('source_commit', 'b' * 40),
    ('retained_filename', '../outside.tar.xz'), ('role', 'bridge'),
])
def test_invalid_candidate_metadata_never_inherits_a_valid_bridge_pass(retained, field, value):
    path = retained / 'candidate-artifact.json'
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(AssertionError):
        RETENTION.validate_retained(retained, SHA)


@pytest.mark.parametrize('role', ['candidate', 'bridge'])
def test_binary_archive_hash_is_checked_after_retention(retained, role):
    with (retained / ('entry-intraday-' + role + '-tested.tar.xz')).open('ab') as stream:
        stream.write(b'tampered')
    with pytest.raises(AssertionError):
        RETENTION.validate_retained(retained, SHA)


def test_candidate_capability_cannot_be_substituted_for_immutable_bridge(retained):
    path = retained / 'loaded-bridge-capability.json'
    loaded = json.loads(path.read_text())
    loaded['capabilities']['independent_creation'] = True
    path.write_text(json.dumps(loaded))
    with pytest.raises(AssertionError):
        RETENTION.validate_retained(retained, SHA)


def test_cli_refuses_any_non_ci_artifact_directory_before_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['retention', str(tmp_path)])
    monkeypatch.setattr(RETENTION, 'run', lambda *a, **k: pytest.fail('non-CI path invoked Docker'))
    with pytest.raises(AssertionError, match='CI_only'):
        RETENTION.main()


def test_main_push_and_exact_final_binaries_are_part_of_image_workflow():
    text = (ROOT / '.github/workflows/entry-intraday-compatibility.yml').read_text()
    assert 'branches: [main]' in text and "github.event_name == 'push'" in text
    assert 'python scripts/retain_entry_intraday_images.py /tmp/intraday-artifacts' in text
    assert 'retained.validate_retained(base,sha)' in text
    assert "'tested_retained_loaded_candidate':True" in text
