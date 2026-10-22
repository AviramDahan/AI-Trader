"""Synthetic local-only translation; no provider/Telegram calls."""
import json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

AT=datetime(2026,10,22,13,tzinfo=timezone.utc)

@pytest.fixture
def db(tmp_path,monkeypatch):
    import database,scanner_engine,stock_scanner
    monkeypatch.setattr(database,'DATABASE_URL','')
    monkeypatch.setattr(database,'_SQLITE_DB_PATH',str(tmp_path/'hebrew.sqlite'))
    for key,value in {'TELEGRAM_TRUMP_TRUTH_ENABLED':'true','TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED':'true',
        'TELEGRAM_TRUMP_TRUTH_NOT_BEFORE':(AT-timedelta(minutes=5)).isoformat(),
        'TELEGRAM_MARKET_NEWS_THREAD_ID':'991','NEWS_EVENTS_RUNTIME':'false'}.items():monkeypatch.setenv(key,value)
    monkeypatch.delenv('TELEGRAM_NEWS_NOT_BEFORE',raising=False)
    database.init_database()
    monkeypatch.setattr(scanner_engine,'now_z',lambda:AT.isoformat())
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    return database

def item(body='We will not raise tariffs by 5%.',number=10):
    import trump_truth_posts as t
    text=t.HEADER+'\n'+body+'\n'+t.LABEL
    msg=NS(id=number,date=AT,message=text,action=None,peer_id=NS(channel_id=t.CHANNEL_ID),
           entities=[NS(offset=len(text[:text.rindex(t.LABEL)].encode('utf-16-le'))//2,
                        length=len(t.LABEL),url='https://truthsocial.com/@realDonaldTrump/117500000000000123')])
    return t.extract(msg,AT)[0]

def row(db):
    with db.get_db_connection() as c:return dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())

def test_hebrew_waiting_cannot_be_claimed_by_previous_source_binary(db):
    import trump_truth_posts as t
    t.ingest([item()],AT)
    assert row(db)['status']=='trump_hebrew_pending'
    with db.get_db_connection() as c:
        assert not c.execute("SELECT id FROM scanner_telegram_outbox WHERE status IN ('pending','retry','community_pending','trump_pending','trump_retry')").fetchall()

def test_unprepared_hebrew_never_sends_original_english_as_translation(db):
    import trump_truth_posts as t
    t.ingest([item()],AT)
    assert t.delivery_message(row(db),AT) is None


def approved(system,payload,schema):
    return ({'text_he':'לא נעלה את המכסים ב־5%.'} if 'text_he' in schema['properties'] else
            {'faithful':True,'fluent_hebrew':True,'complete':True,'unsupported_claims':False})


def test_complete_prepare_cache_dispatch_retry_reuses_translation(db,monkeypatch):
    import trump_truth_posts as t,trump_truth_translation as h,scanner_engine as engine,stock_scanner
    t.ingest([item()],AT)
    call=Mock(side_effect=approved)
    original=row(db)['message']
    assert h.prepare(at=AT,completion=call)=={'prepared':1,'deferred':0}
    assert call.call_count==2 and row(db)['status']==h.READY
    message=t.delivery_message(row(db),AT)
    assert 'לא נעלה' in message and 'תרגום AI' in message and 'We will' not in message
    assert 'לא אומת' in message and item()['truth_url'] in message
    assert len(message.encode('utf-16-le'))//2<=4096
    monkeypatch.setattr(h,'local_json',lambda *a:pytest.fail('inference on dispatch'))
    sender=Mock(side_effect=['connect_timeout','sent'])
    monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    assert engine.process_telegram_outbox()['failed']==1
    assert row(db)['message']==original and row(db)['status']==h.RETRY
    with db.get_db_connection() as c:c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    assert engine.process_telegram_outbox()['sent']==1
    assert engine.process_telegram_outbox()['sent']==0
    assert call.call_count==2 and sender.call_count==2


def test_failure_budget_durable_then_explicit_hebrew_link_only_fallback(db):
    import trump_truth_posts as t,trump_truth_translation as h
    t.ingest([item()],AT)
    unavailable=Mock(side_effect=ValueError('synthetic private content must not leak'))
    assert h.prepare(at=AT,completion=unavailable)['deferred']==1
    assert h.prepare(at=AT+timedelta(seconds=30),completion=unavailable)['prepared']==0
    assert h.prepare(at=AT+timedelta(seconds=61),completion=unavailable)['prepared']==1
    assert unavailable.call_count==2 and row(db)['status']==h.READY
    message=t.delivery_message(row(db),AT+timedelta(seconds=62))
    assert 'התרגום לעברית אינו זמין' in message and 'We will' not in message
    assert 'synthetic' not in message


