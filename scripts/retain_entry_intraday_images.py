"""Retain/reload the TWO actual tested CI binaries; never a deployment tool.

Run only in the isolated Linux image-proof job. Archives contain images, not
database snapshots. Decrypted synthetic backups remain in that job's RAM mount.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

BOUND = 250 * 1024 * 1024
ROLES = ('bridge', 'candidate')


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, **kwargs)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def authority():
    path = Path(__file__).resolve().parents[1] / 'deploy/docker_image_identity.py'
    spec = importlib.util.spec_from_file_location('ci_exact_image_identity', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def describe(path, compression):
    return dict(filename=path.name, compression=compression,
                bytes=path.stat().st_size, sha256=digest(path), status='COMPLETE')


def retain_role(role, row, output, identity):
    assert role in ROLES
    tag = 'entry-intraday-' + role + ':test'
    base = output.parent / ('entry-intraday-' + role + '-tested.tar')
    gz, xz = Path(str(base) + '.gz'), Path(str(base) + '.xz')
    run(['bash', '-o', 'pipefail', '-c',
         'docker save "$1" | gzip -1 > "$2"', '_', tag, str(gz)], timeout=240)
    attempts = [describe(gz, 'gzip -1')]
    if gz.stat().st_size > BOUND:
        # Bounded fallback, without relaxing the archive size/retention gate.
        result = subprocess.run(['timeout', '240s', 'bash', '-o', 'pipefail', '-c',
            'docker save "$1" | xz -T2 -6 > "$2"', '_', tag, str(xz)],
            capture_output=True, timeout=260)
        if result.returncode == 0:
            attempts.append(describe(xz, 'xz -T2 -6'))
        else:
            attempts.append(dict(filename=xz.name, compression='xz -T2 -6',
                status='FAILED_OR_TIMED_OUT', maximum_seconds=240,
                not_a_verified_archive=True))
    selected = min((a for a in attempts if a['status'] == 'COMPLETE'), key=lambda a: a['bytes'])
    archive = output.parent / selected['filename']
    retained = 0 < selected['bytes'] <= BOUND
    loaded = None
    if retained:
        decoder = 'xz' if selected['compression'].startswith('xz') else 'gzip'
        run([decoder, '-t', str(archive)], timeout=120)
        run(['bash', '-o', 'pipefail', '-c', decoder + ' -dc "$1" | docker load',
             '_', str(archive)], timeout=120)
        loaded_id = run(['docker', 'image', 'inspect', tag, '--format', '{{.Id}}'],
                        text=True, timeout=30).stdout.strip()
        assert loaded_id == row['image_id'], 'loaded_tested_binary_identity_changed'
        loaded_identity = identity.resolve_image(loaded_id, expected_build=row['build_sha'])
        assert loaded_identity == row['identity']
        code = """import json,os,pathlib,entry_discovery_capabilities as c,entry_discovery as d
