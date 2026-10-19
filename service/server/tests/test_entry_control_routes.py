"""Public statistics and logs membership must not grant trading-control writes."""
import sys
import types
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import routes_scanner


@pytest.fixture
def browser(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path/'permissions.db'))
    database.init_database()
    with database.get_db_connection() as c:
        for name, role in [('admin','admin'), ('regular','agent'), ('operator','agent')]:
            c.execute('INSERT INTO agents(name,token,role,cash) VALUES(?,?,?,1000)',
                      (name,'synthetic-'+name,role))
        aid = c.execute("SELECT id FROM agents WHERE name='operator'").fetchone()['id']
        c.execute('INSERT INTO scanner_operators(agent_id) VALUES(?)', (aid,))
    calls = []
    def change(paused, expected_revision):
        calls.append((paused, expected_revision))
        return dict(version='paper_entry_emergency_v1', revision=expected_revision+1, paused=paused)
    monkeypatch.setitem(sys.modules, 'entry_emergency', types.SimpleNamespace(
        status=lambda cur=None: dict(paused=False, revision=0), set_paused=change))
    monkeypatch.setitem(sys.modules, 'strategy_performance', types.SimpleNamespace(
        payload=lambda hours=48: dict(version=1,hours=hours,strategy_rows=[])))
    app = FastAPI()
    routes_scanner.register_scanner_routes(app)
    return TestClient(app), calls


def test_public_performance_does_not_grant_control(browser):
    client, calls = browser
    assert client.get('/api/scanner/strategy-performance?hours=48').status_code == 200
    assert client.get('/api/scanner/strategy-performance?hours=12').status_code == 422
    assert calls == []


@pytest.mark.parametrize('token,code', [(None,401), ('synthetic-regular',403)])
def test_public_or_regular_user_cannot_control_entries(browser, token, code):
    client, calls = browser
    headers = {'Authorization':'Bearer '+token} if token else {}
    assert client.get('/api/scanner/settings/entry-emergency',headers=headers).status_code == code
    assert client.put('/api/scanner/settings/entry-emergency',headers=headers,
                      json=dict(paused=True,expected_revision=0)).status_code == code
    assert calls == []


@pytest.mark.parametrize('token', ['synthetic-admin','synthetic-operator'])
def test_existing_manager_can_change_entries(browser, token):
    client, calls = browser
    headers = {'Authorization':'Bearer '+token}
    assert client.get('/api/scanner/settings/entry-emergency',headers=headers).status_code == 200
    assert client.put('/api/scanner/settings/entry-emergency',headers=headers,
                      json=dict(paused=True,expected_revision=0)).status_code == 200
    assert calls == [(True,0)]


@pytest.mark.parametrize('body', [dict(paused='false',expected_revision=0),
    dict(paused=True,expected_revision=True),dict(paused=True,expected_revision=-1),
    dict(paused=True,expected_revision=0,now='2000-01-01T00:00:00Z')])
def test_strict_body_cannot_supply_clock(browser, body):
    client, calls = browser
    assert client.put('/api/scanner/settings/entry-emergency',json=body,
        headers={'Authorization':'Bearer synthetic-admin'}).status_code == 422
    assert calls == []


def test_logs_header_is_not_write_permission(browser):
    client, calls = browser
    assert client.put('/api/scanner/settings/entry-emergency',
        headers={'X-Telegram-Init-Data':'synthetic-logs-member'},
        json=dict(paused=True,expected_revision=0)).status_code == 401
    assert calls == []
