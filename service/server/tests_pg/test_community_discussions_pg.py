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
