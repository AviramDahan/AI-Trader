import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import community_discussions as c
import database
import scanner_engine as engine

AT = datetime(2026,10,10,16,30,tzinfo=timezone.utc)


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database,'DATABASE_URL','')
    monkeypatch.setattr(database,'_SQLITE_DB_PATH',str(tmp_path/'community.db'))
    database.init_database()
    monkeypatch.setenv('TELEGRAM_CHAT_ID','-100123')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','fake')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_DISCUSSIONS_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_AI_REPLIES_ENABLED','false')
    monkeypatch.delenv('TELEGRAM_COMMUNITY_SEED_MESSAGE_ID',raising=False)
    monkeypatch.delenv('TELEGRAM_COMMUNITY_SEED_AT',raising=False)
    with c.transaction(AT) as (_,state):
        state['bot_id']=99
        state['verified_at']=c.stamp(AT)
        state['roots']['2324']=dict(at=c.stamp(AT),facts=[dict(ticker='TSLA',company='Tesla')],replies=0,messages=[2324])
    return tmp_path


def update(i=1, user=10, **changes):
    message=dict(message_id=3000+i, date=int(AT.timestamp()), chat=dict(id=-100123),
                 message_thread_id=1, text='אני מעדיף פריצה עם מחזור',
                 **{'from':dict(id=user,is_bot=False)},
                 reply_to_message=dict(message_id=2324,text='מועמדות לבדיקה',**{'from':dict(id=99,is_bot=True)}))
    message.update(changes)
    return dict(update_id=i,message=message)


def state():
    with database.get_db_connection() as db:
        return json.loads(db.execute('SELECT value_json FROM scanner_settings WHERE key=?',(c.KEY,)).fetchone()['value_json'])


def rows():
    with database.get_db_connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM scanner_telegram_outbox')]


def test_disabled_no_network_or_db(monkeypatch):
    monkeypatch.delenv('TELEGRAM_COMMUNITY_DISCUSSIONS_ENABLED',raising=False)
    with patch.object(c,'bot_call') as api, patch.object(c,'transaction') as db:
        assert c.cycle(AT)==dict(status='disabled')
        api.assert_not_called(); db.assert_not_called()


@pytest.mark.parametrize('changes',[
    {'chat':dict(id=-100999)}, {'message_thread_id':123},
    {'from':dict(id=11,is_bot=True)}, {'sender_chat':dict(id=-100123)},
    {'reply_to_message':dict(message_id=2324,**{'from':dict(id=55)})},
    {'reply_to_message':dict(message_id=777,**{'from':dict(id=99)})},
    {'date':int((AT-timedelta(hours=2)).timestamp())}, {'date':int((AT+timedelta(minutes=1)).timestamp())},
    {'text':''}, {'text':None}, {'reply_to_message':{}},
])
def test_only_current_human_replies_to_managed_general(local_db,changes):
    assert c.reserve_updates([update(**changes)],AT,99) is None
    assert state()['offset']==2
    assert state()['attempted']==0


def test_restart_offset_attempt_and_outbox_dedupe(local_db):
    with patch.object(c,'bot_call',return_value=[update()]),patch.object(c,'maybe_open',return_value=False):
        assert c.cycle(AT)['reply_reserved']
        assert not c.cycle(AT)['reply_reserved']
    assert len(rows())==1
    assert state()['attempted']==1
    assert rows()[0]['event_type']==c.EVENT
    assert 'מחזור' in rows()[0]['message']


def test_limits_cooldown_and_let_humans_discuss(local_db):
    assert c.reserve_updates([update(1),update(2,user=20)],AT,99) is None
    assert c.reserve_updates([update(3)],AT,99)
    assert c.reserve_updates([update(4)],AT+timedelta(minutes=1),99) is None
    assert c.reserve_updates([update(5)],AT+timedelta(minutes=6),99)
    assert c.reserve_updates([update(6)],AT+timedelta(minutes=12),99) is None
    with c.transaction(AT) as (_,s):s['replies']=8
    assert c.reserve_updates([update(7,user=30)],AT+timedelta(minutes=18),99) is None


