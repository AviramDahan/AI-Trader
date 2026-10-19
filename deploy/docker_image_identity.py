#!/usr/bin/env python3
"""Bounded immutable Docker identity, shared by installed release operators.

Index, platform manifest and config digests are different domains. A runtime
legacy handle is informational ONLY after its exact platform descriptor binds
to a hash-verified immutable export. No mutable alias is an identity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import tempfile
import threading

PLATFORM = 'linux/amd64'
INDEX_TYPES = ('application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json')
MANIFEST_TYPES = ('application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json')
FIELDS = {'version', 'kind', 'runnable_ref', 'platform', 'platform_manifest', 'config_digest', 'build_sha', 'user'}


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('sha256:[0-9a-f]{64}', value):
        raise ValueError('image_identity_digest_invalid')
    return value


def _env(config):
    return dict(v.split('=', 1) for v in config.get('Env', []) if isinstance(v, str) and '=' in v)


def validate_identity(value):
    if not isinstance(value, dict) or not FIELDS.issubset(value) or set(value) - (FIELDS | {'raw_image_observed'}):
        raise ValueError('image_identity_shape_invalid')
    if type(value.get('version')) is not int or value['version'] != 1 or value.get('kind') not in ('classic', 'oci') or value.get('platform') != PLATFORM:
        raise ValueError('image_identity_version_platform_invalid')
    _digest(value.get('runnable_ref'))
    _digest(value.get('config_digest'))
    if value['kind'] == 'oci': _digest(value.get('platform_manifest'))
    elif value.get('platform_manifest') is not None or value['runnable_ref'] != value['config_digest']:
        raise ValueError('image_identity_classic_digest_invalid')
    if not re.fullmatch('[0-9a-f]{40}', value.get('build_sha', '')) or value.get('user') != '10001:10001':
        raise ValueError('image_identity_source_user_invalid')
    if 'raw_image_observed' in value: _digest(value['raw_image_observed'])
    return value


def _record(kind, reference, manifest, config_digest, config):
    return validate_identity(dict(version=1, kind=kind, runnable_ref=reference, platform=PLATFORM,
        platform_manifest=manifest, config_digest=config_digest, build_sha=_env(config).get('BUILD_SHA'),
        user=config.get('User')))


def verify_archive_metadata(metadata, runnable_ref, platform_manifest):
    """Verify exact RAW metadata blob bytes, never reconstructed JSON hashes."""
    reference, manifest_digest = _digest(runnable_ref), _digest(platform_manifest)
    if not isinstance(metadata, dict) or len(metadata) > 256:
        raise ValueError('image_metadata_bound')
    decoded, raw_blobs = {}, {}
    for name, raw in metadata.items():
        if not isinstance(raw, bytes) or len(raw) > 512 * 1024:
            raise ValueError('image_metadata_blob_bound')
        if name.startswith('blobs/sha256/'):
            if not re.fullmatch('blobs/sha256/[0-9a-f]{64}', name) or hashlib.sha256(raw).hexdigest() != name.rsplit('/', 1)[-1]:
                raise ValueError('image_metadata_hash_mismatch')
            raw_blobs['sha256:' + name.rsplit('/', 1)[-1]] = raw
            try: decoded['sha256:' + name.rsplit('/', 1)[-1]] = json.loads(raw)
            except (ValueError, UnicodeDecodeError): continue
    root = decoded.get(reference)
    if not isinstance(root, dict): raise ValueError('image_index_blob_missing')
    if root.get('mediaType') in INDEX_TYPES:
        matches = [d for d in root.get('manifests', []) if d.get('platform', {}).get('os') == 'linux'
            and d.get('platform', {}).get('architecture') == 'amd64' and not d.get('platform', {}).get('variant')]
        if len(matches) != 1 or matches[0].get('digest') != manifest_digest:
            raise ValueError('image_index_platform_membership_invalid')
        selected = matches[0]
        if selected.get('mediaType') not in MANIFEST_TYPES or type(selected.get('size')) is not int or selected['size'] != len(raw_blobs.get(manifest_digest, b'')):
            raise ValueError('image_manifest_descriptor_invalid')
    elif reference != manifest_digest:
        raise ValueError('image_manifest_reference_invalid')
    manifest = decoded.get(manifest_digest)
    if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 2 or manifest.get('mediaType') not in MANIFEST_TYPES or root.get('schemaVersion') != 2:
        raise ValueError('image_platform_manifest_missing')
    config_descriptor = manifest.get('config', {})
    config_digest = _digest(config_descriptor.get('digest'))
    if config_descriptor.get('mediaType') not in ('application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json') or type(config_descriptor.get('size')) is not int or config_descriptor['size'] != len(raw_blobs.get(config_digest, b'')):
        raise ValueError('image_config_descriptor_invalid')
    config = decoded.get(config_digest)
    if not isinstance(config, dict) or config.get('os') != 'linux' or config.get('architecture') != 'amd64' or config.get('variant'):
        raise ValueError('image_config_platform_invalid')
    return _record('oci', reference, manifest_digest, config_digest, config.get('config', {}))


def _inspect_image(reference, platform=False):
    command = ['docker', 'image', 'inspect']
    if platform: command += ['--platform', PLATFORM]
    result = subprocess.run(command + [reference], capture_output=True, timeout=20)
    if result.returncode: return None
    if len(result.stdout) > 1024 * 1024: raise ValueError('image_inspection_bound')
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != 1: raise ValueError('image_inspection_shape')
    return rows[0]


def _export_metadata(reference):
    """Stream at most2GiB/256 entries; watchdog only kills this export client."""
    # Platform-filtered SAVE can rewrite/omit the original index blob. Export
    # the pinned full graph; selection remains exact linux/amd64 membership.
    process = subprocess.Popen(['docker', 'image', 'save', reference],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    finished = threading.Event()
    def watchdog():
        if not finished.wait(120):
            try: process.kill()
            except ProcessLookupError: pass
    thread = threading.Thread(target=watchdog, daemon=True)
    thread.start()
    metadata, count, size = {}, 0, 0
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for member in archive:
                count += 1
                size += member.size
                if count > 256 or size > 2 * 1024 ** 3: raise ValueError('image_export_bound')
                if not member.isfile() or member.size > 512 * 1024: continue
                if member.name.startswith('blobs/sha256/') or member.name == 'manifest.json':
                    if member.name in metadata: raise ValueError('image_export_duplicate_metadata')
                    metadata[member.name] = archive.extractfile(member).read()
        if process.wait(timeout=5): raise ValueError('image_export_failed')
        return metadata
    finally:
        finished.set()
        if process.poll() is None: process.kill()
        process.wait(timeout=5)
        process.stdout.close()


def _cache_path(directory, reference):
    directory = Path(directory)
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('image_proof_cache_unprotected')
    return directory / (reference[7:] + '.json')


def _write_cache(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.identity-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json.dumps(value, sort_keys=True).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def resolve_image(reference, *, expected_build=None, cache_dir=None):
    """Resolve only an immutable ref. OCI graph proof may use protected cache."""
    reference = _digest(reference)
    row = _inspect_image(reference)
    if not row or row.get('Id') != reference: raise ValueError('immutable_image_unavailable')
    descriptor = row.get('Descriptor') or {}
    if descriptor.get('mediaType') in INDEX_TYPES + MANIFEST_TYPES:
        if descriptor.get('digest') != reference: raise ValueError('image_descriptor_reference_mismatch')
        child = _inspect_image(reference, platform=True)
        if not child: raise ValueError('image_platform_unavailable')
        manifest = _digest(child.get('Id'))
        child_descriptor = child.get('Descriptor') or {}
        if child_descriptor.get('digest') != manifest or child_descriptor.get('mediaType') not in MANIFEST_TYPES or child.get('Os') != 'linux' or child.get('Architecture') != 'amd64':
            raise ValueError('image_selected_platform_inspection_invalid')
        path = _cache_path(cache_dir, reference) if cache_dir is not None else None
        if path is not None and path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 4096:
                raise ValueError('image_proof_file_unprotected')
            value = validate_identity(json.loads(path.read_bytes()))
            if value['runnable_ref'] != reference or value['platform_manifest'] != manifest:
                raise ValueError('image_proof_cache_identity_changed')
        else:
            value = verify_archive_metadata(_export_metadata(reference), reference, manifest)
            if path is not None: _write_cache(path, value)
        # Docker selected-platform inspection must agree with the hashed config.
        if _env(child.get('Config', {})).get('BUILD_SHA') != value['build_sha'] or child.get('Config', {}).get('User') != value['user']:
            raise ValueError('image_platform_config_inspection_mismatch')
    else:
        if descriptor: raise ValueError('image_descriptor_unknown')
        if row.get('Os') != 'linux' or row.get('Architecture') != 'amd64':
            raise ValueError('image_classic_platform_invalid')
        value = _record('classic', reference, None, reference, row.get('Config', {}))
    if expected_build is not None and value['build_sha'] != expected_build:
        raise ValueError('image_expected_source_mismatch')
    return value


def verify_container(row, identity, *, require_healthy=False):
    value = validate_identity(identity)
    if not isinstance(row, dict): raise ValueError('runtime_container_missing')
    if _env(row.get('Config', {})).get('BUILD_SHA') != value['build_sha']:
        raise ValueError('runtime_source_mismatch')
    if row.get('Config', {}).get('User') != value['user']:
        raise ValueError('runtime_user_mismatch')
    descriptor = row.get('ImageManifestDescriptor') or {}
    if value['kind'] == 'oci':
        if descriptor.get('digest') != value['platform_manifest'] or descriptor.get('mediaType') not in MANIFEST_TYPES or descriptor.get('platform') != dict(os='linux', architecture='amd64'):
            raise ValueError('runtime_platform_manifest_mismatch')
    elif descriptor or row.get('Image') != value['config_digest']:
        raise ValueError('runtime_classic_image_mismatch')
    if require_healthy:
        state = row.get('State', {})
        if state.get('Running') is not True or state.get('OOMKilled') or state.get('Health', {}).get('Status') != 'healthy':
            raise ValueError('runtime_not_healthy_running')
    return True


def resolve_running(container_or_row, *, cache_dir=None):
    row = container_or_row
    if isinstance(row, str):
        result = subprocess.run(['docker', 'container', 'inspect', row], capture_output=True, timeout=20)
        if result.returncode or len(result.stdout) > 1024 * 1024: raise ValueError('runtime_inspection_failed')
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or len(rows) != 1: raise ValueError('runtime_inspection_shape')
        row = rows[0]
    if not isinstance(row, dict): raise ValueError('runtime_container_missing')
    raw = _digest(row.get('Image'))
    image = _inspect_image(raw)
    if image is None:
        # The ONLY alias discovery path requires an authoritative runtime
        # descriptor, then verifies exact content against the immutable result.
        descriptor = row.get('ImageManifestDescriptor') or {}
        _digest(descriptor.get('digest'))
        sha = _env(row.get('Config', {})).get('BUILD_SHA', '')
        if not re.fullmatch('[0-9a-f]{40}', sha): raise ValueError('runtime_source_unknown')
        image = _inspect_image('ai-trader:' + sha)
        if not image: raise ValueError('runtime_immutable_content_unavailable')
    reference = _digest(image.get('Id'))
    value = resolve_image(reference, cache_dir=cache_dir)
    verify_container(row, value)
    return dict(value, raw_image_observed=raw)
