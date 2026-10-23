"""Synthetic-only cadence projection: no collector, provider, AI or delivery calls."""
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_system_status as ops
import database
from news_events.funnel_health import COUNTS
from test_admin_system_status import isolated, seed

NOW = datetime(2026, 10, 16, 13, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(minutes=5)).isoformat()


def current_health(**changes):
    """No events in this synthetic DB; keep cadence guards independent of recall."""
    value = {'checked_at': NOW.isoformat(), 'queue_size': 0,
             'oldest_queue_seconds': 0, 'alarms': [],
             'funnel': {'version': 1, 'status': 'no_input', 'checked_at': NOW.isoformat(),
                        'window_start': (NOW-timedelta(hours=6)).isoformat(),
                        'window_end': NOW.isoformat(), 'counts': {key: 0 for key in COUNTS},
                        'advisories': []}}
    value.update(changes)
    return value


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class ProjectedPostgres:
    """Only PG metadata syntax is adapted; ordinary build SQL uses real SQLite."""
    def __init__(self, conn, canonical, roles):
        self.conn, self.canonical, self.roles = conn, canonical, roles

    def execute(self, query, args=()):
        if 'FROM pg_locks' in query:
            return Result([{'role_key': k, 'holders': v} for k, v in self.roles.items()])
        if 'jsonb_build_object' in query:
            return self.conn.execute("SELECT value_json FROM scanner_settings WHERE key='news_canonical_health'")
        if 'FROM ne_control' in query:
            return Result([{'mode': 'canonical'}])
        if 'FROM ne_provider_state' in query:
            return Result(self.canonical)
        if 'MAX(version)' in query:
            return Result([{'version': 7}])
        return self.conn.execute(query, args)


def canonical_provider(name='prnewswire', **changes):
    row = {'provider_id': name, 'status': 'ok', 'last_success_at': NOW.isoformat(),
           'last_attempt_at': NOW.isoformat(), 'next_check_at': FUTURE,
           'error_code': None, 'error_present': 0, 'http_status': None}
    return dict(row, **changes)


@pytest.fixture
def snapshot(isolated, monkeypatch):
    def no_network(*a, **kw):
        raise AssertionError('No real network permitted in cadence projection tests')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    monkeypatch.setattr(socket, 'create_connection', no_network)
    with isolated() as conn:
        seed(conn, {'enabled': True, 'status': 'ready', 'last_check_at': NOW.isoformat(), 'active': False})
        conn.execute("UPDATE scanner_service_status SET last_attempt_at=?,last_success_at=?",
                     (NOW.isoformat(), NOW.isoformat()))
        conn.execute("UPDATE scanner_settings SET value_json=? WHERE key='ai_cost_reconciliation'",
                     (json.dumps({'checked_at': NOW.isoformat(), 'remaining': 20, 'credit_balance': 2}),))
        conn.execute("UPDATE scanner_service_status SET status='backoff',detail='checked=0 inserted=0 errors=' WHERE component='news_feed'")
        conn.execute("INSERT INTO scanner_settings VALUES(?,?,?)", ('news_canonical_health',
            json.dumps(current_health()), NOW.isoformat()))
        conn.execute("""INSERT INTO scanner_news_providers
            (provider,status,last_success_at,next_check_at,cadence_seconds,coverage)
            VALUES('investing','ok',?,?,900,'fixture')""", (NOW.isoformat(), FUTURE))

    def run(*, legacy=None, canonical=None, health=None, service=None, roles=None, missing_funnel=False):
        with isolated() as conn:
            if legacy is not None:
                conn.execute('DELETE FROM scanner_news_providers')
                for row in legacy:
                    conn.execute("""INSERT INTO scanner_news_providers
                        (provider,status,last_success_at,next_check_at,cadence_seconds,coverage,error)
                        VALUES(?,?,?,?,900,'fixture',?)""",
                        (row.get('provider', 'investing'), row.get('status', 'ok'),
                         NOW.isoformat(), row.get('next_check_at', FUTURE), row.get('error')))
            if health is not None or missing_funnel:
                effective = current_health(**(health or {}))
                if missing_funnel:
                    effective.pop('funnel')
                conn.execute("UPDATE scanner_settings SET value_json=? WHERE key='news_canonical_health'", (json.dumps(effective),))
            if service:
                for field, value in service.items():
                    assert field in {'status', 'detail', 'last_attempt_at'}
                    conn.execute('UPDATE scanner_service_status SET '+field+"=? WHERE component='news_feed'", (value,))
        monkeypatch.setattr(ops, 'using_postgres', lambda: True)
        with isolated() as conn:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            db = ProjectedPostgres(conn, [canonical_provider()] if canonical is None else canonical,
                                   {11: 1, 12: 1, 13: 1} if roles is None else roles)
            result = ops.build(db, NOW)
        node = next(n for n in result['nodes'] if n['id'] == 'news_feed')
        return node, result
    return run