def test_crash_at_last_budget_never_calls_model_again(db):
    import trump_truth_posts as t,trump_truth_translation as h
    t.ingest([item()],AT)
    r=row(db);envelope=json.loads(r['message'])
    value={'version':h.VERSION,'binding':h.binding(r,envelope),'attempts':2,'status':'working','text_he':''}
    with db.get_db_connection() as c:
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',(h.cache_key(r),h.wire(value),AT.isoformat()))
        c.execute("UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=?",(h.WORKING,(AT-timedelta(seconds=1)).isoformat()))
    assert h.prepare(at=AT,completion=lambda *a:pytest.fail('third attempt'))['prepared']==1
    assert 'אינו זמין' in t.delivery_message(row(db),AT)


def test_cached_translation_recovered_without_model_and_no_financial_writes(db):
    import trump_truth_posts as t,trump_truth_translation as h
    t.ingest([item()],AT)
    h.prepare(at=AT,completion=approved)
    with db.get_db_connection() as c:c.execute('UPDATE scanner_telegram_outbox SET status=?',(h.PENDING,))
    assert h.prepare(at=AT,completion=lambda *a:pytest.fail('cache not reused'))['prepared']==1
    with db.get_db_connection() as c:
        for table in ('scanner_orders','scanner_trades','scanner_fills','scanner_signals','scanner_news'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n']==0


@pytest.mark.parametrize('body',['','This post contains the following media: image','This post contains the following media: video'])
def test_media_does_not_invent_caption_or_call_ai(db,body):
    import trump_truth_posts as t,trump_truth_translation as h
    t.ingest([item(body)],AT)
    assert h.prepare(at=AT,completion=lambda *a:pytest.fail('media generation'))['prepared']==1
    assert 'אין תמלול' in t.delivery_message(row(db),AT)


@pytest.mark.parametrize(('source','hebrew'),[
    ('5 billion dollars','5 מיליון דולר'),('5%','5'),('5 dollars','5 אירו'),
    ('$-5','-5'),('-5','5'),('5 million','5 מיליארד'),('5 thousand','5 מיליון'),
    ('5','5 https://example.com'),('5','5\u202eעברית'),('5','5 another English draft'),
])
def test_numeric_currency_unit_or_content_drift_rejected(source,hebrew):
    import trump_truth_translation as h
    with pytest.raises(ValueError):h.validate_text({'text_he':hebrew},source)


@pytest.mark.parametrize(('source','hebrew'),[
    ('5 percent','5% בעברית'),('5 billion dollars','5 מיליארד דולר'),
    ('-5 million euros','-5 מיליון אירו'),('5 thousand','5 אלף'),
])
def test_equivalent_units_accepted(source,hebrew):
    import trump_truth_translation as h
    assert h.validate_text({'text_he':hebrew},source)==hebrew


def test_corrupt_cache_cancelled_without_generation(db):
    import trump_truth_posts as t,trump_truth_translation as h
    t.ingest([item()],AT)
    with db.get_db_connection() as c:
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',(h.cache_key(row(db)),'{broken',AT.isoformat()))
    assert h.prepare(at=AT,completion=lambda *a:pytest.fail('corrupt cache'))['prepared']==0
    assert row(db)['status']=='cancelled' and row(db)['last_error']=='trump_hebrew_cache_invalid'


def test_local_transport_never_paid_fallback_and_records_native_usage(monkeypatch):
    import ai_routing,ai_operations,trump_truth_translation as h
    monkeypatch.setattr(ai_routing,'enabled',lambda:True)
    monkeypatch.setattr(ai_routing,'ready',lambda:True)
    record=Mock();monkeypatch.setattr(ai_operations,'record',record)
    local=Mock(return_value=({'text_he':'בדיקה'},{'prompt_eval_count':9,'eval_count':3}))
    monkeypatch.setattr(ai_routing,'local_completion',local)
    monkeypatch.setattr(ai_routing,'Route',lambda *a:pytest.fail('paid route'))
    assert h.local_json('system',{'source_excerpt':'Test'},h.SCHEMA)=={'text_he':'בדיקה'}
    assert local.call_count==1
    args=record.call_args.args
    assert args[0]=='news_translation' and args[2]['usage']=={'cost':0,'prompt_tokens':9,'completion_tokens':3}
    local.side_effect=ValueError('synthetic error')
    with pytest.raises(ValueError):h.local_json('system',{},h.SCHEMA)
    assert local.call_count==2 and record.call_count==2
    assert record.call_args.args[5]=='local_translation_unavailable'
    monkeypatch.setattr(ai_routing,'ready',lambda:False)
    with pytest.raises(ValueError):h.local_json('system',{},h.SCHEMA)
    assert local.call_count==2
