from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from news_events.providers import Config, ProviderFailure, RSSProvider
from news_events.press_feed import PressFeedProvider

NOW = datetime(2026, 9, 27, 19, tzinfo=timezone.utc)

@pytest.mark.parametrize('pid', ['prnewswire', 'globenewswire'])
def test_activation_fence_persists_across_restart(pid, monkeypatch):
    monkeypatch.setenv('NEWS_' + pid.upper() + '_ACTIVATED_AT', NOW.isoformat())
    xml = b'''<rss><channel><item><title>Old</title><link>https://example.com/old</link><pubDate>Sun, 27 Sep 2026 18:59:00 GMT</pubDate></item><item><title>New</title><link>https://example.com/new</link><pubDate>Sun, 27 Sep 2026 19:00:00 GMT</pubDate></item></channel></rss>'''
    cfg = Config(pid, 'https://example.com/rss', pid, enabled=True, rights='approved')
    for _ in range(2):
        p = PressFeedProvider(cfg, Mock(request=Mock(return_value=xml)))
        result = p.fetch({}, NOW)
        assert len(result['items']) == 1 and result['items'][0]['title'] == 'New'
        assert result['raw_item_count'] == 2 and result['checkpoint']['replay_blocked'] == 1
        assert p.normalize(result['items'][0], NOW).published_at == NOW.isoformat()

def test_no_boundary_fail_closed_before_network(monkeypatch):
    monkeypatch.delenv('NEWS_PRNEWSWIRE_ACTIVATED_AT', raising=False)
    transport = Mock()
    with pytest.raises(ProviderFailure, match='activation_required'):
        PressFeedProvider(Config('prnewswire', 'https://example.com/rss', 'PR'), transport).fetch({}, NOW)
    transport.request.assert_not_called()

def test_recovery_boundary_blocks_outage_backlog_after_restart(monkeypatch):
    import json
    monkeypatch.setenv('NEWS_PRNEWSWIRE_ACTIVATED_AT', '2026-09-26T00:00:00Z')
    xml = b'''<rss><channel><item><title>Outage</title><link>https://example.com/old</link><pubDate>Sun, 27 Sep 2026 18:59:00 GMT</pubDate></item><item><title>New</title><link>https://example.com/new</link><pubDate>Sun, 27 Sep 2026 19:00:00 GMT</pubDate></item></channel></rss>'''
    cfg = Config('prnewswire', 'https://example.com/rss', 'PR', enabled=True, rights='approved')
    state = {'checkpoint_json': json.dumps({'recovery_not_before': NOW.isoformat()})}
    for _ in range(2):
        result = PressFeedProvider(cfg, Mock(request=Mock(return_value=xml))).fetch(state, NOW)
        assert [r['title'] for r in result['items']] == ['New']
        assert result['checkpoint']['replay_blocked'] == 1
        state = {'checkpoint_json': json.dumps(result['checkpoint'])}

@pytest.mark.parametrize('attempts,previous,terminal', [(0, True, False), (1, True, False), (2, True, True), (0, False, True)])
def test_404_recovery_bounded_only_for_verified_feed(monkeypatch, attempts, previous, terminal):
    monkeypatch.setenv('NEWS_PRNEWSWIRE_ACTIVATED_AT', NOW.isoformat())
    p = PressFeedProvider(Config('prnewswire', 'https://example.com/rss', 'PR', enabled=True, rights='approved'),
        Mock(request=Mock(side_effect=ProviderFailure('http_error', 404, 420, True))))
    with pytest.raises(ProviderFailure) as caught:
        p.fetch({'attempts': attempts, 'last_success': NOW.isoformat() if previous else None}, NOW)
    assert caught.value.terminal == terminal
    assert caught.value.retry_after >= 420

def test_standard_identifying_ua_is_press_only():
    cfg = Config('globenewswire', 'https://www.globenewswire.com/rss', 'Globe')
    assert PressFeedProvider(cfg).transport.user_agent.startswith('AI-Trader/1.0 ')
    assert RSSProvider(cfg).transport.user_agent == 'AI-Trader News Event Sandbox'
    assert PressFeedProvider(cfg).transport.read_timeout == 10
    assert PressFeedProvider(cfg).transport.timeout == 12
    assert RSSProvider(cfg).transport.read_timeout is None


@pytest.mark.parametrize('change', [
    {'last_success': None}, {'http_status': 401}, {'http_status': 404},
    {'error': 'unsafe_endpoint'}, {'error': 'source_metadata_invalid'},
    {'last_attempt': NOW.isoformat()}, {'last_attempt': 'invalid'},
    {'checkpoint_json': '{"access_recovery_for":"verified"}'},
])
def test_terminal_recovery_never_weakens_unverified_or_other_failures(change):
    from datetime import timedelta
    cfg=Config('globenewswire','https://www.globenewswire.com/rss','Globe',enabled=True,rights='approved')
    state=dict(terminal=True,http_status=403,error='http_error',last_success='verified',
               last_attempt=(NOW-timedelta(hours=2)).isoformat())
    state.update(change)
    assert PressFeedProvider(cfg).recover_terminal(state,NOW) is None


@pytest.mark.parametrize('enabled,rights', [(False,'approved'),(True,'review_required')])
def test_recovery_requires_current_approval(enabled,rights):
    from datetime import timedelta
    cfg=Config('globenewswire','https://www.globenewswire.com/rss','Globe',enabled=enabled,rights=rights)
    state=dict(terminal=True,http_status=403,error='http_error',last_success='verified',
               last_attempt=(NOW-timedelta(hours=2)).isoformat())
    assert PressFeedProvider(cfg).recover_terminal(state,NOW) is None

@pytest.mark.parametrize('read_timeout', [None, 10])
def test_read_timeout_applied_without_changing_connect_limit(monkeypatch, read_timeout):
    import news_events.providers as mod
    response=Mock(status=200)
    response.getheader.side_effect=lambda key,*default:'identity' if key=='Content-Encoding' else None
    response.read1.side_effect=[b'<rss/>',b'']
    connection=Mock(getresponse=Mock(return_value=response));sock=Mock()
    connect=Mock(return_value=Mock())
    monkeypatch.setattr(mod,'resolve_public',lambda _:['8.8.8.8'])
    monkeypatch.setattr(mod.socket,'create_connection',connect)
    monkeypatch.setattr(mod.ssl,'create_default_context',Mock(return_value=Mock(wrap_socket=Mock(return_value=sock))))
    monkeypatch.setattr(mod.http.client,'HTTPSConnection',Mock(return_value=connection))
    assert mod.Transport(['example.com'],read_timeout=read_timeout).request('https://example.com/rss')==b'<rss/>'
    connect.assert_called_once_with(('8.8.8.8',443),timeout=3)
    if read_timeout is None:sock.settimeout.assert_not_called()
    else:sock.settimeout.assert_called_once_with(10)
