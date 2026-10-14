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


def test_canonical_providers_survive_evidence_leases_and_keep_actual_times(pg):
    now=datetime.now(timezone.utc).isoformat()
    with database.get_db_connection() as c:
        c.execute("UPDATE ne_control SET mode='canonical' WHERE id=1")
        for i in range(120):
            c.execute('INSERT INTO ne_provider_state VALUES(?,?)',(f'evidence:{i:04}',json.dumps({'status':'degraded','secret':'DO-NOT-EXPOSE'})))
        c.execute('INSERT INTO ne_provider_state VALUES(?,?)',('globenewswire',json.dumps({'status':'requires_configuration','last_success':now,'last_attempt':now,'error':'http_error','http_status':403,'secret':'DO-NOT-EXPOSE'})))
        c.execute('INSERT INTO ne_provider_state VALUES(?,?)',('prnewswire',json.dumps({'status':'ok','last_success':now,'last_attempt':now})))
    ops._cached=None
    value=ops.payload()
    feed=next(n for n in value['nodes'] if n['id']=='news_feed')
    providers={p['id']:p for p in feed['providers']}
    assert set(providers)=={'globenewswire','prnewswire'}
    assert providers['globenewswire']['http_status']==403
    assert providers['globenewswire']['error_code']=='http_error'
    assert providers['prnewswire']['last_success_at'] is not None
    assert feed['metrics']['provider_issues']==1
    assert 'DO-NOT-EXPOSE' not in json.dumps(value) and 'evidence:0000' not in json.dumps(value)
    ops._cached=None
