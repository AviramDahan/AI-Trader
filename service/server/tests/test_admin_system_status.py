"""Private read-only monitoring: synthetic records, no live Telegram/AI calls."""
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import admin_system_status as ops
import telegram_admin_access as access

NOW = datetime(2026, 10, 14, 15, tzinfo=timezone.utc)


def signed(bot='fixture-bot', uid=42, now=None, extra=None):
    fields = {'auth_date':str(int(time.time() if now is None else now)), 'user':json.dumps({'id':uid}), 'start_param':'operations'}
    fields.update(extra or {})
    secret = hmac.new(b'WebAppData', bot.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, '\n'.join(f'{k}={fields[k]}' for k in sorted(fields)).encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path / 'ops.db'))
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.delenv('AI_TRADER_CLOUD', raising=False)
    database.init_database()
    with database.get_db_connection() as conn:
        # The private ops tables are normally installed by the cloud migrations.
        conn.execute('CREATE TABLE admin_alerts(dedupe_key TEXT PRIMARY KEY,status TEXT,created_at TEXT)')
        conn.execute('CREATE TABLE ai_call_usage(call_id TEXT PRIMARY KEY,task TEXT,timestamp TEXT)')
    ops._cached = None
    access._members.clear()
    return database.get_db_connection


def test_signed_telegram_user_is_not_the_launch_hint():
    assert access.verified_user(signed(now=NOW.timestamp()), 'fixture-bot', NOW.timestamp()) == 42
    with pytest.raises(HTTPException) as e:
        access.verified_user('tgWebAppStartParam=operations&user=42', 'fixture-bot', NOW.timestamp())
    assert e.value.status_code == 401


@pytest.mark.parametrize('raw,bot', [
    (signed(now=NOW.timestamp()) + '&auth_date=1', 'fixture-bot'),
    (signed(now=NOW.timestamp()).replace('operations','private'), 'fixture-bot'),
    (signed(now=NOW.timestamp()), 'different-bot'),
    (signed(now=NOW.timestamp()-3601), 'fixture-bot'),
    (signed(now=NOW.timestamp()+31), 'fixture-bot'),
    (signed(now=NOW.timestamp(), uid=True), 'fixture-bot'),
    (signed(now=NOW.timestamp(), uid=-1), 'fixture-bot'),
    ('x'*8193, 'fixture-bot'),
    (signed(now=NOW.timestamp(), extra={'user':'{"id":42,"id":43}'}), 'fixture-bot'),
])
def test_bad_auth_fail_closed(raw, bot):
    with pytest.raises(HTTPException) as error:
        access.verified_user(raw, bot, NOW.timestamp())
    assert error.value.status_code == 401
    assert 'fixture-bot' not in str(error.value.detail)


def membership(monkeypatch, status='member', user=42, body=None):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'fixture-bot')
    monkeypatch.setenv('TELEGRAM_ADMIN_BOT_TOKEN', 'fixture-admin-bot')
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID', '-123456')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-987654')
    access._members.clear()
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.iter_content.return_value = [json.dumps(body or {'ok':True,'result':{'status':status, 'user':{'id':user}}}).encode()]
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response
    monkeypatch.setattr(access.requests, 'Session', MagicMock(return_value=session))
    return session, response


def test_private_membership_bounded_cache_and_exact_identity(monkeypatch):
    session, _ = membership(monkeypatch)
    access.require_logs_member(signed())
    access.require_logs_member(signed())
    assert session.get.call_count == 1
    assert session.trust_env is False
    assert session.get.call_args.kwargs['allow_redirects'] is False
    assert session.get.call_args.kwargs['params'] == {'chat_id':'-123456','user_id':42}
    assert session.get.call_args.args[0].endswith('/getChatMember')
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID','-55555')
    access.require_logs_member(signed())
    assert session.get.call_count == 2


