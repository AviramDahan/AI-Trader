"""Bounded accounting observation inside the API container; never initializes it.

Run with service/server on PYTHONPATH. Output contains evidence states/counts,
not account amounts, raw fills, imported credentials or historical prompts.
"""
import argparse
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from accounting_audit import reconcile


def collect(conn, *, opening_snapshot=None):
    """Caller owns connection lifecycle; every query shares one read-only snapshot."""
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='5s'")
    conn.execute("SET LOCAL lock_timeout='2s'")
    if conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on':
        raise RuntimeError('accounting_audit_requires_read_only')
    if conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read':
        raise RuntimeError('accounting_audit_requires_repeatable_read')
    raw = conn.execute("SELECT value_json FROM scanner_settings WHERE key='active_snapshot_baseline'").fetchone()
    try:
        baseline = json.loads(raw['value_json']) if raw else None
        if raw and baseline is None:
            baseline = {}  # Present-but-invalid must not mean absent/full history.
    except (TypeError, ValueError):
        baseline = {}
    accounts = [dict(r) for r in conn.execute('SELECT * FROM scanner_accounts ORDER BY agent_id LIMIT 11')]
    trades = [dict(r) for r in conn.execute('SELECT * FROM scanner_trades ORDER BY id LIMIT 501')]
    fills = [dict(r) for r in conn.execute(
        'SELECT trade_id,fill_type,price,quantity,fee,gross_pnl FROM scanner_fills ORDER BY id LIMIT 10001')]
    clipped = len(accounts) > 10 or len(trades) > 500 or len(fills) > 10000
    grouped = {}
    for fill in fills[:10000]:
        grouped.setdefault(fill['trade_id'], []).append(fill)
    out = dict(at=datetime.now(timezone.utc).isoformat(), build=os.getenv('BUILD_SHA'),
               transaction_read_only=True, transaction_isolation='repeatable read',
               input_truncated=clipped, opening_baseline_present=raw is not None,
               accounting=reconcile(accounts[:10], trades[:500], grouped,
                                    baseline=baseline, complete=not clipped,
                                    opening_snapshot=opening_snapshot))
    out['orders'] = [dict(r) for r in conn.execute(
        'SELECT purpose,status,count(*) n FROM scanner_orders GROUP BY purpose,status LIMIT 100')]
    out['signals'] = [dict(r) for r in conn.execute(
        'SELECT action,status,legacy_unverified,count(*) n FROM scanner_signals '
        'GROUP BY action,status,legacy_unverified LIMIT 100')]
    out['duplicate_fills'] = conn.execute(
        'SELECT count(*) n FROM (SELECT event_key FROM scanner_fills '
        'GROUP BY event_key HAVING count(*)>1) q').fetchone()['n']
    out['leases'] = [dict(r) for r in conn.execute(
        "SELECT objid,count(*) n FROM pg_locks WHERE locktype='advisory' "
        "AND classid=719322 AND granted GROUP BY objid LIMIT 10")]
    row = conn.execute("SELECT status,last_attempt_at,last_success_at FROM scanner_service_status "
                       "WHERE component='monitor'").fetchone()
    out['monitor'] = dict(row) if row else {'status': 'NOT_VERIFIED'}
    # This accounting observation cannot prove a new natural trade or live TP/SL.
    # Do not execute the older unbounded all-history chain observer here.
    out['natural_trading_e2e'] = 'NOT_VERIFIED'
    if out['duplicate_fills']:
        out['accounting']['status'] = 'FAIL'
        out['accounting']['reason'] = 'DUPLICATE_FILL_KEYS'
    return out


def read_opening_snapshot(path, identity):
    """Decrypt only the explicitly selected existing original; RAM-only and bounded.

    The supplied key and ciphertext are never returned or printed. Authentication
    against the live pinned import ID happens in reconcile(), not by filename.
    """
    maximum = 16 * 1024 * 1024
    path, identity = Path(path), Path(identity)
    if path.stat().st_size > maximum or identity.stat().st_size > 65536:
        raise ValueError('opening_snapshot_input_too_large')
    # Output to a RAM pipe, not a tempfile. The output cannot exceed the selected
    # age ciphertext size; a second explicit limit protects against a bad tool.
    with subprocess.Popen(['age', '-d', '-i', str(identity), str(path)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        with ThreadPoolExecutor(max_workers=1) as reader:
            try:
                raw = reader.submit(process.stdout.read, maximum + 1).result(timeout=20)
                if len(raw) > maximum:
                    raise ValueError('opening_snapshot_input_too_large')
                if process.wait(timeout=5) != 0:
                    raise ValueError('opening_snapshot_decryption_failed')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
            raw = compressed.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('opening_snapshot_decompressed_too_large')
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opening-snapshot', help='Existing original encrypted cutover snapshot; no new backup')
    parser.add_argument('--identity', help='Existing protected age identity; never exported')
    args = parser.parse_args()
    if bool(args.opening_snapshot) != bool(args.identity):
        parser.error('--opening-snapshot and --identity must be supplied together')
    opening, opening_error = None, False
    if args.opening_snapshot:
        try:
            opening = read_opening_snapshot(args.opening_snapshot, args.identity)
        except (OSError, ValueError, TypeError, TimeoutError, subprocess.SubprocessError):
            opening_error = True
    from database import get_db_connection
    with get_db_connection() as conn:
        result = collect(conn, opening_snapshot=opening)
    if opening_error:
        result['opening_snapshot_input'] = 'NOT_VERIFIED'
        result['opening_snapshot_input_reason'] = 'DECRYPTION_OR_INPUT_FAILED'
    print(json.dumps(result, default=str, allow_nan=False))


if __name__ == '__main__':
    main()