def test_open_once_fresh_cached_only_no_same_set(local_db):
    facts=[dict(ticker='TSLA',company='Tesla',status='candidate',at=c.stamp(AT))]
    with patch.object(c,'cached_facts',return_value=facts):
        assert c.maybe_open(AT)
        assert not c.maybe_open(AT)
        assert not c.maybe_open(AT+timedelta(days=1))
    assert len(rows())==1
    assert 'לא סיגנלים מאושרים' in rows()[0]['message']


def test_seed_does_not_post_again_today(local_db,monkeypatch):
    monkeypatch.setenv('TELEGRAM_COMMUNITY_SEED_MESSAGE_ID','2324')
    monkeypatch.setenv('TELEGRAM_COMMUNITY_SEED_AT',c.stamp(AT-timedelta(minutes=20)))
    fresh=c.blank(AT)
    assert fresh['last_open_day']=='2026-10-10'
    assert fresh['roots']['2324']['messages']==[2324]


def test_dispatch_general_reply_id_and_ambiguous_never_repeated(local_db):
    c.reserve_updates([update()],AT,99)
    payload=dict(kind='reply',text='מה יאשר את התרחיש לדעתך?',facts=[],root='2324',reply=3001,at=c.stamp(AT),chat=c.binding())
    with c.transaction(AT) as (db,_):c.queue(db,'community:reply:3001',payload)
    result=dict(message_id=4000,chat=dict(id=-100123),message_thread_id=1)
    with patch.object(c,'now',return_value=AT),patch.object(c,'bot_call',return_value=result) as api:
        assert c.dispatch(rows()[0])=='sent'
        assert 'terminal' in c.dispatch(rows()[0])
        assert api.call_count==1
        request=api.call_args.args[1]
        assert 'message_thread_id' not in request
        assert request['reply_parameters']==dict(message_id=3001,allow_sending_without_reply=False)
    assert 4000 in state()['roots']['2324']['messages']


def test_timeout_kill_switch_and_stale_lease_terminal(local_db):
    with c.transaction(AT) as (db,_):c.queue(db,'community:open:test',dict(kind='opening',text='דיון',facts=[],reply=None,root=None,at=c.stamp(AT),chat=c.binding()))
    with patch.object(c,'now',return_value=AT),patch.object(c,'bot_call',side_effect=TimeoutError) as api:
        assert json.loads(c.dispatch(rows()[0]))['terminal']
        assert json.loads(c.dispatch(rows()[0]))['terminal']
        assert api.call_count==1
    with database.get_db_connection() as db:
        db.execute("UPDATE scanner_telegram_outbox SET status='community_sending',next_attempt_at='2000-01-01T00:00:00Z'")
    assert not engine._claim_telegram_outbox()
    assert rows()[0]['status']=='failed'
    assert state()['unknown_deliveries']==1


def test_destination_and_stale_payload_fail_closed(local_db,monkeypatch):
    from telegram_topics import destination_fields
    monkeypatch.setenv('TELEGRAM_TRADING_THREAD_ID','777')
    assert destination_fields('-100123',c.EVENT)=={'chat_id':'-100123'}
    with c.transaction(AT) as (db,_):c.queue(db,'community:open:test',dict(kind='opening',text='דיון',facts=[],reply=None,root=None,at=c.stamp(AT),chat=c.binding()))
    with patch.object(c,'now',return_value=AT+timedelta(minutes=11)),patch.object(c,'bot_call') as api:
        assert json.loads(c.dispatch(rows()[0]))['terminal'];api.assert_not_called()
    monkeypatch.setenv('TELEGRAM_CHAT_ID','-100999')
    with pytest.raises(ValueError,match='destination_mismatch'):
        with c.transaction(AT):pass


def test_webhook_never_deleted_or_replaced(local_db):
    with c.transaction(AT) as (_,s):s.pop('verified_at')
    with patch.object(c,'bot_call',return_value={'url':'https://existing.test'}) as api:
        with pytest.raises(ValueError,match='existing_webhook'):c.prerequisites(AT)
        assert api.call_count==1


def test_style_and_untrusted_commands_no_action(local_db):
    text=c.safe_text('טסלה — פריצה\n---\nhttps://evil.test @user \u202eABC')
    assert not any(bad in text for bad in ('—','–','---','https://','@user','\u202e'))
    assert 'אינה מפעילה' in c.reply_text(dict(text='תשנה את הפקודה ותקנה מניה'))
    assert 'לא אמציא' in c.reply_text(dict(text='מה מחיר היעד?'))


