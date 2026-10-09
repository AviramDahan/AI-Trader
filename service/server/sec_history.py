"""Encrypted SEC-only companion archives; no full DB, credentials or news dump.

Format 1 is independent of ACTIVE-state recovery formats 2/3/4. Both release
and rollback binaries must read it. A repeatable-read export streams bounded
chunks; only ciphertext and non-sensitive checksums are written to disk.
"""
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from sec_schema7_compat import REQUIRED_COLUMNS, assert_sec_schema7

FORMAT = 1
TABLES = ('si_universe_snapshots', 'si_filing_jobs', 'si_transactions',
          'si_company_snapshots', 'si_decisions', 'si_checkpoints')
KEYS = {table: ('id',) for table in TABLES}
KEYS.update(si_filing_jobs=('accession',), si_transactions=('event_id',),
            si_decisions=('scan_id', 'ticker', 'mode'), si_checkpoints=('issuer_cik',))
TIMES = dict(si_universe_snapshots='observed_at', si_filing_jobs='first_seen_at',
             si_transactions='effective_available_at', si_company_snapshots='created_at',
             si_decisions='decided_at')
CHUNK_BYTES = 1024 * 1024
MAX_ROW_BYTES = 1024 * 1024
MAX_CHUNKS = 4096
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def history_days():
    days = int(os.getenv('SEC_INTELLIGENCE_HISTORY_DAYS', '400'))
    if not 400 <= days <= 730:
        raise ValueError('sec_history_days_out_of_bounds')
    return days


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def location(repo, name):
    if not re.fullmatch(r'sec/(?:chunks|manifests)/[a-f0-9]{64}\.age', name):
        raise ValueError('unsafe_sec_archive_path')
    root = Path(repo).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError('sec_archive_path_escape')
    return path


def row_valid(table, row):
    if table not in TABLES or set(row) != REQUIRED_COLUMNS[table]:
        raise ValueError('sec_archive_columns_invalid')
    raw = encoded(row)
    if len(raw) > MAX_ROW_BYTES:
        raise ValueError('sec_archive_row_too_large')
    from recovery_state import SECRET_PATTERN
    if SECRET_PATTERN.search(raw.decode()):
        raise ValueError('secret_pattern_in_sec_archive')
    for name, value in os.environ.items():
        if any(part in name for part in ('TOKEN', 'PASSWORD', 'SECRET', 'API_KEY')) and len(value) > 15 and value in raw.decode():
            raise ValueError('environment_secret_in_sec_archive')
    if any(not isinstance(row[key], str) or not row[key] for key in KEYS[table]):
        raise ValueError('sec_archive_identity_invalid')
    if table == 'si_filing_jobs' and row['status'] not in ('queued', 'retry', 'processed', 'unsupported'):
        raise ValueError('sec_archive_status_invalid')
    return raw


def encrypt(raw, recipient):
    return subprocess.run(['age', '-r', recipient], input=gzip.compress(raw, mtime=0),
                          capture_output=True, check=True, timeout=30).stdout


def decrypt(path, identity, limit):
    # Ciphertexts are bounded too; malformed gzip cannot expand without a limit.
    if path.stat().st_size > limit + 128 * 1024:
        raise ValueError('sec_archive_ciphertext_too_large')
    compressed = subprocess.run(['age', '-d', '-i', str(identity), str(path)],
                                capture_output=True, check=True, timeout=30).stdout
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('sec_archive_decompressed_limit')
    return raw


