"""Synthetic connectivity episodes; no model, paid requests, workers or messages."""
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_routing
import ollama_connectivity_watch as watch

NOW = datetime(2026, 10, 14, 8, tzinfo=timezone.utc)
BAD = {'status': 'failed', 'reason': 'private_relay_unreachable'}
GOOD = {'status': 'ready', 'reason': None}
BUSY = {'status': 'reachable_not_ready', 'reason': None}


def episode(observations, start=NOW, previous=None):
    changes = []
    for i, observation in enumerate(observations):
        previous, change = watch.advance(previous, observation, start+timedelta(minutes=i))
        if change:
            changes.append(change)
    return previous, changes


def test_failure_debounce_once_recovery_once_and_restart():
    state, changes = episode([BAD]*8)
    assert changes == ['failure'] and state['active'] and state['generation'] == 1
    importlib.reload(watch)
    state, changes = episode([GOOD]*4, NOW+timedelta(minutes=8), state)
    assert changes == ['recovery'] and not state['active']
    state, changes = episode([BAD]*4, NOW+timedelta(minutes=12), state)
    assert changes == ['failure'] and state['generation'] == 2


def test_busy_cold_and_transient_connections_never_report_an_outage():
    assert episode([BUSY]*20)[1] == []
    assert episode([BAD, BAD, GOOD, BAD, GOOD, BUSY, BAD])[1] == []
    state, _ = episode([BAD]*3)
    state, changes = episode([BUSY]*5, NOW+timedelta(minutes=3), state)
    assert state['active'] and changes == []


def test_observer_gap_clock_change_and_disabled_mode_do_not_invent_evidence():
    state, _ = episode([BAD, BAD])
    state, change = watch.advance(state, BAD, NOW+timedelta(hours=2))
    assert change is None and state['failed_checks'] == 1
    state, change = watch.advance(state, BAD, NOW-timedelta(hours=1))
    assert change is None and state['failed_checks'] == 1
    state, _ = episode([BAD]*3)
    paused, change = watch.advance(state, None, NOW+timedelta(minutes=3), False)
    assert paused['active'] and change is None
    resumed, change = watch.advance(paused, GOOD, NOW+timedelta(minutes=4))
    assert resumed['active'] and change is None
    resumed, change = watch.advance(resumed, GOOD, NOW+timedelta(minutes=5))
    assert not resumed['active'] and change == 'recovery'


@pytest.mark.parametrize('value,reason', [
    (None, 'invalid_health_response'),
    ({'protocol': True, 'ready': True, 'capacity': 1}, 'invalid_health_response'),
    ({'protocol': 1, 'ready': True, 'capacity': 1, 'model': 'wrong'}, 'model_identity_mismatch'),
])
def test_untrusted_health_is_allowlisted_without_private_output(monkeypatch, value, reason):
    relay = Mock(return_value=value)
    monkeypatch.setattr(ai_routing, 'relay', relay)
    assert watch.probe() == {'status': 'failed', 'reason': reason}
    relay.assert_called_once_with('GET', '/health', timeout=2)


def test_health_get_does_not_generate_or_modify_routing_cooldown(monkeypatch):
    monkeypatch.setattr(ai_routing, '_until', 12345)
    value = dict(protocol=1, ready=False, capacity=1, model=ai_routing.MODEL, digest=ai_routing.DIGEST)
    monkeypatch.setattr(ai_routing, 'relay', Mock(return_value=value))
    assert watch.probe() == BUSY
    value['ready'] = True
    assert watch.probe() == GOOD
    ai_routing.relay.side_effect = requests.ConnectionError('token=PRIVATE https://private.example')
    assert watch.probe() == BAD and ai_routing._until == 12345
    state, _ = episode([BAD]*3)
    text = watch.message('failure', state)
    assert 'PRIVATE' not in text and 'https://' not in text
    assert 'כאשר הקרדיטים' in text and 'סיבת המחשב לא אומתה' in text
    recovery = watch.message('recovery', state)
    assert 'לא הוכחה להצלחת ניתוח AI' in recovery


@pytest.fixture
def isolated_sqlite(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path/'watch.db'))
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    monkeypatch.setenv('AI_TRADER_ROLE', 'telegram')
    monkeypatch.setenv('AI_INFERENCE_MODE', 'ollama_first')
    with database.get_db_connection() as c:
        c.execute('CREATE TABLE scanner_settings(key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT)')
        c.execute('CREATE TABLE admin_alerts(dedupe_key TEXT PRIMARY KEY,message TEXT,created_at TEXT)')
    return database


