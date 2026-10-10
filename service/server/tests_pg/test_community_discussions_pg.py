"""Use the same implementation and real PostgreSQL isolation, no provider calls."""
import json
from datetime import datetime,timezone
from unittest.mock import patch

import community_discussions as c
from database import get_db_connection


def test_durable_general_outbox_and_no_trading_mutation(pg,monkeypatch):
    monkeypatch.setenv('TELEGRAM_CHAT_ID','-100123')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_DISCUSSIONS_ENABLED','true')
    monkeypatch.delenv('TELEGRAM_COMMUNITY_SEED_MESSAGE_ID',raising=False)
    monkeypatch.delenv('TELEGRAM_COMMUNITY_SEED_AT',raising=False)
    at=datetime(2026,10,10,16,30,tzinfo=timezone.utc)
    payload=dict(kind='opening',text='שאלה לדיון',facts=[],root=None,reply=None,at=c.stamp(at),chat=c.binding())
    with c.transaction(at) as (db,s):
        s['last_open_day']='2026-10-10'
        assert c.queue(db,'community:open:2026-10-10',payload)
        assert not c.queue(db,'community:open:2026-10-10',payload)
    from scanner_engine import _claim_telegram_outbox
    with get_db_connection() as db:
        assert db.execute("SELECT count(*) n FROM scanner_telegram_outbox WHERE status IN ('pending','retry','sending')").fetchone()['n']==0
    assert _claim_telegram_outbox()[0]['status']=='community_sending'
    with patch.object(c,'now',return_value=at),patch.object(c,'bot_call',return_value=dict(message_id=5000,chat=dict(id=-100123))):
        with get_db_connection() as db:row=dict(db.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        assert c.dispatch(row)=='sent'
        assert json.loads(c.dispatch(row))['terminal']
    with get_db_connection() as db:
        state=json.loads(db.execute('SELECT value_json FROM scanner_settings WHERE key=?',(c.KEY,)).fetchone()['value_json'])
        assert state['roots']['5000']['messages']==[5000]
        assert state['delivered']==1
        for t in ('scanner_signals','scanner_orders','scanner_trades','scanner_fills'):
            assert db.execute('SELECT count(*) n FROM '+t).fetchone()['n']==0


def test_openers_only_three_durable_slots_and_reply_fence(pg,monkeypatch):
    monkeypatch.setenv('TELEGRAM_CHAT_ID','-100123')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_DISCUSSIONS_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_REPLIES_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_AI_REPLIES_ENABLED','true')
    monkeypatch.delenv('TELEGRAM_COMMUNITY_SEED_MESSAGE_ID',raising=False)
    monkeypatch.delenv('TELEGRAM_COMMUNITY_SEED_AT',raising=False)
    with patch.object(c,'bot_call') as network,patch.object(c,'reply_text') as ai,patch.object(c,'cached_facts',return_value=[]):
        for h in (6,10,16):
            at=datetime(2026,10,10,h,tzinfo=timezone.utc)
            assert c.cycle(at)['opened']
            assert not c.cycle(at)['opened']
        network.assert_not_called();ai.assert_not_called()
    with get_db_connection() as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM scanner_telegram_outbox WHERE event_type=?",(c.EVENT,))]
        assert len(rows)==3 and len({r['dedupe_key'] for r in rows})==3
        assert all(json.loads(r['message'])['kind']=='opening' for r in rows)
        for t in ('scanner_signals','scanner_orders','scanner_trades','scanner_fills'):
            assert db.execute('SELECT count(*) n FROM '+t).fetchone()['n']==0
    at=datetime(2026,10,10,16,tzinfo=timezone.utc)
    with c.transaction(at) as (db,_):
        c.queue(db,'community:reply:old',dict(kind='reply',text='תשובה',facts=[],root='2324',reply=3001,at=c.stamp(at),chat=c.binding()))
    with get_db_connection() as db:
        row=dict(db.execute("SELECT * FROM scanner_telegram_outbox WHERE dedupe_key='community:reply:old'").fetchone())
    with patch.object(c,'now',return_value=at),patch.object(c,'bot_call') as network:
        assert json.loads(c.dispatch(row))['reason']=='community_replies_disabled'
        network.assert_not_called()
