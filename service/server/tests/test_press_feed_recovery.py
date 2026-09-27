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
