"""Isolated weekly delivery tests: no real Telegram calls."""
import importlib.util
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
import pytest

spec = importlib.util.spec_from_file_location('weekly', Path(__file__).resolve().parents[3] / 'scripts/weekly_earnings.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def feed(author='/u/epswhispers', day='September 28, 2026', host='i.redd.it'):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <author><name>{author}</name></author>
    <title>The Most Anticipated Earnings Releases for the Week of {day}</title>
    <content type="html">&lt;p&gt;#MU #NKE #MU&lt;/p&gt;
    &lt;a href="https://{host}/abc.png"&gt;image&lt;/a&gt;
    &lt;a href="https://www.reddit.com/r/EarningsWhisper/comments/abc/title/"&gt;post&lt;/a&gt;</content>
    </entry></feed>'''.encode()


def test_current_official_calendar_and_caption():
    item=w.find_calendar(feed(),date(2026,9,28))
    assert item['tickers']==['MU','NKE']
    assert '28.09.2026' in w.caption(item)
    assert w.caption(item).startswith('דוחות לשבוע 28.09.2026–02.10.2026')
    assert 'השבוע הבא' not in w.caption(item)
    assert 'מקור ותמונה' not in w.caption(item)
    assert item['source_url'] not in w.caption(item)
    assert len(w.caption(item).encode('utf-16-le'))//2 <=1024


@pytest.mark.parametrize('changes',[{'author':'/u/imposter'},{'day':'September 21, 2026'},{'host':'example.com'}])
def test_reject_wrong_author_stale_week_or_image(changes):
    with pytest.raises(ValueError):
        w.find_calendar(feed(**changes),date(2026,9,28))


def test_year_boundary():
    assert w.next_monday(date(2027,12,31))==date(2028,1,3)


def inputs():
    return w.find_calendar(feed(),date(2026,9,28)), {'TELEGRAM_BOT_TOKEN':'test', 'TELEGRAM_CHAT_ID':'-1','TELEGRAM_EARNINGS_THREAD_ID':'42'}


def telegram_session(*, pin_fails=False):
    session=Mock()
    me=Mock(status_code=200,json=lambda:{'ok':True,'result':{'id':123,'is_bot':True}})
    member=Mock(status_code=200,json=lambda:{'ok':True,'result':{'status':'administrator',
            'user':{'id':123,'is_bot':True},'can_pin_messages':True}})
    session.get.side_effect=lambda url,**_kwargs:member if url.endswith('/getChatMember') else me
    session.photo_response=Mock(status_code=200,json=lambda:{'ok':True,'result':{'message_id':12,
                'from':{'id':123,'is_bot':True},'chat':{'id':-1},'message_thread_id':42,'photo':[{'file_id':'fixture'}]}})
    def post(url,**kwargs):
        if url.endswith('/sendPhoto'):
            return session.photo_response
        return Mock(status_code=403 if pin_fails else 200,json=lambda:{'ok':not pin_fails,'result':not pin_fails})
    session.post.side_effect=post
    return session


def test_pin_pending_receipt_precedes_silent_pin_and_restart_never_resends(tmp_path):
    item,values=inputs();session=telegram_session(pin_fails=True);saved=[]
    state=tmp_path/'pin-state.sqlite'
    with pytest.raises(ValueError,match='pin'):
        w.send_once(item,b'image','caption',values,session,state,saved.append)
    assert saved[-1]['status']=='pin_pending' and saved[-1]['message_id']==12
    assert len(saved[-1]['destination_binding'])==64
    assert [c.args[0].rsplit('/',1)[-1] for c in session.post.call_args_list]==['sendPhoto','pinChatMessage']
    resumed=telegram_session()
    assert w.send_once(item,b'image','caption',values,resumed,state,saved.append)['status']=='pinned'
    assert [c.args[0].rsplit('/',1)[-1] for c in resumed.post.call_args_list]==['pinChatMessage']
    assert resumed.post.call_args.kwargs['data']['disable_notification'] is True


def test_previous_week_unpins_only_exact_bound_receipt_after_new_pin(tmp_path):
    item,values=inputs();session=telegram_session();saved=[]
    previous={'schema_version':2,'week':'2026-09-21','status':'pinned','message_id':7,
              'destination_binding':w.destination_binding(123,-1,42)}
    result=w.send_once(item,b'image','caption',values,session,tmp_path/'state.sqlite',saved.append,previous=previous)
    assert result['status']=='pinned'
    calls=session.post.call_args_list
    assert [c.args[0].rsplit('/',1)[-1] for c in calls]==['sendPhoto','pinChatMessage','unpinChatMessage']
    assert calls[-1].kwargs['data']['message_id']==7
    assert all('unpinAll' not in c.args[0] for c in calls)


def test_delivered_once_survives_restart(tmp_path):
    item,values=inputs(); session=telegram_session()
    state=tmp_path/'state.sqlite'
    assert w.send_once(item,b'image','caption',values,session,state)['status']=='pinned'
    assert w.send_once(item,b'image','caption',values,session,state)['status']=='already_pinned'
    assert session.post.call_count==2
    assert session.post.call_args_list[0].kwargs['data']['message_thread_id']==42


def test_weekly_caption_bidi_without_network_or_delivery_changes(tmp_path):
    from telegram_presentation import telegram_text, RLM, LRI, PDI
    item, values = inputs(); session = telegram_session()
    text = w.caption(item, 'https://t.me/+Example')
    assert w.send_once(item, b'image', text, values, session, tmp_path/'fixture.sqlite')['status'] == 'pinned'
    payload = session.post.call_args_list[0].kwargs['data']
    assert payload['caption'] == telegram_text(text, limit=1024)
    assert payload['caption'].startswith(RLM)
    assert LRI + 'Before Open' in payload['caption']
    assert 'https://t.me/+Example' in payload['caption']
    assert payload['message_thread_id'] == 42


def test_uncertain_send_never_retried_blindly(tmp_path):
    item,values=inputs(); session=telegram_session(); session.post.side_effect=TimeoutError('secret URL')
    state=tmp_path/'state.sqlite'
    with pytest.raises(ValueError,match='delivery uncertain'):
        w.send_once(item,b'image','caption',values,session,state)
    with pytest.raises(ValueError,match='Previous send outcome uncertain'):
        w.send_once(item,b'image','caption',values,session,state)
    assert session.post.call_count==1


def test_explicit_rate_limit_can_retry(tmp_path):
    item,values=inputs(); session=telegram_session()
    session.photo_response=Mock(status_code=429,json=lambda:{'ok':False})
    state=tmp_path/'state.sqlite'
    with pytest.raises(ValueError,match='refused'):
        w.send_once(item,b'image','caption',values,session,state)
    session.photo_response=telegram_session().photo_response
    assert w.send_once(item,b'image','caption',values,session,state)['status']=='pinned'


def test_untrusted_image_rejected_before_network():
    session=Mock()
    with pytest.raises(ValueError):
        w.photo_bytes('https://example.com/a.png',session)
    session.get.assert_not_called()


def test_cloud_claim_failure_prevents_telegram(tmp_path):
    item,values=inputs(); session=telegram_session()
    persist=Mock(side_effect=ValueError('Cloud unavailable'))
    with pytest.raises(ValueError,match='Cloud unavailable'):
        w.send_once(item,b'image','caption',values,session,tmp_path/'state.sqlite',persist)
    session.post.assert_not_called()


def test_cloud_status_wraps_send(tmp_path):
    item,values=inputs(); session=telegram_session(); events=[]
    original=session.post.side_effect
    def post(url,**kwargs):
        events.append(url.rsplit('/',1)[-1])
        return original(url,**kwargs)
    session.post.side_effect=post
    w.send_once(item,b'image','caption',values,session,tmp_path/'state.sqlite',lambda record:events.append(record['status']))
    assert events==['sending','sendPhoto','pin_pending','pinChatMessage','pinned']


def test_cloud_state_compare_and_swap(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo')
    monkeypatch.setenv('GH_TOKEN','dummy')
    session=Mock()
    record=w.base64.b64encode(b'{"week":"2026-09-28","status":"retryable"}').decode()
    session.get.return_value=Mock(status_code=200,json=lambda:{'sha':'old','content':record})
    session.put.return_value=Mock(status_code=200,json=lambda:{'content':{'sha':'new'}})
    cloud=w.GitHubDelivery('2026-09-28',session)
    assert cloud.read()=={'week':'2026-09-28','status':'retryable'}
    cloud.write('sending')
    payload=session.put.call_args.kwargs['json']
    assert payload['sha']=='old'
    assert payload['branch']=='earnings-state'
    assert cloud.sha=='new'


def test_cloud_read_error_fails_closed(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo')
    monkeypatch.setenv('GH_TOKEN','dummy')
    session=Mock(); session.get.return_value.status_code=503
    with pytest.raises(ValueError,match='Cloud state read failed'):
        w.GitHubDelivery('2026-09-28',session).read()


@pytest.mark.parametrize('field,value', [('message_id',True),('message_id',0),('chat',{'id':-2}),
    ('chat',[]),('from',{'id':999,'is_bot':True}),('from',{'id':123,'is_bot':False}),
    ('message_thread_id',43),('message_thread_id',True),('photo',[])])
def test_unverified_photo_ack_stays_uncertain_and_never_pins_or_resends(tmp_path,field,value):
    item,values=inputs();session=telegram_session()
    ack=session.photo_response.json();ack['result'][field]=value
    session.photo_response.json=lambda:ack
    state=tmp_path/'invalid.sqlite'
    with pytest.raises(ValueError,match='ACK identity'):
        w.send_once(item,b'image','caption',values,session,state)
    with pytest.raises(ValueError,match='Previous send outcome uncertain'):
        w.send_once(item,b'image','caption',values,session,state)
    assert [c.args[0].rsplit('/',1)[-1] for c in session.post.call_args_list]==['sendPhoto']


def test_photo_ack_cloud_write_failure_prevents_pin_but_known_local_receipt_can_resume(tmp_path):
    item,values=inputs();session=telegram_session();saved=[]
    def persist(record):
        saved.append(record)
        if record['status']=='pin_pending':raise ValueError('Cloud unavailable')
    state=tmp_path/'persist.sqlite'
    with pytest.raises(ValueError,match='Cloud unavailable'):
        w.send_once(item,b'image','caption',values,session,state,persist)
    assert session.post.call_count==1 and saved[-1]['message_id']==12
    resumed=telegram_session()
    assert w.send_once(item,None,None,values,resumed,state)['status']=='pinned'
    assert [c.args[0].rsplit('/',1)[-1] for c in resumed.post.call_args_list]==['pinChatMessage']


def test_legacy_sent_without_receipt_is_manual_unknown_not_photo_replay(tmp_path):
    item,values=inputs();state=tmp_path/'legacy.sqlite';session=telegram_session()
    with w.sqlite3.connect(state) as db:
        db.execute('CREATE TABLE deliveries(week TEXT PRIMARY KEY,status TEXT,source TEXT,message_id INTEGER)')
        db.execute('INSERT INTO deliveries VALUES(?,?,?,NULL)',(item['week'],'sent','fixture'));db.commit()
    assert w.send_once(item,None,None,values,session,state)['status']=='already_sent_pin_unknown'
    session.get.assert_not_called();session.post.assert_not_called()


def test_resumed_receipt_target_change_blocks_pin_and_photo(tmp_path):
    item,values=inputs();session=telegram_session()
    record={'schema_version':2,'week':item['week'],'status':'pin_pending','message_id':12,
            'destination_binding':w.destination_binding(123,-1,99)}
    with pytest.raises(ValueError,match='binding changed'):
        w.send_once(item,None,None,values,session,tmp_path/'state.sqlite',resume=record)
    session.post.assert_not_called()


def test_previous_receipt_different_target_never_unpins(tmp_path):
    item,values=inputs();session=telegram_session()
    previous={'schema_version':2,'week':'2026-09-21','status':'pinned','message_id':7,
              'destination_binding':w.destination_binding(123,-1,99)}
    assert w.send_once(item,b'image','caption',values,session,tmp_path/'state.sqlite',previous=previous)['status']=='pinned'
    assert [c.args[0].rsplit('/',1)[-1] for c in session.post.call_args_list]==['sendPhoto','pinChatMessage']


def test_unpin_failure_restarts_only_exact_previous_cleanup(tmp_path):
    item,values=inputs();session=telegram_session();original=session.post.side_effect;saved=[]
    def post(url,**kwargs):
        if url.endswith('/unpinChatMessage'):return Mock(status_code=403,json=lambda:{'ok':False})
        return original(url,**kwargs)
    session.post.side_effect=post
    previous={'schema_version':2,'week':'2026-09-21','status':'pinned','message_id':7,
              'destination_binding':w.destination_binding(123,-1,42)}
    state=tmp_path/'unpin.sqlite'
    with pytest.raises(ValueError,match='unpinChatMessage'):
        w.send_once(item,b'image','caption',values,session,state,saved.append,previous=previous)
    assert saved[-1]['status']=='pinned' and saved[-1]['previous_pin']['message_id']==7
    restarted=telegram_session()
    assert w.send_once(item,None,None,values,restarted,state,saved.append)['status']=='pinned'
    assert [c.args[0].rsplit('/',1)[-1] for c in restarted.post.call_args_list]==['unpinChatMessage']
    assert 'previous_pin' not in saved[-1]


def test_known_prior_message_already_absent_is_idempotent_unpin(tmp_path):
    item,values=inputs();session=telegram_session()
    session.post.side_effect=lambda *_a,**_k:Mock(status_code=400,json=lambda:{'ok':False,'description':'Bad Request: message to unpin not found'})
    record={'schema_version':2,'week':item['week'],'status':'pinned','message_id':12,
            'destination_binding':w.destination_binding(123,-1,42),
            'previous_pin':{'week':'2026-09-21','message_id':7,'destination_binding':w.destination_binding(123,-1,42)}}
    assert w.send_once(item,None,None,values,session,tmp_path/'state.sqlite',resume=record)['status']=='pinned'
    assert session.post.call_args.kwargs['data']['message_id']==7


def test_cloud_receipt_cas_failure_cannot_advance_or_expose_raw_destinations(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo');monkeypatch.setenv('GH_TOKEN','dummy')
    session=Mock();session.put.return_value=Mock(status_code=409)
    cloud=w.GitHubDelivery('2026-09-28',session);cloud.sha='expected'
    record={'schema_version':2,'week':'2026-09-28','status':'pin_pending','message_id':12,
            'destination_binding':w.destination_binding(123,-1,42)}
    with pytest.raises(ValueError,match='no blind retry'):cloud.write(record)
    assert cloud.sha=='expected'
    sent=w.json.loads(w.base64.b64decode(session.put.call_args.kwargs['json']['content']))
    assert sent==record
    assert set(sent)=={'schema_version','week','status','message_id','destination_binding'}


def test_reentrant_sender_cannot_send_concurrent_second_photo(tmp_path):
    item,values=inputs();session=telegram_session();other=telegram_session();state=tmp_path/'concurrent.sqlite'
    original=session.post.side_effect
    def post(url,**kwargs):
        if url.endswith('/sendPhoto'):
            with pytest.raises(ValueError,match='Previous send outcome uncertain'):
                w.send_once(item,b'image','caption',values,other,state)
        return original(url,**kwargs)
    session.post.side_effect=post
    assert w.send_once(item,b'image','caption',values,session,state)['status']=='pinned'
    other.post.assert_not_called()


def test_preview_never_claims_sends_or_pins(monkeypatch,capsys):
    item,_=inputs();session=telegram_session()
    session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    monkeypatch.setattr(w.requests,'Session',Mock(return_value=session))
    monkeypatch.setattr(w,'fetch_calendar',Mock(return_value=item));monkeypatch.setattr(w,'photo_bytes',Mock(return_value=b'image'))
    cloud=Mock(side_effect=AssertionError('No preview state'));monkeypatch.setattr(w,'GitHubDelivery',cloud)
    monkeypatch.setattr(w.sys,'argv',['weekly_earnings.py','--github'])
    w.main()
    assert '"status": "preview"' in capsys.readouterr().out
    cloud.assert_not_called();session.post.assert_not_called();session.get.assert_not_called()


@pytest.mark.parametrize('status,method',[('pin_pending','pinChatMessage'),('pinned','unpinChatMessage')])
def test_cloud_restart_recovers_known_pin_without_source_fetch_or_photo(monkeypatch,tmp_path,capsys,status,method):
    item,values=inputs();session=telegram_session()
    class Friday(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,9,25,20,tzinfo=tz)
    record={'schema_version':2,'week':item['week'],'status':status,'message_id':12,
            'destination_binding':w.destination_binding(123,-1,42)}
    if status=='pinned':record['previous_pin']={'week':'2026-09-21','message_id':7,'destination_binding':record['destination_binding']}
    monkeypatch.setattr(w,'datetime',Friday)
    monkeypatch.setattr(w.sys,'argv',['weekly_earnings.py','--send','--github'])
    session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    monkeypatch.setattr(w.requests,'Session',Mock(return_value=session))
    monkeypatch.setattr(w,'fetch_calendar',Mock(side_effect=AssertionError('No recovery source fetch')))
    monkeypatch.setattr(w,'photo_bytes',Mock(side_effect=AssertionError('No recovery photo fetch')))
    cloud=Mock();cloud.read.return_value=record
    monkeypatch.setattr(w,'GitHubDelivery',Mock(return_value=cloud))
    original=w.send_once
    monkeypatch.setattr(w,'send_once',lambda *args,**kwargs:original(*args,state=tmp_path/'recovered.sqlite',**kwargs))
    for key,value in values.items():monkeypatch.setenv(key,value)
    w.main()
    assert '"status": "pinned"' in capsys.readouterr().out
    assert [c.args[0].rsplit('/',1)[-1] for c in session.post.call_args_list]==[method]


def test_pin_recovery_cas_conflict_stops_before_telegram(tmp_path):
    item,values=inputs();session=telegram_session()
    record={'schema_version':2,'week':item['week'],'status':'pin_pending','message_id':12,
            'destination_binding':w.destination_binding(123,-1,42)}
    with pytest.raises(ValueError,match='CAS conflict'):
        w.send_once(item,None,None,values,session,tmp_path/'cas.sqlite',
                    Mock(side_effect=ValueError('CAS conflict')),resume=record)
    session.post.assert_not_called()


def test_missing_pin_rights_blocks_new_photo_before_durable_claim(tmp_path):
    item,values=inputs();session=telegram_session();original=session.get.side_effect
    def get(url,**kwargs):
        if url.endswith('/getChatMember'):
            return Mock(status_code=200,json=lambda:{'ok':True,'result':{'status':'administrator',
                'user':{'id':123,'is_bot':True},'can_pin_messages':False}})
        return original(url,**kwargs)
    session.get.side_effect=get
    state=tmp_path/'no-rights.sqlite'
    with pytest.raises(ValueError,match='pin permission'):
        w.send_once(item,b'image','caption',values,session,state)
    session.post.assert_not_called()
    with w.sqlite3.connect(state) as db:assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0]==0


def test_cloud_pinned_wrong_current_target_is_not_reported_success(monkeypatch,tmp_path):
    item,values=inputs();session=telegram_session()
    class Friday(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,9,25,20,tzinfo=tz)
    monkeypatch.setattr(w,'datetime',Friday)
    monkeypatch.setattr(w.sys,'argv',['weekly_earnings.py','--send','--github'])
    session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    monkeypatch.setattr(w.requests,'Session',Mock(return_value=session))
    monkeypatch.setattr(w,'fetch_calendar',Mock(side_effect=AssertionError('No source fetch')))
    cloud=Mock();cloud.read.return_value={'schema_version':2,'week':item['week'],'status':'pinned','message_id':12,
                                       'destination_binding':w.destination_binding(123,-1,99)}
    monkeypatch.setattr(w,'GitHubDelivery',Mock(return_value=cloud))
    original=w.send_once
    monkeypatch.setattr(w,'send_once',lambda *args,**kwargs:original(*args,state=tmp_path/'wrong-target.sqlite',**kwargs))
    for key,value in values.items():monkeypatch.setenv(key,value)
    with pytest.raises(ValueError,match='binding changed'):w.main()
    session.post.assert_not_called();cloud.write.assert_not_called()


@pytest.mark.parametrize('stamp,allowed',[
    ('2026-10-09T17:59:59',False),
    ('2026-10-09T18:00:00',True),
    ('2026-10-09T22:59:59',True),
    ('2026-10-09T23:04:06',True),  # actual delayed scheduled run
    ('2026-10-10T02:58:25',True),  # actual delayed scheduled run
    ('2026-10-10T19:17:00',True),
    ('2026-10-11T23:59:59',True),
    ('2026-10-12T00:00:00',False),
    ('2026-10-08T20:00:00',False),
    ('2026-12-31T20:00:00',False),
    ('2027-01-01T23:00:00',True),
    ('2027-01-03T23:59:59',True),
    ('2027-01-04T00:00:00',False),
])
def test_bounded_weekend_catchup_window(stamp,allowed):
    now=datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo('Asia/Jerusalem'))
    assert w.delivery_window(now)==allowed


def test_window_uses_israel_timezone():
    assert w.delivery_window(datetime.fromisoformat('2026-10-09T15:00:00+00:00'))
    assert not w.delivery_window(datetime.fromisoformat('2026-10-11T21:00:00+00:00'))
    with pytest.raises(ValueError,match='timezone'):
        w.delivery_window(datetime(2026,10,9,20))


def test_delayed_main_send_then_catchup_is_already_sent(monkeypatch,tmp_path,capsys):
    # Full CLI path, durable claim and real local guard; only provider/Telegram
    # transports are mocked. No live topic, AI, repository or portfolio writes.
    clock=[datetime(2026,10,9,23,4,tzinfo=ZoneInfo('Asia/Jerusalem'))]
    class Frozen(datetime):
        @classmethod
        def now(cls,tz=None): return clock[0].astimezone(tz)
    monkeypatch.setattr(w,'datetime',Frozen)
    monkeypatch.setattr(w.sys,'argv',['weekly_earnings.py','--send','--github'])
    item=w.find_calendar(feed(day='October 12, 2026'),date(2026,10,12))
    fetch=Mock(return_value=item); monkeypatch.setattr(w,'fetch_calendar',fetch)
    monkeypatch.setattr(w,'photo_bytes',Mock(return_value=b'fixture'))
    session=telegram_session()
    session.__enter__=Mock(return_value=session); session.__exit__=Mock(return_value=False)
    monkeypatch.setattr(w.requests,'Session',Mock(return_value=session))
    cloud=Mock(); cloud.read.return_value=None
    def persist(record): cloud.read.return_value=record
    cloud.write.side_effect=persist
    monkeypatch.setattr(w,'GitHubDelivery',Mock(return_value=cloud))
    original=w.send_once
    monkeypatch.setattr(w,'send_once',lambda *args,**kw:original(*args,state=tmp_path/'state.sqlite',**kw))
    for key,value in inputs()[1].items(): monkeypatch.setenv(key,value)
    w.main()
    assert '"status": "pinned"' in capsys.readouterr().out
    clock[0]=datetime(2026,10,10,2,58,tzinfo=ZoneInfo('Asia/Jerusalem'))
    w.main()
    assert '"status": "already_pinned"' in capsys.readouterr().out
    assert session.post.call_count==2 and fetch.call_count==1
    assert fetch.call_args.args[0]==date(2026,10,12)
    assert [call.args[0]['status'] for call in cloud.write.call_args_list]==['sending','pin_pending','pinned']
    cloud.read.return_value={'week':'2026-10-12','status':'sending'}
    with pytest.raises(ValueError,match='Cloud delivery uncertain'):
        w.main()
    assert session.post.call_count==2 and fetch.call_count==1


def test_main_monday_blocks_before_network(monkeypatch):
    class Monday(datetime):
        @classmethod
        def now(cls,tz=None): return cls(2026,10,12,0,tzinfo=tz)
    monkeypatch.setattr(w,'datetime',Monday)
    monkeypatch.setattr(w.sys,'argv',['weekly_earnings.py','--send','--github'])
    session=Mock(); monkeypatch.setattr(w.requests,'Session',session)
    with pytest.raises(ValueError,match='delivery window'):
        w.main()
    session.assert_not_called()


@pytest.mark.parametrize('stamp,allowed',[
    ('2026-10-09T23:04:06',True),
    ('2026-10-10T02:58:25',True),
    ('2026-10-12T00:00:00',False),
])
def test_actual_workflow_python_guard(monkeypatch,stamp,allowed):
    import datetime as datetime_module
    import subprocess
    import re
    import textwrap
    now=datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo('Asia/Jerusalem'))
    class Frozen(datetime):
        @classmethod
        def now(cls,tz=None): return now.astimezone(tz)
    monkeypatch.setattr(datetime_module,'datetime',Frozen)
    monkeypatch.syspath_prepend(str(w.ROOT))
    monkeypatch.setenv('SCHEDULED','true'); monkeypatch.setenv('PREVIEW','false')
    run=Mock(); monkeypatch.setattr(subprocess,'run',run)
    workflow=(w.ROOT/'.github/workflows/weekly-earnings.yml').read_text(encoding='utf-8')
    code=textwrap.dedent(re.search(r"python - <<'PY'\n(.*?)\n\s+PY",workflow,re.S)[1])
    if allowed:
        exec(compile(code,'weekly-workflow','exec'),{})
        run.assert_called_once()
        assert run.call_args.args[0][-2:]==['--send','--github']
        assert run.call_args.kwargs['check'] is True
    else:
        with pytest.raises(SystemExit) as exit:
            exec(compile(code,'weekly-workflow','exec'),{})
        assert exit.value.code==0
        run.assert_not_called()
