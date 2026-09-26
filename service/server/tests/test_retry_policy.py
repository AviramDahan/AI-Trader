from datetime import datetime,timezone
from unittest.mock import Mock,patch
import pytest
import requests
import retry_policy as p

def test_retry_after_seconds_and_http_date():
    assert p.retry_after('120')==120
    assert p.retry_after('Sun, 27 Sep 2026 00:02:00 GMT',datetime(2026,9,27,tzinfo=timezone.utc))==120
    assert p.retry_after('invalid')==0

def test_http_detail_does_not_include_secrets_or_body():
    r=Mock(status_code=403,headers={})
    e=requests.HTTPError('secret in url',response=r)
    assert 'secret' not in p.detail(e)
    assert '403' in p.detail(e)

def test_openrouter_retry_after_defers_instead_of_sleeping_or_retrying():
    r=Mock(status_code=429,headers={'Retry-After':'3600'})
    with patch.dict('os.environ',{'AI_TRADER_CLOUD':'false'}):
        with pytest.raises(p.DeferredProviderError) as e:p.defer_openrouter(r)
    assert e.value.retry_after_seconds==3600

def test_telegram_preserves_retry_after_and_terminal_codes():
    import stock_scanner as s
    for code,terminal in [(429,False),(403,True)]:
        r=Mock(status_code=code,headers={'Retry-After':'120'})
        r.json.return_value={'parameters':{'retry_after':180}}
        r.raise_for_status.side_effect=requests.HTTPError(response=r)
        session=Mock();session.post.return_value=r
        import json
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'fake','TELEGRAM_CHAT_ID':'fake'}),patch.object(s.requests,'Session',return_value=session):
            result=json.loads(s.send_telegram('test',{'telegram_enabled':True},'market_news'))
        assert result['retry_after']==180 and result['terminal']==terminal