def test_existing_main_bot_can_authorize_private_logs_without_new_credentials(monkeypatch):
    session, _ = membership(monkeypatch)
    monkeypatch.delenv('TELEGRAM_ADMIN_BOT_TOKEN')
    access.require_logs_member(signed())
    assert session.get.call_args.args[0] == 'https://api.telegram.org/botfixture-bot/getChatMember'


@pytest.mark.parametrize('status,uid,expected', [('left',42,403),('kicked',42,403),('member',43,503),('member',42.0,503),('restricted',42,403)])
def test_nonmembers_and_wrong_provider_identity_denied(monkeypatch, status, uid, expected):
    membership(monkeypatch, status, uid)
    with pytest.raises(HTTPException) as error:
        access.require_logs_member(signed())
    assert error.value.status_code == expected


def test_membership_network_failure_and_public_group_never_authorize(monkeypatch):
    session, response = membership(monkeypatch)
    response.status_code = 429
    with pytest.raises(HTTPException) as error:
        access.require_logs_member(signed())
    assert error.value.status_code == 503
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID','-987654')
    before = session.get.call_count
    with pytest.raises(HTTPException) as error:
        access.require_logs_member(signed())
    assert error.value.status_code == 503 and session.get.call_count == before


def test_component_missing_stale_future_error_and_idle():
    assert ops.component('monitor', {}, NOW)['state'] == 'unknown'
    row = {'status':'ok','last_attempt_at':NOW.isoformat(),'last_success_at':NOW.isoformat(),'detail':'secret https://bad.invalid PRIVATE'}
    assert ops.component('monitor', {'monitor':row}, NOW, lease=1)['state'] == 'healthy'
    assert ops.component('monitor', {'monitor':row}, NOW, lease=0)['reason'] == 'lease_missing'
    assert ops.component('monitor', {'monitor':row}, NOW, lease=2)['reason'] == 'duplicate_role_lease'
    for stamp in (None, '2026-10-14T15:00:00', (NOW+timedelta(minutes=1)).isoformat()):
        assert ops.component('monitor', {'monitor':dict(row,last_attempt_at=stamp)}, NOW)['state'] == 'unknown'
    assert ops.component('monitor', {'monitor':dict(row,last_attempt_at=(NOW-timedelta(hours=1)).isoformat())}, NOW)['state'] == 'stale'
    assert ops.component('monitor', {'monitor':dict(row,status='market_closed')}, NOW)['state'] == 'idle'
    for status in ('no_signals','not_modified','no_new'):
        assert ops.component('scan', {'scan':dict(row,status=status)}, NOW)['state'] == 'idle'
    value = ops.component('monitor', {'monitor':dict(row,status='error')}, NOW)
    assert value['state'] == 'failed' and 'secret' not in json.dumps(value) and 'bad.invalid' not in json.dumps(value)


def test_live_scan_phase_and_existing_overdue_grace_do_not_fake_completion():
    node = {'state':'idle','reason':'no_signals'}
    ops.scan_activity(node, {'status':'scanning','last_started_at':NOW.timestamp()-20,'next_scan_at':NOW.timestamp()+1800}, NOW)
    assert node['state'] == 'idle' and node['reason'] == 'scan_in_progress'
    ops.scan_activity(node, {'status':'scanning','last_started_at':NOW.timestamp()-1900,'next_scan_at':NOW.timestamp()-301}, NOW)
    assert node['state'] == 'stale' and node['reason'] == 'scan_schedule_overdue'
    node.update(state='failed',reason='lease_missing')
    ops.scan_activity(node, {'status':'scanning','last_started_at':NOW.timestamp(),'next_scan_at':NOW.timestamp()+1800}, NOW)
    assert node['state'] == 'failed' and node['reason'] == 'lease_missing'