p=pathlib.Path(c.__file__);x=c.capabilities()
assert c.BUILD_ROLE==ROLE_VALUE and c.creation_allowed()==(ROLE_VALUE=='candidate')
if ROLE_VALUE=='bridge':assert d.enabled_ids()==()
assert 10 in x['snapshot_formats'] and 'entry_discovery_intraday_v1' in x['audit_versions']
assert 'independent_entry_execution_intraday_v1' in x['execution_versions']
assert os.geteuid()==10001 and p.stat().st_uid==p.parent.stat().st_uid==0
assert p.stat().st_mode&0o222==0 and not os.access(p.parent,os.W_OK)
print(json.dumps({'build_sha':os.environ['BUILD_SHA'],'capabilities':x,'immutable_file_and_parent_verified':True}))
""".replace('ROLE_VALUE', repr(role))
        command = ['docker', 'run', '--rm', '--network', 'none',
                   '-e', 'ENTRY_DISCOVERY_ROLE=candidate']
        for flag in ('VCP_DISCOVERY', 'MOMENTUM_BURST', 'PEAD', 'PULLBACK_RECLAIM',
                     'RS_LEADER', 'INDEPENDENT_INTRADAY', 'INTRADAY_RVOL_CONTEXT'):
            command += ['-e', 'STOCK_SCANNER_' + flag + '_ENABLED=true']
        command += ['--entrypoint', 'python', loaded_id, '-c', code]
        loaded = json.loads(run(command, text=True, timeout=60).stdout)
        assert loaded['build_sha'] == row['build_sha']
        (output / ('loaded-' + role + '-capability.json')).write_text(json.dumps(loaded, indent=2))
        shutil.move(str(archive), output / archive.name)
    manifest = dict(
        archive_bytes=selected['bytes'], archive_sha256=selected['sha256'], bound_bytes=BOUND,
        compression=selected['compression'], retained_filename=archive.name if retained else None,
        compression_attempts=attempts, xz_fallback_maximum_seconds=240,
        verified_loaded_image_id=row['image_id'] if loaded else None,
        config_digest=row['config_digest'], image_identity=row['identity'],
        loaded_capability_verified=bool(loaded), role=role,
        status=('TESTED_FORMAT10_' + role.upper() + '_ARCHIVE_RETAINED_ONE_DAY') if retained else 'IMAGE_ARTIFACT_NOT_RETAINED',
        source_commit=row['build_sha'], image_identity_file='images.json', recovery_format=10,
        rebuild_is_exact_binary_reproduction=False,
        activation_gate='BLOCKED until the exact final-merge SHA binaries, source, target proof and protected compatible rollback certificate are independently verified and pinned on target',
        retained_claim_requires_successful_workflow_upload=True, no_production_activation=True)
    name = 'rollback-artifact.json' if role == 'bridge' else 'candidate-artifact.json'
    (output / name).write_text(json.dumps(manifest, indent=2))
    return manifest


def validate_retained(output, source_sha):
    """Strict pure final-file gate; the workflow separately verifies upload."""
    images = json.loads((output / 'images.json').read_text())
    canonical = authority()
    assert len({row['role'] for row in images}) == len(images)
    total = 0
    for role in ROLES:
        row = next(r for r in images if r['role'] == role)
        name = 'rollback-artifact.json' if role == 'bridge' else 'candidate-artifact.json'
        manifest = json.loads((output / name).read_text())
        loaded = json.loads((output / ('loaded-' + role + '-capability.json')).read_text())
        assert manifest['status'] == 'TESTED_FORMAT10_' + role.upper() + '_ARCHIVE_RETAINED_ONE_DAY'
        assert row['build_sha'] == manifest['source_commit'] == loaded['build_sha'] == source_sha
        assert manifest['loaded_capability_verified'] is True
        assert manifest['verified_loaded_image_id'] == row['image_id']
        assert manifest['config_digest'] == row['config_digest']
        assert manifest['image_identity'] == row['identity']
        canonical.validate_identity(row['identity'])
        assert row['identity']['runnable_ref'] == row['image_id']
        assert row['identity']['build_sha'] == source_sha
        assert row['identity']['config_digest'] == row['config_digest']
        assert type(manifest['archive_bytes']) is int and type(manifest['bound_bytes']) is int
        assert manifest['bound_bytes'] == BOUND and 0 < manifest['archive_bytes'] <= BOUND
        assert manifest['recovery_format'] == 10 and manifest['role'] == role
        filename = manifest['retained_filename']
        assert filename in ('entry-intraday-' + role + '-tested.tar.gz', 'entry-intraday-' + role + '-tested.tar.xz')
        archive = output / filename
        assert archive.stat().st_size == manifest['archive_bytes']
        assert digest(archive) == manifest['archive_sha256']
        total += manifest['archive_bytes']
        caps = loaded['capabilities']
        assert loaded['immutable_file_and_parent_verified'] is True
        assert caps['build_role'] == role and caps['independent_creation'] is (role == 'candidate')
        assert 10 in caps['snapshot_formats']
        assert 'entry_discovery_intraday_v1' in caps['audit_versions']
        assert 'independent_entry_execution_intraday_v1' in caps['execution_versions']
    assert 0 < total <= 2 * BOUND
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    output = args.directory.resolve(strict=True)
    assert output == Path('/tmp/intraday-artifacts'), 'CI_only_fixed_artifact_directory'
    images = json.loads((output / 'images.json').read_text())
    identity = authority()
    for role in ROLES:
        retain_role(role, next(i for i in images if i['role'] == role), output, identity)
    source = json.loads((output / 'source-proof.json').read_text())
    total = validate_retained(output, source['source_commit'])
    print(json.dumps(dict(status='TESTED_BOTH_ARCHIVES_RETAINED_AND_RELOADED', bytes=total,
                         maximum_total_bytes=2 * BOUND, production_activation=False)))


if __name__ == '__main__':
    main()