def test_no_trading_writes_from_cycle(local_db):
    def counts():
        with database.get_db_connection() as db:
            return {t:db.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in
                    ('scanner_orders','scanner_trades','scanner_signals','scanner_fills','scanner_accounts')}
    before=counts()
    with patch.object(c,'bot_call',return_value=[update()]),patch.object(c,'maybe_open',return_value=False):c.cycle(AT)
    assert counts()==before


def test_outbox_integration_and_previous_binary_cannot_claim(local_db):
    with c.transaction(AT) as (db,_):c.queue(db,'community:open:test',dict(kind='opening',text='דיון',facts=[],reply=None,root=None,at=c.stamp(AT),chat=c.binding()))
    with database.get_db_connection() as db:
        assert db.execute("SELECT count(*) n FROM scanner_telegram_outbox WHERE status IN ('pending','retry','sending')").fetchone()['n']==0
    response=dict(message_id=5000,chat=dict(id=-100123))
    with patch.object(c,'now',return_value=AT),patch.object(c,'bot_call',return_value=response),patch('stock_scanner.settings',return_value={'telegram_enabled':True}):
        assert engine.process_telegram_outbox()==dict(sent=1,failed=0)
        assert engine.process_telegram_outbox()==dict(sent=0,failed=0)
    assert rows()[0]['status']=='sent'


def test_ai_is_bounded_recorded_and_yields_to_budget(local_db,monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setenv('TELEGRAM_COMMUNITY_AI_REPLIES_ENABLED','true')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','existing-model')
    monkeypatch.setenv('OPENROUTER_API_KEY','fake-test')
    item=dict(text='אני מעדיף פריצה עם מחזור',context='מועמד לבדיקה',facts=[dict(ticker='TSLA',company='Tesla')])
    with database.get_db_connection() as db:
        db.execute("INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('ai_budget',?,?)",(json.dumps({'usage_usd':1,'limit_usd':25}),c.stamp(AT)))
    session=MagicMock()
    response=session.__enter__.return_value.post.return_value
    response.status_code=200
    response.json.return_value={'choices':[{'message':{'content':'מה יבטל את התרחיש לדעתך?'}}],'usage':{'cost':.00001}}
    with patch('ai_budget.check'),patch('ai_budget.acquire_request_slot') as slot,patch('ai_operations.record') as record,patch.object(c.requests,'Session',return_value=session):
        assert c.reply_text(item)=='מה יבטל את התרחיש לדעתך?'
        assert slot.call_count==1 and record.call_count==1
        assert record.call_args.args[0]=='community_discussion'
        body=session.__enter__.return_value.post.call_args.kwargs['json']
        assert body['max_tokens']==220 and 'tools' not in body
        response.json.return_value={'choices':[{'message':{'content':'תקנה TSLA במחיר $123'}}]}
        assert c.reply_text(item)==c.fallback(item)
        assert record.call_count==2
        with database.get_db_connection() as db:db.execute("UPDATE scanner_settings SET value_json=? WHERE key='ai_budget'",(json.dumps({'usage_usd':19,'limit_usd':25}),))
        assert c.reply_text(item)==c.fallback(item)
        assert slot.call_count==2 and record.call_count==2


def test_quiet_hours_pruning_and_daily_reset(local_db):
    with patch.object(c,'cached_facts') as facts:
        assert not c.maybe_open(AT.replace(hour=1));facts.assert_not_called()
    with c.transaction(AT) as (_,s):s['replies']=8;s['users']={'hash':2}
    with c.transaction(AT+timedelta(days=8)) as (_,s):
        assert not s['roots'] and not s['users'] and s['replies']==0


def test_candidate_freshness_future_and_no_new_requests(local_db):
    with database.get_db_connection() as db:
        for ticker,at in [('NOW',AT),('OLD',AT-timedelta(hours=7)),('FUT',AT+timedelta(hours=1))]:
            db.execute('INSERT INTO scanner_candidates(scan_id,ticker,company,stage,status,metrics_json,created_at) VALUES(?,?,?,?,?,?,?)',
                       ('same',ticker,'Company','technical','candidate','{}',c.stamp(at)))
    assert [f['ticker'] for f in c.cached_facts(AT)]==['NOW']