def seed(conn, local=None):
    for key in ops.SERVICE_LIMITS:
        conn.execute('INSERT INTO scanner_service_status VALUES(?,?,?,?,?)', (key,'ok',NOW.isoformat(),NOW.isoformat(),'fixture only'))
    conn.execute('INSERT INTO scanner_settings VALUES(?,?,?)', ('ollama_connectivity_watch_v1',json.dumps(local or {'enabled':True,'status':'ready','last_check_at':NOW.isoformat(),'active':False}),NOW.isoformat()))
    conn.execute('INSERT INTO scanner_settings VALUES(?,?,?)', ('ai_cost_reconciliation',json.dumps({'checked_at':NOW.isoformat(),'remaining':20,'credit_balance':2}),NOW.isoformat()))


def test_snapshot_reads_only_bounded_metadata_and_no_inference(isolated, monkeypatch):
    with isolated() as conn:
        seed(conn)
        conn.execute('''INSERT INTO scanner_news_providers(provider,status,next_check_at,cadence_seconds,coverage)
            VALUES(?,?,?,900,'fixture')''', ('globenewswire','requires_configuration',NOW.isoformat()))
    with isolated() as conn:
        conn.execute('PRAGMA query_only=ON'); conn.execute('BEGIN')
        result = ops.build(conn, NOW)
        with pytest.raises(Exception):
            conn.execute("UPDATE scanner_service_status SET status='error'")
    nodes = {n['id']:n for n in result['nodes']}
    assert nodes['ai_local']['state'] == 'healthy'
    assert nodes['ai_cloud']['state'] == 'idle'
    assert nodes['news_feed']['reason'] == 'partial_provider_coverage'
    assert nodes['news_feed']['metrics']['queue'] is None
    assert nodes['paper']['metrics'] == {'open_positions':0,'pending_orders':0,'holds':0}
    assert nodes['backup']['last_success_at'] == NOW.isoformat()
    assert result['read_only'] and len(result['nodes']) == 13 and result['overall'] == 'attention'
    assert 'fixture only' not in json.dumps(result)
    with isolated() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM scanner_telegram_outbox').fetchone()['n'] == 0
        assert conn.execute('SELECT COUNT(*) n FROM ai_call_usage').fetchone()['n'] == 0


@pytest.mark.parametrize('local,expected', [
    ({'enabled':True,'status':'reachable_not_ready','last_check_at':NOW.isoformat()},'idle'),
    ({'enabled':True,'status':'ready','active':True,'last_check_at':NOW.isoformat()},'degraded'),
    ({'enabled':True,'status':'failed','last_check_at':NOW.isoformat()},'failed'),
    ({'enabled':False},'disabled'),
    ({'enabled':True,'status':'ready','last_check_at':(NOW-timedelta(minutes=10)).isoformat()},'stale'),
])
def test_local_ai_is_on_demand_not_fake_continuous_activity(isolated, local, expected):
    with isolated() as conn: seed(conn, local)
    with isolated() as conn: result = ops.build(conn, NOW)
    assert next(n for n in result['nodes'] if n['id']=='ai_local')['state'] == expected


def test_route_requires_permission_and_never_exposes_exception(isolated, monkeypatch):
    from routes import create_app
    client = TestClient(create_app())
    denied = client.get('/api/admin/system-status')
    assert denied.status_code == 401
    monkeypatch.setattr(access, 'require_logs_member', lambda raw: None)
    monkeypatch.setattr(ops, 'payload', lambda: {'version':1,'read_only':True})
    allowed = client.get('/api/admin/system-status',headers={'X-Telegram-Init-Data':'synthetic'})
    assert allowed.status_code == 200 and allowed.headers['cache-control'] == 'no-store, private'
    assert client.post('/api/admin/system-status').status_code == 405
    def failed(): raise RuntimeError('password fixture-private')
    monkeypatch.setattr(ops, 'payload', failed)
    failure = client.get('/api/admin/system-status',headers={'X-Telegram-Init-Data':'synthetic'})
    assert failure.status_code == 503 and 'password' not in failure.text
