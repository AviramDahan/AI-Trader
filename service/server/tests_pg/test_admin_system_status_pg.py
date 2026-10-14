"""Actual PostgreSQL read-only snapshot and advisory ownership, test schemas only."""
import json
from datetime import datetime, timezone

import pytest
import psycopg
import database
import admin_system_status as ops


def test_readonly_projection_does_not_create_jobs_or_trades(pg, monkeypatch):
    ops._cached = None
    roles = psycopg.connect(pg, autocommit=True)
    try:
        for key in (11,12,13):
            roles.execute('SELECT pg_advisory_lock(719322,%s)', (key,))
        tables = ('scanner_signals','scanner_orders','scanner_trades','scanner_fills','admin_alerts','scanner_telegram_outbox','ai_call_usage')
        with database.get_db_connection() as c:
            c.execute('INSERT INTO scanner_settings VALUES(?,?,?)', ('news_canonical_health',json.dumps({
                'checked_at':datetime.now(timezone.utc).isoformat(),'queue_size':0,'oldest_queue_seconds':0,
                'alarms':[],'outcomes':{'large_private_history':'X'*1100000}}),datetime.now(timezone.utc).isoformat()))
            before = {t:c.execute('SELECT COUNT(*) n FROM '+t).fetchone()['n'] for t in tables}
        value = ops.payload()
        assert value['read_only'] and value['version'] == 1
        monitor = next(n for n in value['nodes'] if n['id']=='monitor')
        assert monitor['lease_holders'] == 1 and monitor['state'] == 'unknown'
        assert next(n for n in value['nodes'] if n['id']=='database')['metrics']['schema'] == 7
        assert next(n for n in value['nodes'] if n['id']=='news_feed')['metrics']['queue'] == 0
        assert 'large_private_history' not in json.dumps(value) and len(json.dumps(value)) < 15000
        with database.get_db_connection() as c:
            after = {t:c.execute('SELECT COUNT(*) n FROM '+t).fetchone()['n'] for t in tables}
            assert before == after
        with database.get_db_connection() as c:
            c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            with pytest.raises(Exception):
                c.execute("INSERT INTO scanner_settings VALUES('forbidden','{}','2026-10-14')")
    finally:
        roles.close()
        ops._cached = None