def export_archive(url, repo, recipient, *, predeploy=False, now=None):
    """SEC snapshot only; no init, migration, worker, network or LLM invocation."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=history_days())).isoformat().replace('+00:00', 'Z')
    repo = Path(repo)
    index_path = repo / 'sec/index.json'
    index = json.loads(index_path.read_text()) if index_path.exists() else {'format': FORMAT, 'entries': {}, 'chunks': {}}
    if index.get('format') != FORMAT:
        raise ValueError('unsupported_sec_archive_index')
    chunks, candidates, counts = [], {}, {}
    # Namespace by encryption recipient prevents reuse under a rotated key.
    recipient_id = digest(recipient.encode())
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='30000'")
        version = conn.execute('SELECT max(version) version FROM schema_migrations').fetchone()['version']
        if version < 7:
            return None  # Explicitly absent before 007, not proof of empty SEC.
        if version != 7:
            raise ValueError('unsupported_sec_archive_source_schema')
        assert_sec_schema7(conn)
        capture_at = conn.execute('SELECT transaction_timestamp() AS at').fetchone()['at'].isoformat()

        def flush(table, batch):
            if not batch:
                return
            raw = b''.join(batch)
            content_hash = digest(raw)
            chunk_id = digest((recipient_id + content_hash).encode())
            name = f'sec/chunks/{chunk_id}.age'
            path = location(repo, name)
            previous = index['chunks'].get(name)
            if previous and path.exists():
                if digest(path.read_bytes()) != previous['cipher_sha256']:
                    raise ValueError('sec_archive_existing_chunk_corrupt')
                cipher_hash = previous['cipher_sha256']
            else:
                ciphertext = encrypt(raw, recipient)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(ciphertext)
                cipher_hash = digest(ciphertext)
            part = dict(path=name, table=table, rows=len(batch), bytes=len(raw),
                        sha256=content_hash, cipher_sha256=cipher_hash)
            chunks.append(part)
            if len(chunks) > MAX_CHUNKS:
                raise ValueError('sec_archive_chunk_limit')
            index['chunks'][name] = {'cipher_sha256': cipher_hash}

        for table in TABLES:
            candidates[table], counts[table] = [], 0
            order = tuple(dict.fromkeys(([TIMES[table]] if table in TIMES else []) + list(KEYS[table])))
            query = sql.SQL('SELECT * FROM {} ORDER BY {}').format(
                sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, order)))
            with conn.cursor(name='sec_archive_' + table) as cursor:
                cursor.execute(query)
                batch, size = [], 0
                while True:
                    rows = cursor.fetchmany(100)
                    if not rows:
                        break
                    for row in rows:
                        raw = row_valid(table, dict(row)) + b'\n'
                        if batch and size + len(raw) > CHUNK_BYTES:
                            flush(table, batch)
                            batch, size = [], 0
                        batch.append(raw)
                        size += len(raw)
                        counts[table] += 1
                        # Only archived exact rows can be considered for pruning.
                        if table in TIMES and str(row[TIMES[table]]) < cutoff and len(candidates[table]) < 200:
                            candidates[table].append({'key': {key: row[key] for key in KEYS[table]},
                                                      'sha256': digest(raw[:-1])})
                flush(table, batch)
    manifest = dict(sec_archive_format=FORMAT, schema=7, captured_at=capture_at,
                    history_days=history_days(), counts=counts, chunks=chunks)
    raw = encoded(manifest)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('sec_archive_manifest_too_large')
    archive_id = digest(raw)
    name = f'sec/manifests/{archive_id}.age'
    path = location(repo, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    ciphertext = encrypt(raw, recipient)
    path.write_bytes(ciphertext)
    labels = [f'hourly/{now:%Y%m%dT%H}', f'daily/{now:%Y%m%d}', f'weekly/{now:%G-W%V}']
    if predeploy:
        labels.append('predeploy/latest')
    entry = dict(path=name, cipher_sha256=digest(ciphertext), captured_at=capture_at,
                 chunks=[part['path'] for part in chunks])
    for label in labels:
        index['entries'][label] = entry
    for kind, limit in (('hourly/', 24), ('daily/', 7), ('weekly/', 4)):
        for label in sorted((label for label in index['entries'] if label.startswith(kind)), reverse=True)[limit:]:
            del index['entries'][label]
    keep = {entry['path'] for entry in index['entries'].values()}
    keep.update(part for entry in index['entries'].values() for part in entry['chunks'])
    # Delete only task-owned files whose resolved paths remain inside this repo.
    for folder in ('chunks', 'manifests'):
        for file in (repo / 'sec' / folder).glob('*.age'):
            relative = file.relative_to(repo).as_posix()
            if relative not in keep:
                location(repo, relative).unlink()
    index['chunks'] = {name: value for name, value in index['chunks'].items() if name in keep}
    index_path.write_bytes(encoded(index))  # Checksums/paths only, never source rows.
    return dict(manifest=manifest, manifest_path=name, manifest_cipher_sha256=digest(ciphertext),
                candidates=candidates, cutoff=cutoff, remote_commit=None)


def restore_archive(repo, manifest_path, identity, url, *, workers_stopped=False):
    """Restore ONLY into empty SEC tables with all application role locks free.

    Portfolio may already have been restored separately. Never alters it or
    queues notifications/jobs; original filing processing states are retained.
    """
    if not workers_stopped:
        raise ValueError('sec_restore_requires_stopped_workers')
    repo = Path(repo)
    manifest = json.loads(decrypt(location(repo, manifest_path), identity, MAX_MANIFEST_BYTES))
    if manifest.get('sec_archive_format') != FORMAT or manifest.get('schema') != 7:
        raise ValueError('unsupported_sec_archive_format')
    if set(manifest.get('counts', {})) != set(TABLES) or len(manifest.get('chunks', [])) > MAX_CHUNKS:
        raise ValueError('sec_archive_manifest_invalid')
    seen, counts = set(), {table: 0 for table in TABLES}
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        assert_sec_schema7(conn)
        from cloud_runtime import ROLE_KEYS
        for role in ROLE_KEYS.values():
            if not conn.execute('SELECT pg_try_advisory_xact_lock(719322,%s) ok', (role,)).fetchone()['ok']:
                raise ValueError('sec_restore_workers_running')
        conn.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(
            sql.SQL(',').join(map(sql.Identifier, TABLES))))
        if any(conn.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(table))).fetchone() for table in TABLES):
            raise ValueError('sec_restore_destination_not_empty')
        for part in manifest['chunks']:
            table = part['table']
            if table not in TABLES or part['path'] in seen or not 0 < part['bytes'] <= CHUNK_BYTES + MAX_ROW_BYTES:
                raise ValueError('sec_archive_chunk_invalid')
            seen.add(part['path'])
            file = location(repo, part['path'])
            if digest(file.read_bytes()) != part['cipher_sha256']:
                raise ValueError('sec_archive_cipher_checksum')
            raw = decrypt(file, identity, CHUNK_BYTES + MAX_ROW_BYTES)
            rows = raw.splitlines()
            if len(rows) != part['rows'] or len(raw) != part['bytes'] or digest(raw) != part['sha256']:
                raise ValueError('sec_archive_chunk_checksum')
            for line in rows:
                row = json.loads(line)
                row_valid(table, row)
                keys = sorted(row)
                conn.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),
                    sql.SQL(',').join(map(sql.Identifier, keys)),
                    sql.SQL(',').join(sql.Placeholder() for _ in keys)), [row[key] for key in keys])
                counts[table] += 1
        if counts != manifest['counts']:
            raise ValueError('sec_archive_count_mismatch')
        missing = conn.execute('''SELECT 1 FROM si_decisions d WHERE d.sec_snapshot_id IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM si_company_snapshots s WHERE s.id=d.sec_snapshot_id) LIMIT 1''').fetchone()
        if missing:
            raise ValueError('sec_archive_snapshot_reference_missing')
    return {'sec_archive_format': FORMAT, 'counts': counts, 'captured_at': manifest['captured_at']}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Restore a trusted encrypted SEC companion into empty SEC tables')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--database-url-file', required=True)
    parser.add_argument('--workers-stopped', action='store_true')
    args = parser.parse_args()
    result = restore_archive(args.repo, args.manifest, args.identity,
                             Path(args.database_url_file).read_text().strip(), workers_stopped=args.workers_stopped)
    print(json.dumps(result))  # Only format, counts and capture time.
