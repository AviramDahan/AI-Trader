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


def test_delivered_once_survives_restart(tmp_path):
    item,values=inputs(); session=Mock()
    session.post.return_value.json.return_value={'ok':True,'result':{'message_id':12}}
    state=tmp_path/'state.sqlite'
    assert w.send_once(item,b'image','caption',values,session,state)['status']=='sent'
    assert w.send_once(item,b'image','caption',values,session,state)['status']=='already_sent'
    assert session.post.call_count==1
    assert session.post.call_args.kwargs['data']['message_thread_id']==42


def test_weekly_caption_bidi_without_network_or_delivery_changes(tmp_path):
    from telegram_presentation import telegram_text, RLM, LRI, PDI
    item, values = inputs(); session = Mock()
    session.post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 12}}
    text = w.caption(item, 'https://t.me/+Example')
    assert w.send_once(item, b'image', text, values, session, tmp_path/'fixture.sqlite')['status'] == 'sent'
    payload = session.post.call_args.kwargs['data']
    assert payload['caption'] == telegram_text(text, limit=1024)
    assert payload['caption'].startswith(RLM)
    assert LRI + 'Before Open' in payload['caption']
    assert 'https://t.me/+Example' in payload['caption']
    assert payload['message_thread_id'] == 42


def test_uncertain_send_never_retried_blindly(tmp_path):
    item,values=inputs(); session=Mock(); session.post.side_effect=TimeoutError('secret URL')
    state=tmp_path/'state.sqlite'
    with pytest.raises(ValueError,match='delivery uncertain'):
        w.send_once(item,b'image','caption',values,session,state)
    with pytest.raises(ValueError,match='Previous send outcome uncertain'):
        w.send_once(item,b'image','caption',values,session,state)
    assert session.post.call_count==1


def test_explicit_rate_limit_can_retry(tmp_path):
    item,values=inputs(); session=Mock()
    session.post.return_value.status_code=429
    session.post.return_value.json.return_value={'ok':False}
    state=tmp_path/'state.sqlite'
    with pytest.raises(ValueError,match='HTTP 429'):
        w.send_once(item,b'image','caption',values,session,state)
    session.post.return_value.json.return_value={'ok':True,'result':{'message_id':12}}
    assert w.send_once(item,b'image','caption',values,session,state)['status']=='sent'


def test_untrusted_image_rejected_before_network():
    session=Mock()
    with pytest.raises(ValueError):
        w.photo_bytes('https://example.com/a.png',session)
    session.get.assert_not_called()


def test_cloud_claim_failure_prevents_telegram(tmp_path):
    item,values=inputs(); session=Mock()
    persist=Mock(side_effect=ValueError('Cloud unavailable'))
    with pytest.raises(ValueError,match='Cloud unavailable'):
        w.send_once(item,b'image','caption',values,session,tmp_path/'state.sqlite',persist)
    session.post.assert_not_called()


def test_cloud_status_wraps_send(tmp_path):
    item,values=inputs(); session=Mock(); events=[]
    def post(*args,**kwargs):
        events.append('telegram')
        return Mock(json=lambda:{'ok':True,'result':{'message_id':12}})
    session.post.side_effect=post
    w.send_once(item,b'image','caption',values,session,tmp_path/'state.sqlite',events.append)
    assert events==['sending','telegram','sent']


def test_cloud_state_compare_and_swap(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo')
    monkeypatch.setenv('GH_TOKEN','dummy')
    session=Mock()
    record=w.base64.b64encode(b'{"week":"2026-09-28","status":"retryable"}').decode()
    session.get.return_value=Mock(status_code=200,json=lambda:{'sha':'old','content':record})
    session.put.return_value=Mock(status_code=200,json=lambda:{'content':{'sha':'new'}})
    cloud=w.GitHubDelivery('2026-09-28',session)
    assert cloud.read()=='retryable'
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
    session=Mock()
    session.__enter__=Mock(return_value=session); session.__exit__=Mock(return_value=False)
    session.post.return_value.json.return_value={'ok':True,'result':{'message_id':12}}
    monkeypatch.setattr(w.requests,'Session',Mock(return_value=session))
    cloud=Mock(); cloud.read.return_value=None
    def persist(status): cloud.read.return_value=status
    cloud.write.side_effect=persist
    monkeypatch.setattr(w,'GitHubDelivery',Mock(return_value=cloud))
    original=w.send_once
    monkeypatch.setattr(w,'send_once',lambda *args,**kw:original(*args,state=tmp_path/'state.sqlite',**kw))
    for key,value in inputs()[1].items(): monkeypatch.setenv(key,value)
    w.main()
    assert '"status": "sent"' in capsys.readouterr().out
    clock[0]=datetime(2026,10,10,2,58,tzinfo=ZoneInfo('Asia/Jerusalem'))
    w.main()
    assert '"status": "already_sent"' in capsys.readouterr().out
    assert session.post.call_count==1 and fetch.call_count==1
    assert fetch.call_args.args[0]==date(2026,10,12)
    assert [call.args[0] for call in cloud.write.call_args_list]==['sending','sent']
    cloud.read.return_value='sending'
    with pytest.raises(ValueError,match='Cloud delivery uncertain'):
        w.main()
    assert session.post.call_count==1 and fetch.call_count==1


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
