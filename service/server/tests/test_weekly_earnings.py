"""Isolated weekly delivery tests: no real Telegram calls."""
import importlib.util
from pathlib import Path
from datetime import date
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
