"""Real PostgreSQL same-snapshot cadence proof; disposable test_* schemas only."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_news_feed_cadence_status import NOW, FUTURE, current_health
import admin_system_status as ops
import database


@pytest.mark.parametrize('case', ['scheduled', 'legacy_error', 'legacy_due',
    'canonical_error', 'canonical_rate_limit', 'canonical_missing_due',
    'unknown_error', 'alarm', 'missing_lease', 'fractional_queue', 'missing_funnel'])
def test_actual_pg_projection_cadence_and_fail_closed_boundaries(pg, case):
    canonical = {'status': 'ok', 'last_attempt': NOW.isoformat(),
                 'last_success': NOW.isoformat(), 'next_at': FUTURE}
    if case == 'canonical_error': canonical['status'] = 'error'
    if case == 'canonical_rate_limit': canonical['http_status'] = 429
    if case == 'canonical_missing_due': canonical.pop('next_at')
    if case == 'unknown_error': canonical['error'] = 'PRIVATE_UNKNOWN_FIXTURE_ERROR'
    health = current_health()
    if case == 'missing_funnel': health.pop('funnel')
    if case == 'alarm': health['alarms'] = ['synthetic_alarm']
    if case == 'fractional_queue': health['queue_size'] = 0.5
    tables = ('scanner_signals', 'scanner_orders', 'scanner_trades', 'scanner_fills',
              'scanner_telegram_outbox', 'admin_alerts', 'ai_call_usage')
    with database.get_db_connection() as c:
        c.execute("UPDATE ne_control SET mode='canonical' WHERE id=1")
        c.execute('INSERT INTO ne_provider_state(provider_id,state_json) VALUES(?,?)',
                  ('prnewswire', json.dumps(canonical)))
        c.execute('''INSERT INTO scanner_news_providers
            (provider,status,last_success_at,next_check_at,cadence_seconds,coverage,error)
            VALUES('prnewswire','ok',?,?,900,'fixture',?)''',
            (NOW.isoformat(), NOW.isoformat() if case == 'legacy_due' else FUTURE,
             'PRIVATE_LEGACY_FIXTURE_ERROR' if case == 'legacy_error' else None))
        c.execute('''INSERT INTO scanner_service_status
            (component,status,last_attempt_at,last_success_at,detail)
            VALUES('news_feed','backoff',?,?,'checked=0 inserted=0 errors=')''',
            (NOW.isoformat(), NOW.isoformat()))
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
                  ('news_canonical_health', json.dumps(health), NOW.isoformat()))
        before = {t: c.execute('SELECT COUNT(*) n FROM '+t).fetchone()['n'] for t in tables}
    with database.get_db_connection() as c:
        for role in (12, 13) if case == 'missing_lease' else (11, 12, 13):
            c.execute('SELECT pg_advisory_lock(719322,?)', (role,))
        c.commit()
        c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        assert c.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        value = ops.build(c, NOW)
        after = {t: c.execute('SELECT COUNT(*) n FROM '+t).fetchone()['n'] for t in tables}
        assert before == after
    node = next(n for n in value['nodes'] if n['id'] == 'news_feed')
    if case == 'scheduled':
        assert (node['state'], node['reason']) == ('idle', 'scheduled_wait')
    else:
        assert node['state'] != 'idle'
    if case == 'missing_lease':
        assert (node['state'], node['reason']) == ('failed', 'lease_missing')
    if case == 'missing_funnel':
        assert (node['state'], node['reason']) == ('unknown','news_funnel_unverified')
        assert node['metrics']['news_events_6h'] is None
    assert 'PRIVATE_UNKNOWN_FIXTURE_ERROR' not in json.dumps(value)
    assert 'PRIVATE_LEGACY_FIXTURE_ERROR' not in json.dumps(value)
    assert value['read_only']