def test_normal_future_cadence_is_idle_not_retry_failure(snapshot):
    node, result = snapshot()
    assert (node['state'], node['reason']) == ('idle', 'scheduled_wait')
    assert node['lease_holders'] == 1
    assert result['overall'] == 'observed_operational'


def test_cadence_without_funnel_evidence_is_unknown_not_success(snapshot):
    node, _ = snapshot(missing_funnel=True)
    assert (node['state'], node['reason']) == ('unknown','news_funnel_unverified')
    assert node['metrics']['news_events_6h'] is None
    assert node['metrics']['news_funnel_review_required'] is None


@pytest.mark.parametrize('status', ['error', 'rate_limited', 'degraded', 'requires_configuration', 'unknown'])
def test_actual_or_unknown_legacy_issue_is_not_scheduled_idle(snapshot, status):
    node, _ = snapshot(legacy=[{'status': status}])
    assert node['state'] != 'idle'


def test_explicit_component_error_has_failure_precedence(snapshot):
    node, _ = snapshot(service={'status': 'error'})
    assert (node['state'], node['reason']) == ('failed', 'reported_error')


@pytest.mark.parametrize('due', [None, '', 'invalid', '2026-10-16T13:05:00',
    NOW.isoformat(), (NOW-timedelta(seconds=1)).isoformat()])
def test_legacy_missing_invalid_or_due_now_is_not_idle(snapshot, due):
    # NOT NULL is a storage guard; empty and malformed strings model missing
    # retained timestamps without weakening the database fixture schema.
    node, _ = snapshot(legacy=[{'next_check_at': '' if due is None else due}])
    assert node['state'] != 'idle'


@pytest.mark.parametrize('changes', [
    {'status': 'rate_limited'}, {'status': 'error'}, {'status': 'unknown'},
    {'next_check_at': None}, {'next_check_at': 'invalid'}, {'next_check_at': NOW.isoformat()},
    {'error_present': 1, 'error_code': 'unallowlisted-private-error'},
    {'http_status': 403}, {'http_status': 429}, {'http_status': 'invalid'},
])
def test_canonical_issues_not_hidden_by_projection(snapshot, changes):
    node, result = snapshot(canonical=[canonical_provider(**changes)])
    assert node['state'] != 'idle'
    assert 'unallowlisted-private-error' not in json.dumps(result)


def test_canonical_merge_does_not_hide_legacy_error_or_due(snapshot):
    node, _ = snapshot(legacy=[{'provider': 'prnewswire', 'status': 'error'}])
    assert node['providers'][0]['status'] == 'ok'  # Original UI merge, not proof.
    assert node['state'] != 'idle'


def test_unallowlisted_legacy_error_presence_blocks_without_leaking(snapshot):
    node, result = snapshot(legacy=[{'error': 'PRIVATE_UNCLASSIFIED_ERROR'}])
    assert node['state'] != 'idle'
    assert 'PRIVATE_UNCLASSIFIED_ERROR' not in json.dumps(result)


@pytest.mark.parametrize('detail', ['checked=0 inserted=0 errors=scanner_bridge:RuntimeError',
    'checked=1 inserted=0 errors=', 'checked=0 inserted=1 errors=', '', None,
    'checked=0 inserted=0 errors=\n'])
def test_only_exact_no_work_no_error_summary_qualifies(snapshot, detail):
    node, _ = snapshot(service={'detail': detail})
    assert node['state'] != 'idle'