def test_persisted_dedupe_restart_sampling_and_private_outbox(isolated_sqlite, monkeypatch):
    db = isolated_sqlite
    probe = Mock(return_value=BAD)
    monkeypatch.setattr(watch, 'probe', probe)
    for i in range(5):
        watch.check(NOW+timedelta(minutes=i))
        watch.check(NOW+timedelta(minutes=i, seconds=20))
    assert probe.call_count == 5
    with db.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM admin_alerts').fetchone()['n'] == 1
    importlib.reload(watch)
    monkeypatch.setattr(watch, 'probe', Mock(return_value=GOOD))
    watch.check(NOW+timedelta(minutes=5)); watch.check(NOW+timedelta(minutes=6))
    with db.get_db_connection() as c:
        rows = c.execute('SELECT * FROM admin_alerts ORDER BY created_at').fetchall()
        assert [r['dedupe_key'] for r in rows] == ['ollama-connectivity:1:failure', 'ollama-connectivity:1:recovery']
        assert all(r['message'].splitlines()[-1].startswith('Timestamp: 14/10/2026 11:') for r in rows)
        state = json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?', (watch.KEY,)).fetchone()['value_json'])
        assert not state['active']
    from telegram_presentation import telegram_text, utf16_length
    assert all(utf16_length(telegram_text(r['message'])) < 4000 for r in rows)


def test_off_local_and_non_observer_roles_never_probe_or_write(monkeypatch):
    monkeypatch.setattr(watch, 'probe', Mock(side_effect=AssertionError('Forbidden probe')))
    monkeypatch.setattr('database.get_db_connection', Mock(side_effect=AssertionError('Forbidden DB')))
    monkeypatch.setenv('AI_TRADER_CLOUD', 'false')
    assert watch.check(NOW) is None
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true'); monkeypatch.setenv('AI_TRADER_ROLE', 'monitor')
    assert watch.check(NOW) is None


def test_cloud_only_does_not_probe_or_claim_recovery(isolated_sqlite, monkeypatch):
    monkeypatch.setenv('AI_INFERENCE_MODE', 'cloud_only')
    monkeypatch.setattr(watch, 'probe', Mock(side_effect=AssertionError('Forbidden probe')))
    assert watch.check(NOW) == {}
    with isolated_sqlite.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM admin_alerts').fetchone()['n'] == 0


def test_deliberate_disable_preserves_incident_until_verified_recovery(isolated_sqlite, monkeypatch):
    monkeypatch.setattr(watch, 'probe', Mock(return_value=BAD))
    for i in range(3):watch.check(NOW+timedelta(minutes=i))
    monkeypatch.setenv('AI_INFERENCE_MODE','cloud_only')
    forbidden=Mock(side_effect=AssertionError('Probe while disabled'))
    monkeypatch.setattr(watch,'probe',forbidden)
    assert watch.check(NOW+timedelta(minutes=3))['active']
    forbidden.assert_not_called()
    with isolated_sqlite.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM admin_alerts').fetchone()['n']==1
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setattr(watch,'probe',Mock(return_value=GOOD))
    assert watch.check(NOW+timedelta(minutes=4))['active']
    assert not watch.check(NOW+timedelta(minutes=5))['active']


def test_observer_exception_cannot_block_existing_admin_delivery(monkeypatch):
    import asyncio
    import ai_operations
    from unittest.mock import MagicMock, AsyncMock
    connection=MagicMock()
    connection.__enter__.return_value.execute.return_value.fetchone.return_value=None
    monkeypatch.setattr('database.get_db_connection',Mock(return_value=connection))
    for name in ('reconcile','enqueue','health'):
        monkeypatch.setattr(ai_operations,name,Mock())
    monkeypatch.setattr(watch,'check',Mock(side_effect=RuntimeError('synthetic probe failure')))
    send=Mock();monkeypatch.setattr(ai_operations,'send_one',send)
    monkeypatch.setattr(ai_operations.asyncio,'sleep',AsyncMock(side_effect=RuntimeError('end-test')))
    with pytest.raises(RuntimeError,match='end-test'):asyncio.run(ai_operations.operations_loop())
    send.assert_called_once()
