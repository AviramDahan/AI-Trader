"""Credential-free mocked RSS recovery; never invokes a live provider/worker."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_events.engine import Pipeline
from news_events.press_feed import PressFeedProvider
from news_events.providers import Config, ProviderFailure, Transport
from news_events import provider_config as controls
from news_events.store import Store

NOW = datetime(2026, 10, 23, 11, tzinfo=timezone.utc)
ENDPOINT = 'https://www.prnewswire.com/rss/news-releases-list.rss'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', Mock(side_effect=AssertionError('no network')))
    monkeypatch.setenv('NEWS_PRNEWSWIRE_ACTIVATED_AT', '2026-10-19T00:00:00Z')


def config(**changes):
    return Config(**(dict(provider_id='prnewswire', endpoint=ENDPOINT,
        publisher='PR Newswire', enabled=True, rights='approved') | changes))


def state(**changes):
    return dict(status='requires_configuration', terminal=True, http_status=301,
        error='http_error', attempts=1, last_success=(NOW-timedelta(days=3, minutes=5)).isoformat(),
        last_attempt=(NOW-timedelta(days=3)).isoformat(),
        next_at=(NOW-timedelta(days=3)+timedelta(minutes=2)).isoformat(),
        cursor='retained-cursor', checkpoint_json=json.dumps({'prior_key': 'retained'})) | changes


def test_verified_exact_prnewswire301_gets_one_delayed_probe_without_state_reset():
    before = state()
    original = copy.deepcopy(before)
    recovered = PressFeedProvider(config()).recover_terminal(before, NOW)
    assert recovered is not None
    assert before == original
    assert recovered['terminal'] is False
    for key in ('attempts', 'last_success', 'last_attempt', 'next_at', 'cursor'):
        assert recovered[key] == before[key]
    checkpoint = json.loads(recovered['checkpoint_json'])
    assert checkpoint == dict(prior_key='retained', access_recovery_for=before['last_success'],
        redirect_recovery_for=before['last_success'], recovery_not_before=NOW.isoformat())
    assert PressFeedProvider(config()).recover_terminal(recovered | {'terminal': True}, NOW) is None


@pytest.mark.parametrize('change', [
    {'next_at': (NOW+timedelta(minutes=1)).isoformat()},
    {'last_attempt': (NOW-timedelta(minutes=59)).isoformat(), 'next_at': NOW.isoformat()},
    {'last_success': None}, {'last_success': 'not-a-date'}, {'last_success': NOW.isoformat()},
    {'last_attempt': 'invalid'}, {'last_attempt': NOW.isoformat().replace('+00:00', '')},
    {'next_at': None}, {'next_at': 'invalid'}, {'attempts': True},
    {'next_at': (NOW-timedelta(days=4)).isoformat()}, {'http_status': 301.0},
    {'checkpoint_json': '[]'}, {'checkpoint_json': 'invalid'},
    {'checkpoint_json': json.dumps({'recovery_not_before': (NOW+timedelta(hours=1)).isoformat()})},
    {'checkpoint_json': json.dumps({'recovery_not_before': 'invalid'})},
    {'error': 'unsafe_endpoint'}, {'error': 'source_metadata_invalid'},
    {'http_status': 302}, {'http_status': 404}, {'terminal': False},
])
def test_recovery_never_overrides_fresh_backoff_unknown_or_other_failures(change):
    assert PressFeedProvider(config()).recover_terminal(state(**change), NOW) is None


@pytest.mark.parametrize('change', [
    {'provider_id': 'globenewswire'}, {'enabled': False}, {'rights': 'internal_review'},
    {'endpoint': ENDPOINT+'/'}, {'endpoint': ENDPOINT+'?token=private'},
    {'endpoint': ENDPOINT+'#fragment'}, {'endpoint': ENDPOINT.replace('https:', 'http:')},
    {'endpoint': ENDPOINT.replace('www.prnewswire.com', 'user@www.prnewswire.com')},
    {'endpoint': 'https://127.0.0.1/rss/news-releases-list.rss'},
])
def test_new_allowance_is_exact_approved_official_feed_only(change):
    assert PressFeedProvider(config(**change)).recover_terminal(state(), NOW) is None


def test_same_verified_incident_cannot_obtain301_after403_allowance_consumed():
    before = state()
    before['checkpoint_json'] = json.dumps({'access_recovery_for': before['last_success']})
    assert PressFeedProvider(config()).recover_terminal(before, NOW) is None


def test_failed301_becoming403_cannot_obtain_a_second_recovery(isolated):
    p, store = isolated
    request = Mock(side_effect=ProviderFailure('http_error', 403, 0, True))
    provider = PressFeedProvider(config(), Mock(request=request))
    p.collect([provider], NOW)
    p.collect([provider], NOW+timedelta(days=1))
    assert request.call_count == 1


def test_saved_future_next_at_prevents_even_recovery_io(isolated):
    p, store = isolated
    before = state(next_at=(NOW+timedelta(minutes=5)).isoformat())
    with store.transaction(True) as c:
        c.execute("UPDATE ne_provider_state SET state_json=? WHERE provider_id='prnewswire'", (json.dumps(before),))
    request = Mock()
    assert p.collect([PressFeedProvider(config(), Mock(request=request))], NOW)['prnewswire'] == before
    request.assert_not_called()


@pytest.fixture
def isolated(tmp_path):
    def connect():
        c = sqlite3.connect(tmp_path/'rss-only.sqlite')
        c.row_factory = sqlite3.Row
        return c
    store = Store(connect, sandbox=True)
    store.install()
    p = Pipeline(store, {'TST': {'company': 'Test Devices Incorporated'}},
        lambda: (set(), set()), not_before=NOW-timedelta(days=4))
    with store.transaction(True) as c:
        c.execute('INSERT INTO ne_provider_state VALUES(?,?)', ('prnewswire', json.dumps(state())))
    return p, store


def saved(store):
    with store.transaction() as c:
        return json.loads(c.execute("SELECT state_json FROM ne_provider_state WHERE provider_id='prnewswire'").fetchone()['state_json'])


@pytest.mark.parametrize('failure', [ProviderFailure('http_error', 301, 0, True),
    ProviderFailure('transport_timeout'), ProviderFailure('http_error', 429, 600),
    ProviderFailure('http_error', 404, 0, True), ValueError('synthetic-invalid-xml')])
def test_failed_probe_is_consumed_before_io_and_never_loops_after_restart(isolated, failure):
    p, store = isolated
    before = saved(store)
    def request(endpoint):
        assert endpoint == ENDPOINT
        persisted = saved(store)
        assert persisted['terminal'] is True
        assert json.loads(persisted['checkpoint_json'])['redirect_recovery_for'] == before['last_success']
        assert persisted['attempts'] == before['attempts']
        raise failure
    transport = Mock(request=Mock(side_effect=request))
    result = p.collect([PressFeedProvider(config(), transport)], NOW)['prnewswire']
    assert result['terminal'] is True
    assert result['attempts'] == before['attempts']+1
    assert result['cursor'] == before['cursor'] and result['last_success'] == before['last_success']
    restarted = Pipeline(Store(store.connect, sandbox=True), p.universe, p.membership, not_before=p.not_before)
    restarted.collect([PressFeedProvider(config(), transport)], NOW+timedelta(days=1))
    assert transport.request.call_count == 1
    suspended = controls.suspended(saved(store), 'provider_not_enabled')
    restored = controls.resumed(suspended)
    with store.transaction(True) as c:
        c.execute("UPDATE ne_provider_state SET state_json=? WHERE provider_id='prnewswire'", (json.dumps(restored),))
    restarted.collect([PressFeedProvider(config(), transport)], NOW+timedelta(days=2))
    assert transport.request.call_count == 1


def test_crash_after_consumed_persist_cannot_replenish_probe(isolated):
    p, store = isolated
    class SimulatedCrash(BaseException):
        pass
    request = Mock(side_effect=SimulatedCrash())
    with pytest.raises(SimulatedCrash):
        p.collect([PressFeedProvider(config(), Mock(request=request))], NOW)
    assert saved(store)['terminal'] is True
    p.collect([PressFeedProvider(config(), Mock(request=request))], NOW+timedelta(hours=2))
    assert request.call_count == 1


def test_success_fences_out_outage_and_preserves_dedupe(isolated):
    p, store = isolated
    xml = b'''<rss><channel>
      <item><guid>old</guid><title>Test Devices Incorporated earnings</title>
      <link>https://www.prnewswire.com/news-releases/test-old-12345.html</link>
      <pubDate>Fri, 23 Oct 2026 10:59:59 GMT</pubDate></item>
      <item><guid>new</guid><title>Test Devices Incorporated earnings</title>
      <link>https://www.prnewswire.com/news-releases/test-new-12345.html</link>
      <pubDate>Fri, 23 Oct 2026 11:00:00 GMT</pubDate></item>
    </channel></rss>'''
    transport = Mock(request=Mock(return_value=xml))
    result = p.collect([PressFeedProvider(config(), transport)], NOW)['prnewswire']
    assert result['status'] == 'ok' and result['terminal'] is False
    checkpoint = json.loads(result['checkpoint_json'])
    assert checkpoint['recovery_not_before'] == NOW.isoformat() and checkpoint['replay_blocked'] == 1
    p.collect([PressFeedProvider(config(), transport)], NOW+timedelta(minutes=6))
    assert transport.request.call_count == 2
    with store.transaction() as c:
        assert c.execute('SELECT COUNT(*) n FROM ne_sources').fetchone()['n'] == 1
        assert c.execute('SELECT COUNT(*) n FROM ne_analysis').fetchone()['n'] == 0
        assert c.execute('SELECT COUNT(*) n FROM ne_delivery').fetchone()['n'] == 0


def transport_with(monkeypatch, locations):
    import news_events.providers as mod
    responses = []
    for status, location in locations:
        response = Mock(status=status)
        response.getheader.side_effect = lambda k, *d, loc=location: loc if k == 'Location' else 'identity' if k == 'Content-Encoding' else None
        response.read1.side_effect = [b'<rss/>', b'']
        responses.append(response)
    connections = [Mock(getresponse=Mock(return_value=r)) for r in responses]
    factory = Mock(side_effect=connections)
    monkeypatch.setattr(mod, 'resolve_public', lambda h: ['8.8.8.8'])
    monkeypatch.setattr(mod.socket, 'create_connection', Mock(return_value=Mock()))
    monkeypatch.setattr(mod.ssl, 'create_default_context', Mock(return_value=Mock()))
    monkeypatch.setattr(mod.http.client, 'HTTPSConnection', factory)
    return Transport(['www.prnewswire.com']), factory, connections


def test_existing_single_same_origin_relative_redirect_preserves_no_credentials(monkeypatch):
    transport, factory, connections = transport_with(monkeypatch, [(301, '/rss/news-releases-list.rss/'), (200, None)])
    assert transport.request(ENDPOINT) == b'<rss/>'
    assert factory.call_count == 2
    for connection in connections:
        assert set(connection.request.call_args.args[3]) == {'User-Agent', 'Accept-Encoding'}


@pytest.mark.parametrize('location', [None, ENDPOINT, 'https://other.example/rss',
    'http://www.prnewswire.com/rss', 'https://user:pass@www.prnewswire.com/rss',
    'https://127.0.0.1/rss', 'https://www.prnewswire.com:444/rss'])
def test_existing_denied_redirects_never_get_a_second_request(monkeypatch, location):
    transport, factory, _ = transport_with(monkeypatch, [(301, location)])
    with pytest.raises(ProviderFailure) as caught:
        transport.request(ENDPOINT)
    assert caught.value.terminal and factory.call_count == 1


@pytest.mark.parametrize('headers', [{'Authorization': 'synthetic'}, {'If-None-Match': 'synthetic'}, {'Cookie': 'synthetic'}])
def test_existing_custom_or_conditional_headers_are_never_forwarded(monkeypatch, headers):
    transport, factory, _ = transport_with(monkeypatch, [(301, '/rss/new')])
    with pytest.raises(ProviderFailure):
        transport.request(ENDPOINT, headers=headers)
    assert factory.call_count == 1


def test_existing_second_hop_is_terminal_even_same_origin(monkeypatch):
    transport, factory, _ = transport_with(monkeypatch, [(301, '/rss/one'), (301, '/rss/two')])
    with pytest.raises(ProviderFailure):
        transport.request(ENDPOINT)
    assert factory.call_count == 2
