"""Bounded archive-first cleanup. Never changes paper orders/accounting.

Only exact rows in an off-server-confirmed SEC companion can be removed.
Current decisions, active trade/hold dependencies and discovery checkpoints
are protected. The compatibility bridge does not invoke this module.
"""
import json
import re
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import sec_history as history
from sec_schema7_compat import assert_sec_schema7


def _active_snapshot_ids(conn):
    rows = conn.execute('''SELECT s.technical_json FROM scanner_signals s WHERE
        EXISTS(SELECT 1 FROM scanner_trades t WHERE t.signal_id=s.id AND t.status='open')
        OR EXISTS(SELECT 1 FROM scanner_orders o WHERE o.signal_id=s.id
                  AND o.status IN ('pending','recovery_uncertain'))''').fetchall()
    ids = set()
    for row in rows:
        technical = json.loads(row['technical_json'] or '{}')
        identifier = technical.get('sec_snapshot_id') or (technical.get('sec_intelligence') or {}).get('snapshot_id')
        if identifier:
            ids.add(identifier)
    return ids


def _protected(conn, table, row, active_ids):
    if table == 'si_decisions':
        return bool(conn.execute('''SELECT 1 FROM scanner_signals s WHERE s.scan_id=%s AND s.ticker=%s
            AND (EXISTS(SELECT 1 FROM scanner_trades t WHERE t.signal_id=s.id AND t.status='open')
            OR EXISTS(SELECT 1 FROM scanner_orders o WHERE o.signal_id=s.id
                      AND o.status IN ('pending','recovery_uncertain'))) LIMIT 1''',
            (row['scan_id'], row['ticker'])).fetchone())
    if table == 'si_company_snapshots':
        if row['id'] in active_ids:
            return True
        return bool(conn.execute('SELECT 1 FROM si_decisions WHERE sec_snapshot_id=%s LIMIT 1', (row['id'],)).fetchone())
    if table == 'si_transactions':
        return bool(conn.execute('SELECT 1 FROM si_company_snapshots WHERE evidence_ids_json::jsonb ? %s LIMIT 1',
                                 (row['event_id'],)).fetchone())
    if table == 'si_filing_jobs':
        if row['status'] not in ('processed', 'unsupported'):
            return True
        if conn.execute('SELECT 1 FROM si_transactions WHERE accession=%s LIMIT 1', (row['accession'],)).fetchone():
            return True
        # Conservatively retain amendment links and snapshot facts (including
        # source accessions) rather than infer that a substring is irrelevant.
        if conn.execute('SELECT 1 FROM si_filing_jobs WHERE superseded_by=%s LIMIT 1', (row['accession'],)).fetchone():
            return True
        if row['superseded_by'] and conn.execute('SELECT 1 FROM si_filing_jobs WHERE accession=%s', (row['superseded_by'],)).fetchone():
            return True
        return bool(conn.execute('SELECT 1 FROM si_company_snapshots WHERE evidence_json::jsonb @> %s::jsonb LIMIT 1',
                                 (json.dumps({'facts': [{'accession': row['accession']}]}),)).fetchone())
    if table == 'si_universe_snapshots':
        latest = conn.execute('SELECT id FROM si_universe_snapshots ORDER BY observed_at DESC,id DESC LIMIT 1').fetchone()
        if latest and latest['id'] == row['id']:
            return True
        return bool(conn.execute('''SELECT 1 FROM si_filing_jobs WHERE universe_snapshot_id=%s
            UNION ALL SELECT 1 FROM si_company_snapshots WHERE universe_snapshot_id=%s LIMIT 1''',
            (row['id'], row['id'])).fetchone())
    return True  # Checkpoints always survive; unknown tables fail closed.


def prune_archived(url, repo, proof):
    commit = proof.get('remote_commit')
    if not re.fullmatch(r'[a-f0-9]{40}', commit or ''):
        raise ValueError('sec_retention_requires_verified_remote_archive')
    # Verify the exact encrypted manifest was in the confirmed Git commit,
    # before opening a write transaction. No remote I/O or decryption here.
    blob = subprocess.run(['git', 'show', commit + ':' + proof['manifest_path']], cwd=Path(repo),
                          check=True, capture_output=True, timeout=30).stdout
    if history.digest(blob) != proof['manifest_cipher_sha256']:
        raise ValueError('sec_retention_archive_commit_mismatch')
    counts = {table: 0 for table in history.TABLES}
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SET LOCAL lock_timeout='1s'")
        conn.execute("SET LOCAL statement_timeout='5000'")
        assert_sec_schema7(conn)
        # Avoid racing new SEC references; never acquire locks on price/order
        # tables or wait indefinitely behind a slow collector.
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE NOWAIT').format(
            sql.SQL(',').join(map(sql.Identifier, history.TABLES))))
        active_ids = _active_snapshot_ids(conn)
        for table in ('si_decisions', 'si_company_snapshots', 'si_transactions',
                      'si_filing_jobs', 'si_universe_snapshots'):
            for candidate in proof['candidates'].get(table, [])[:200]:
                keys = candidate['key']
                if set(keys) != set(history.KEYS[table]):
                    raise ValueError('sec_retention_key_invalid')
                where = sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in keys)
                row = conn.execute(sql.SQL('SELECT * FROM {} WHERE ').format(sql.Identifier(table)) + where,
                                   tuple(keys.values())).fetchone()
                if not row or history.digest(history.row_valid(table, dict(row))) != candidate['sha256']:
                    continue  # A concurrent update was NOT included in this archive.
                if row[history.TIMES[table]] >= proof['cutoff'] or _protected(conn, table, row, active_ids):
                    continue
                conn.execute(sql.SQL('DELETE FROM {} WHERE ').format(sql.Identifier(table)) + where,
                             tuple(keys.values()))
                counts[table] += 1
    return {'history_days': history.history_days(), 'deleted': counts,
            'archive_commit': commit, 'checkpoints_preserved': True}
