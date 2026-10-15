"""Synthetic provider disable/resume and corporate-vs-macro regressions."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from unittest.mock import Mock

import pytest

from news_events.engine import Analysis, Pipeline
from news_events.model import event_type
from news_events.providers import BaseProvider, Config, ProviderFailure
from news_events.press_feed import PressFeedProvider
from news_events.store import Store
import news_events.provider_config as controls

NOW = datetime(2026, 10, 15, 8, tzinfo=timezone.utc)
UNIVERSE = {'TST': {'company': 'Test Devices Incorporated'}}
GRANT = 'Example Therapeutics Reports Inducement Grants Under Nasdaq Listing Rule 5635(c)(4)'
GRANT_TEXT = ('Example Therapeutics announced equity inducement grants to six new employees '
              'as a material inducement to their employment under Nasdaq Listing Rule 5635(c)(4).')


def make_pipeline(connect):
    store = Store(connect, sandbox=True)
    store.install()
    return Pipeline(store, UNIVERSE, lambda: (set(), set()), not_before=NOW-timedelta(days=1)), store


@pytest.fixture
def isolated(tmp_path):
    def connect():
        c = sqlite3.connect(tmp_path/'isolated.sqlite')
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c
    return make_pipeline(connect)


def prior_state():
    success = (NOW-timedelta(days=2)).isoformat()
    return dict(status='requires_configuration', error='http_error', http_status=403,
                terminal=True, attempts=1, last_success=success,
                last_attempt=(NOW-timedelta(hours=2)).isoformat(),
                next_at=(NOW-timedelta(hours=1)).isoformat(), cursor='synthetic-cursor',
                checkpoint_json=json.dumps(dict(access_recovery_for=success,
                    recovery_not_before=(NOW-timedelta(days=1)).isoformat(), activation_boundary=success)))


def seed(store, state):
    with store.transaction(True) as c:
        c.execute('INSERT INTO ne_provider_state VALUES(?,?)', ('globenewswire', json.dumps(state)))


def saved(store):
    with store.transaction() as c:
        return json.loads(c.execute("SELECT state_json FROM ne_provider_state WHERE provider_id='globenewswire'").fetchone()['state_json'])


def configure(monkeypatch, enabled):
    cfg = Config('globenewswire', 'https://www.globenewswire.com/synthetic', 'GlobeNewswire',
                 enabled=enabled, rights='approved')
    monkeypatch.setenv('NEWS_EVENTS_PROVIDERS', 'globenewswire' if enabled else '')
    monkeypatch.setenv('NEWS_EVENTS_PROVIDER_APPROVALS', '{"globenewswire":"synthetic-reference"}')
    monkeypatch.setenv('NEWS_GLOBENEWSWIRE_ACTIVATED_AT', (NOW-timedelta(days=3)).isoformat())
    monkeypatch.setattr(controls, 'configured', lambda: [cfg])
    monkeypatch.setattr(controls, 'notify_changes', Mock())
    return cfg


def exercise_disabled_checkpoint_preservation(isolated, monkeypatch):
    p, store = isolated
    before = prior_state()
    seed(store, before)
    configure(monkeypatch, False)
    controls.collect(p, NOW)
    disabled = saved(store)
    assert disabled['status'] == 'disabled'
    assert disabled['checkpoint_json'] == before['checkpoint_json']
    assert disabled['last_success'] == before['last_success']
    assert disabled['disabled_resume_state'] == before
    assert disabled['error'] == 'provider_not_enabled' and disabled['http_status'] is None
    controls.collect(p, NOW+timedelta(minutes=5))
    assert saved(store) == disabled, 'repeated disable must not nest/reset the saved state'


def exercise_consumed_probe_survives_disable_and_restart(isolated, monkeypatch):
    p, store = isolated
    before = prior_state()
    seed(store, before)
    configure(monkeypatch, False)
    controls.collect(p, NOW)
    cfg = configure(monkeypatch, True)
    request = Mock(side_effect=ProviderFailure('http_error', 403, 0, True))
    monkeypatch.setattr(controls, 'registry', lambda _: [PressFeedProvider(cfg, Mock(request=request))])
    controls.collect(p, NOW+timedelta(minutes=1))
    restarted = Pipeline(Store(store.connect, sandbox=True), UNIVERSE, p.membership, not_before=p.not_before)
    controls.collect(restarted, NOW+timedelta(days=1))
    assert request.call_count == 0, 'reenable must not renew an exhausted recovery allowance'
    assert saved(store) == before
    with store.transaction() as c:
        for table in ('ne_events', 'ne_analysis', 'ne_delivery'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n'] == 0


def exercise_grant_never_becomes_unverified_market_news(isolated, monkeypatch):
    p, store = isolated
    raw = dict(id='synthetic-grant', url='https://www.globenewswire.com/news-release/synthetic-12345',
               title=GRANT, excerpt=GRANT_TEXT, published_at=NOW.isoformat())
    provider = BaseProvider(Config('globenewswire', 'https://www.globenewswire.com/synthetic',
                                  'GlobeNewswire', enabled=True, rights='approved'))
    source = provider.normalize(raw, NOW)
    assert source.event_type == 'business_update'
    eid = p.ingest(source, NOW)
    ai = Mock(return_value=Analysis(dict(related=True, title_he='החברה העניקה מענקים לעובדים',
        summary_he='דיווח חברה שגרתי על תגמול עובדים.', interpretation_he='אין זו המלצת מסחר.',
        sentiment='neutral', materiality='low', relevance=.8)))
    assert p.analyze(eid, ai, NOW) == 'blocked'
    ai.assert_not_called()
    assert store.event(eid)['reason'] == 'identity_unverified'
    assert p.deliver_preview(eid, NOW) == []


def exercise_resume_keeps_outage_fence_and_dedupe(isolated, monkeypatch):
    p, store = isolated
    before = {**prior_state(), 'status': 'ok', 'terminal': False, 'http_status': None, 'error': None,
              'checkpoint_json': json.dumps({'recovery_not_before': NOW.isoformat()})}
    seed(store, before)
    configure(monkeypatch, False)
    controls.collect(p, NOW)
    cfg = configure(monkeypatch, True)
    xml = b'''<rss><channel>
    <item><guid>old</guid><title>Test Devices Incorporated reports old earnings</title>
    <link>https://www.globenewswire.com/news-release/synthetic-old-12345</link>
    <pubDate>Thu, 15 Oct 2026 07:59:00 GMT</pubDate></item>
    <item><guid>new</guid><title>Test Devices Incorporated reports new earnings</title>
    <link>https://www.globenewswire.com/news-release/synthetic-new-12345</link>
    <pubDate>Thu, 15 Oct 2026 08:00:00 GMT</pubDate></item>
    </channel></rss>'''
    request = Mock(return_value=xml)
    monkeypatch.setattr(controls, 'registry', lambda _: [PressFeedProvider(cfg, Mock(request=request))])
    controls.collect(p, NOW+timedelta(minutes=1))
    checkpoint = json.loads(saved(store)['checkpoint_json'])
    assert checkpoint['activation_boundary'] == NOW.isoformat() and checkpoint['replay_blocked'] == 1
    restarted = Pipeline(Store(store.connect, sandbox=True), UNIVERSE, p.membership, not_before=p.not_before)
    controls.collect(restarted, NOW+timedelta(minutes=2))
    assert request.call_count == 1, 'restart must honor the saved next-at'
    controls.collect(restarted, NOW+timedelta(minutes=7))
    assert request.call_count == 2
    with store.transaction() as c:
        assert c.execute('SELECT COUNT(*) n FROM ne_sources').fetchone()['n'] == 1
        assert c.execute('SELECT COUNT(*) n FROM ne_events').fetchone()['n'] == 1
        assert c.execute('SELECT COUNT(*) n FROM ne_analysis').fetchone()['n'] == 0
        assert c.execute('SELECT COUNT(*) n FROM ne_delivery').fetchone()['n'] == 0


def test_disabled_checkpoint_preservation(isolated, monkeypatch):
    exercise_disabled_checkpoint_preservation(isolated, monkeypatch)


def test_consumed_probe_survives_disable_and_restart(isolated, monkeypatch):
    exercise_consumed_probe_survives_disable_and_restart(isolated, monkeypatch)


def test_grant_never_becomes_unverified_market_news(isolated, monkeypatch):
    exercise_grant_never_becomes_unverified_market_news(isolated, monkeypatch)


def test_resume_keeps_outage_fence_and_dedupe(isolated, monkeypatch):
    exercise_resume_keeps_outage_fence_and_dedupe(isolated, monkeypatch)


def test_pending_backoff_is_not_reset_on_enable(isolated, monkeypatch):
    p, store = isolated
    before = {**prior_state(), 'status': 'degraded', 'terminal': False,
              'next_at': (NOW+timedelta(hours=1)).isoformat()}
    seed(store, before)
    configure(monkeypatch, False)
    controls.collect(p, NOW)
    cfg = configure(monkeypatch, True)
    request = Mock()
    monkeypatch.setattr(controls, 'registry', lambda _: [PressFeedProvider(cfg, Mock(request=request))])
    controls.collect(p, NOW+timedelta(minutes=5))
    assert saved(store) == before
    request.assert_not_called()


@pytest.mark.parametrize('previous', [
    {'status': 'disabled', 'error': 'old_static_reason', 'next_at': None},
    {'status': 'disabled', 'disabled_resume_state': 'invalid'},
    {'status': 'disabled', 'disabled_resume_state': {'status': 'disabled'}},
    {'status': 'disabled', 'disabled_resume_state': {'status': 'unexpected'}},
    {'status': 'disabled', 'disabled_resume_state': {'cursor': 'unknown'}},
])
def test_missing_or_corrupt_resume_state_fails_closed(isolated, monkeypatch, previous):
    p, store = isolated
    seed(store, previous)
    cfg = configure(monkeypatch, True)
    request = Mock()
    monkeypatch.setattr(controls, 'registry', lambda _: [PressFeedProvider(cfg, Mock(request=request))])
    controls.collect(p, NOW)
    state = saved(store)
    assert state['status'] == 'requires_configuration'
    assert state['error'] == 'provider_resume_state_unavailable' and state['terminal'] is True
    request.assert_not_called()


def test_unknown_legacy_resume_does_not_grow_nested_history_or_retry(isolated, monkeypatch):
    p, store = isolated
    seed(store, {'status': 'disabled', 'error': 'old_static_reason', 'next_at': None})
    request = Mock()
    for _ in range(5):
        cfg = configure(monkeypatch, True)
        monkeypatch.setattr(controls, 'registry', lambda configs: [PressFeedProvider(cfg, Mock(request=request))] if configs else [])
        controls.collect(p, NOW)
        state = saved(store)
        assert state['error'] == 'provider_resume_state_unavailable' and state['terminal']
        assert 'disabled_resume_state' not in state
        configure(monkeypatch, False)
        controls.collect(p, NOW)
        assert saved(store)['disabled_resume_state'] == state
    request.assert_not_called()


def test_known_new_disabled_provider_can_be_enabled_normally(isolated, monkeypatch):
    p, store = isolated
    configure(monkeypatch, False)
    controls.collect(p, NOW)
    assert saved(store)['disabled_resume_state'] == {}
    cfg = configure(monkeypatch, True)
    request = Mock(return_value=b'<rss><channel/></rss>')
    monkeypatch.setattr(controls, 'registry', lambda _: [PressFeedProvider(cfg, Mock(request=request))])
    controls.collect(p, NOW+timedelta(minutes=1))
    assert saved(store)['status'] == 'ok'
    request.assert_called_once()


def test_disabled_reason_is_current_config_not_a_vendor_payment_claim(isolated, monkeypatch):
    p, store = isolated
    configure(monkeypatch, False)
    controls.collect(p, NOW)
    assert saved(store)['error'] == 'provider_not_enabled'
    assert 'license' not in saved(store)['error']
    monkeypatch.setenv('NEWS_EVENTS_PROVIDERS', 'globenewswire')
    monkeypatch.setenv('NEWS_EVENTS_PROVIDER_APPROVALS', '{}')
    controls.collect(p, NOW)
    assert saved(store)['error'] == 'approval_reference_missing'
    assert 'payment' not in saved(store)['error']


def test_disabled_approval_notice_is_once_and_hides_archived_http(monkeypatch, isolated):
    p, store = isolated
    seed(store, prior_state())
    notify = controls.notify_changes
    configure(monkeypatch, False)
    import ai_operations
    enqueue = Mock()
    monkeypatch.setattr(ai_operations, 'enqueue', enqueue)
    monkeypatch.setattr(controls, 'notify_changes', notify)
    controls.collect(p, NOW)
    controls.collect(p, NOW+timedelta(minutes=5))
    enqueue.assert_called_once()
    message = enqueue.call_args.args[1]
    assert 'DISABLED' in message and 'Reason: provider_not_enabled' in message
    assert 'HTTP: n/a' in message and 'HTTP: 403' not in message
    assert 'license_confirmation_required' not in message


@pytest.mark.parametrize('provider', ['globenewswire', 'prnewswire', 'yahoo_priority'])
def test_verified_company_grant_keeps_stock_gates_not_a_blanket_ban(isolated, provider):
    p, store = isolated
    source = BaseProvider(Config(provider, 'https://example.com/feed', provider, enabled=True, rights='approved')).normalize(
        dict(id='grant', url='https://example.com/articles/synthetic-grant-12345',
             title='Test Devices Incorporated Announces Inducement Grants', excerpt=GRANT_TEXT,
             published_at=NOW.isoformat()), NOW)
    eid = p.ingest(source, NOW)
    result = dict(related=True, title_he='החברה העניקה מענקים לעובדים', summary_he='החברה פרסמה מענקי תגמול.',
                  interpretation_he='אין זו המלצת מסחר.', sentiment='neutral', materiality='medium', relevance=.8)
    assert p.analyze(eid, lambda _: Analysis(result), NOW) == 'done'
    assert p.queue(eid, NOW) == [('important_stock_news', ['TST'])]
    with store.transaction(True) as c:
        c.execute('UPDATE ne_analysis SET result_json=? WHERE event_id=?',
                  (json.dumps({**result, 'materiality': 'low'}), eid))
    assert p.queue(eid, NOW) == []


@pytest.mark.parametrize('title,excerpt,expected', [
    ('US employment rises by 120000 in September', GRANT_TEXT, 'market'),
    ('Fed Powell: inflation outlook higher than last year', GRANT_TEXT, 'market'),
    ('Example Inc. reports quarterly earnings', GRANT_TEXT, 'earnings'),
    ('Example Inc. announces acquisition', GRANT_TEXT, 'merger'),
    ('How to use inducement grants?', GRANT_TEXT, 'unknown'),
    (GRANT, 'Employment in the wider economy rose last month.', 'business_update'),
])
def test_real_macro_stronger_corporate_events_and_opinion_remain_distinct(title, excerpt, expected):
    assert event_type(title, excerpt) == expected