@pytest.mark.parametrize('stamp,expected', [
    ((NOW-timedelta(seconds=901)).isoformat(), 'stale'),
    ((NOW+timedelta(seconds=1)).isoformat(), 'degraded'),
    ((NOW+timedelta(minutes=1)).isoformat(), 'unknown'),
    (None, 'unknown'), ('invalid', 'unknown'),
])
def test_stale_future_missing_service_observation_not_idle(snapshot, stamp, expected):
    node, _ = snapshot(service={'last_attempt_at': stamp})
    assert node['state'] == expected


@pytest.mark.parametrize('changes', [
    {'checked_at': None}, {'checked_at': 'invalid'},
    {'checked_at': (NOW-timedelta(seconds=181)).isoformat()},
    {'checked_at': (NOW+timedelta(seconds=1)).isoformat()},
    {'alarms': ['synthetic_alarm']}, {'alarms': None}, {'alarms': {}},
    {'queue_size': 1}, {'queue_size': None}, {'queue_size': True}, {'queue_size': 0.5},
    {'queue_size': -0.5}, {'queue_size': '0'}, {'queue_size': 'NaN'}, {'queue_size': 'Infinity'},
    {'oldest_queue_seconds': None}, {'oldest_queue_seconds': 20}, {'oldest_queue_seconds': 0.5},
])
def test_unknown_stale_alarms_or_queue_not_cadence_proof(snapshot, changes):
    health = dict(checked_at=NOW.isoformat(), queue_size=0, oldest_queue_seconds=0, alarms=[])
    health.update(changes)
    node, _ = snapshot(health=health)
    assert node['state'] != 'idle'


@pytest.mark.parametrize('roles,reason', [
    ({12: 1, 13: 1}, 'lease_missing'),
    ({11: 2, 12: 1, 13: 1}, 'duplicate_role_lease'),
])
def test_lease_failure_keeps_precedence(snapshot, roles, reason):
    node, _ = snapshot(roles=roles)
    assert (node['state'], node['reason']) == ('failed', reason)


@pytest.mark.parametrize('legacy,canonical', [
    ([], [canonical_provider()]), ([{'status': 'ok'}], []),
    ([{'status': 'retired'}], [canonical_provider(status='disabled')]),
    ([{'provider': 'unknown-source'}], [canonical_provider()]),
])
def test_missing_or_no_active_or_unknown_provider_not_idle(snapshot, legacy, canonical):
    node, _ = snapshot(legacy=legacy, canonical=canonical)
    assert node['state'] != 'idle'


def test_disabled_and_retired_sources_are_not_called_failures(snapshot):
    node, _ = snapshot(legacy=[{'status': 'ok'}, {'provider': 'globenewswire',
        'status': 'disabled', 'next_check_at': '', 'error': 'old_disabled_error'}],
        canonical=[canonical_provider(), canonical_provider('ftc', status='retired', next_check_at=None)])
    assert (node['state'], node['reason']) == ('idle', 'scheduled_wait')


@pytest.mark.parametrize('source', ['legacy', 'canonical'])
def test_truncation_sentinel_refuses_cadence_even_when_every_returned_row_looks_good(source):
    node = {'state': 'degraded', 'reason': 'retry_backoff', 'lease_holders': 1}
    row = {'detail': 'checked=0 inserted=0 errors=', 'last_attempt_at': NOW.isoformat()}
    health = {'checked_at': NOW.isoformat(), 'queue_size': 0, 'oldest_queue_seconds': 0, 'alarms': []}
    legacy = [{'provider': 'investing', 'status': 'ok', 'next_check_at': FUTURE, 'error_present': 0}]
    canonical = [canonical_provider()]
    assert ops.scheduled_feed_wait(node, row, legacy, canonical, health, NOW)
    if source == 'legacy': legacy *= 65
    else: canonical *= 65
    assert not ops.scheduled_feed_wait(node, row, legacy, canonical, health, NOW)


def test_projection_does_not_write_or_start_work(snapshot):
    node, result = snapshot()
    assert result['read_only'] and node['state'] == 'idle'
    # Fixture connections used query_only for the actual projection; any write
    # raises. There is no collector invocation or network path in this harness.
    assert node['metrics']['queue'] == 0 and node['metrics']['provider_issues'] == 0
