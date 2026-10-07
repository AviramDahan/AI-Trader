"""Authoritative admission before idempotent display projection; isolated DB."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database
import scanner_engine as engine
import signal_projection
import routes_signals
from routes import create_app


@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DATABASE_URL','')
    monkeypatch.setattr(database,'_SQLITE_DB_PATH',str(tmp_path/'isolated.db'))
    database.init_database()


def seed_projection():
    with database.get_db_connection() as c:
        c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
        c.execute("INSERT INTO agents(name,token,cash) VALUES('unrelated','other',100000)")
    engine.initialize_runtime()
    projection=dict(market='us-stock',title='BUY TEST | Paper signal',content='Synthetic factual signal',
        symbols='TEST',tags='stock-scanner,paper-only,buy-signal')
    signal=dict(ticker='TEST',company='Synthetic',action='BUY',entry=100,stop_loss=97,
        confidence=.9,time_horizon='days',reason='Synthetic',relevant_news=[])
    saved=engine.record_signal(signal,dict(_strategy_projection=projection),{}, {},'synthetic')
    return dict(projection,scanner_signal_id=saved['id'])


def accounting():
    with database.get_db_connection() as c:
        return {t:[dict(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY id')]
            for t in ('scanner_accounts','scanner_orders','scanner_trades','scanner_fills','scanner_telegram_outbox')}


def isolated_client(monkeypatch):
    # Rendering a strategy cannot reach Telegram/followers/external transports.
    async def no_notify(*a,**kw):return None
    monkeypatch.setattr(routes_signals,'notify_followers_of_post',no_notify)
    return TestClient(create_app())  # no lifespan or worker startup


def assert_roundtrip(client,payload):
    headers={'Authorization':'Bearer synthetic'}
    first=client.post('/api/signals/strategy',headers=headers,json=payload)
    assert first.status_code==200,first.text
    second=client.post('/api/signals/strategy',headers=headers,json=payload)
    assert second.status_code==200,second.text
    assert first.json()['signal_id']==second.json()['signal_id']
    assert second.json()['status']=='already_published'
    with database.get_db_connection() as c:
        assert c.execute("SELECT count(*) n FROM signals WHERE message_type='strategy'").fetchone()['n']==1
        saved=c.execute('SELECT external_signal_id,created_at FROM scanner_signals WHERE id=?',(payload['scanner_signal_id'],)).fetchone()
        projected=c.execute('SELECT created_at FROM signals WHERE signal_id=?',(saved['external_signal_id'],)).fetchone()
        assert saved['created_at']==projected['created_at']


def test_projection_retry_is_idempotent_and_cannot_trade(db,monkeypatch):
    payload=seed_projection();before=accounting()
    client=isolated_client(monkeypatch)
    assert_roundtrip(client,payload)
    assert accounting()==before
    api=Mock();signal_projection.retry_pending(api);api.assert_not_called()


@pytest.mark.parametrize('damage',['unknown','owner','ticker','content','market'])
def test_projection_rejects_mismatched_durable_signal(db,monkeypatch,damage):
    payload=seed_projection();before=accounting();headers={'Authorization':'Bearer synthetic'}
    if damage=='unknown':payload['scanner_signal_id']+=999
    if damage=='owner':headers['Authorization']='Bearer other'
    if damage=='ticker':payload['symbols']='OTHER'
    if damage=='content':payload['content']='Changed after admission'
    if damage=='market':payload['market']='crypto'
    response=isolated_client(monkeypatch).post('/api/signals/strategy',headers=headers,json=payload)
    assert response.status_code==400,response.text
    assert accounting()==before
    with database.get_db_connection() as c:assert c.execute('SELECT count(*) n FROM signals').fetchone()['n']==0


def test_retry_only_posts_existing_projection_without_admission(db):
    payload=seed_projection();before=accounting();api=Mock()
    signal_projection.retry_pending(api);signal_projection.retry_pending(api)
    assert api.call_count==2 and all(call.kwargs['json']==payload for call in api.call_args_list)
    assert accounting()==before
