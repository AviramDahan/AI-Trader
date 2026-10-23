"""Independent recall regressions: isolated state and denied external effects."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import copy
import json
import socket
import sqlite3

import pytest

from news_events import macro_rules
from news_events.engine import Analysis, Pipeline
from news_events.model import Source, event_type
from news_events.store import Store


AT = datetime(2026, 10, 23, 11, tzinfo=timezone.utc)
# Public syntax reproduced with deliberately synthetic values, not live facts.
RATE_FORMS = (
    'RUSSIAN INTEREST RATE DECISION ACTUAL 13.25% (FORECAST 13%, PREVIOUS 13.50%) $MACRO|FJ',
    'Russia Holds Key Rate At 13.25%, As Expected',
)


@pytest.fixture(autouse=True)
def deny_external_work(monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', Mock(side_effect=AssertionError('No network')))
    monkeypatch.setattr(socket, 'getaddrinfo', Mock(side_effect=AssertionError('No DNS')))


@pytest.mark.parametrize('title', RATE_FORMS)
def test_literal_sovereign_rate_decision_reaches_macro_not_company_gate(title):
    assert macro_rules.market_headline(title) is True
    assert macro_rules.factual_macro_title(title) is True
    assert event_type(title, title) == 'market'


@pytest.mark.parametrize('title', (
    'Russia may hold key rate at 13.25%',
    'Will Russia hold key rate at 13.25%?',
    'Preview: Russia Holds Key Rate At 13.25%, As Expected',
    'Russia Holds Key Rate At NaN%, As Expected',
    'Russia Holds Key Rate At inf%, As Expected',
    'Russia Holds Key Rate At 13.25% tomorrow',
    'Russia Holds Key Rate At 13.25%, buy these bank stocks',
    'Russia Bank Corporation Holds Key Rate At 13.25%, As Expected',
    'Synthetic Corporation Holds Key Rate At 13.25%, As Expected',
    'RUSSIAN INTEREST RATE DECISION FORECAST 13.25% (FORECAST 13%, PREVIOUS 13.50%)',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 13.25 (FORECAST 13%, PREVIOUS 13.50%)',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 13.25% (FORECAST 13%)',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 13.25% (FORECAST 13%, PREVIOUS 13.50%) commentary',
    'Russia Holds Key Rate At 13.25%shares',
))
def test_rate_keywords_never_certify_preview_corporate_or_malformed_prose(title):
    assert macro_rules.market_headline(title) is False
    assert macro_rules.factual_macro_title(title) is False


@pytest.mark.parametrize('title', RATE_FORMS)
def test_new_rate_classification_preserves_real_pipeline_quality_and_no_replay(tmp_path, title):
    def connect():
        connection = sqlite3.connect(tmp_path/'recall.sqlite')
        connection.row_factory = sqlite3.Row
        return connection

    store = Store(connect, sandbox=True)
    store.install()
    pipeline = Pipeline(store, {'TEST': {'company': 'Synthetic Devices Incorporated'}},
                        lambda: (set(), set()), not_before=AT-timedelta(hours=6))
    source = Source('synthetic_relay', 'rate', 'https://example.invalid/rate',
                    'Synthetic retained relay', AT.isoformat(), AT.isoformat(), title, title,
                    event_type=event_type(title, title), rights='approved')
    eid = pipeline.ingest(source, AT)
    assert store.event(eid)['reason'] is None
    assert store.event(eid)['body']['company_identity'] == []
    result = dict(related=True, title_he='דיווח על החלטת הריבית',
                  summary_he='הדיווח מציין את שיעור הריבית שנקבע בהחלטה.',
                  interpretation_he='זהו דיווח מקור ולא המלצת השקעה.',
                  sentiment='neutral', materiality='low', relevance=.95)
    completion = Mock(return_value=Analysis(result))
    assert pipeline.analyze(eid, completion, AT) == 'done'
    assert pipeline.queue(eid, AT) == []
    assert store.event(eid)['reason'] == 'low_importance'
    assert pipeline.ingest(source, AT+timedelta(minutes=1)) == eid
    assert pipeline.analyze(eid, completion, AT+timedelta(minutes=1)) == 'done'
    completion.assert_called_once()
    assert store.event(eid)['reason'] == 'low_importance'


@pytest.fixture
def funnel_connection(tmp_path):
    def connect():
        c = sqlite3.connect(tmp_path/'funnel-independent.sqlite')
        c.row_factory = sqlite3.Row
        return c
    Store(connect, sandbox=True).install()
    c = connect()
    c.execute('CREATE TABLE scanner_telegram_outbox(dedupe_key TEXT PRIMARY KEY,event_type TEXT,status TEXT,sent_at TEXT)')
    c.execute('CREATE TABLE ne_outbox(dedupe_key TEXT PRIMARY KEY,event_id TEXT,version TEXT,topic TEXT,epoch INTEGER)')
    yield c
    c.close()


def funnel_event(c, name, status='blocked', reason='identity_unverified', age=2, version='v1'):
    at = (AT-timedelta(hours=age)).isoformat()
    c.execute('INSERT INTO ne_events VALUES(?,?,?,?,?,?,?)',
              (str(name), '{}', version, status, reason, at, at))


@pytest.mark.parametrize('unrelated_kind', ['trump_truth_post', 'sec_intelligence'])
def test_other_publication_paths_cannot_mask_silent_canonical_funnel(funnel_connection, unrelated_kind):
    from news_events.funnel_health import snapshot
    c = funnel_connection
    for n in range(50):
        funnel_event(c, n, status='analyzed', reason='irrelevant', age=4)
    c.execute('INSERT INTO scanner_telegram_outbox VALUES(?,?,?,?)',
              ('unrelated-path', unrelated_kind, 'sent', (AT-timedelta(minutes=1)).isoformat()))
    value = snapshot(c, AT)
    assert value['counts']['events'] == 50
    assert value['counts']['sent_window_notices'] == 0
    assert value['status'] == 'review_required'
    assert 'no_publication_with_input' in value['advisories']


@pytest.mark.parametrize('state,counts', [
    ('observed', {'events': 1, 'current_analysis_done': 2}),
    ('observed', {'events': 1, 'identity_unverified': 1, 'insufficient_information': 1}),
    ('observed', {}),
    ('no_input', {'events': 1}),
])
def test_private_projection_rejects_impossible_cohort_or_state(funnel_connection, state, counts):
    from news_events.funnel_health import snapshot, projection
    data = snapshot(funnel_connection, AT)
    value = copy.deepcopy(data)
    value['status'] = state
    value['counts'].update(counts)
    assert projection(value, AT)['status'] == 'unknown'


@pytest.fixture
def press_pipeline(tmp_path, monkeypatch):
    from news_events.press_feed import PressFeedProvider
    from news_events.providers import Config, PRNEWSWIRE_RSS_ENDPOINT
    monkeypatch.setenv('NEWS_PRNEWSWIRE_ACTIVATED_AT', (AT-timedelta(days=1)).isoformat())
    def connect():
        c = sqlite3.connect(tmp_path/'press-independent.sqlite')
        c.row_factory = sqlite3.Row
        return c
    store = Store(connect, sandbox=True)
    store.install()
    pipeline = Pipeline(store, {'TEST': {'company': 'Synthetic Devices Incorporated'}},
                        lambda: (set(), set()), not_before=AT-timedelta(days=1))
    before = dict(status='requires_configuration', terminal=True, http_status=301,
                  error='http_error', attempts=3, cursor='keep-cursor',
                  last_success=(AT-timedelta(hours=3)).isoformat(),
                  last_attempt=(AT-timedelta(hours=2)).isoformat(),
                  next_at=(AT-timedelta(hours=2)+timedelta(minutes=5)).isoformat(),
                  checkpoint_json=json.dumps({'prior_marker': 'preserved'}))
    with store.transaction(True) as c:
        c.execute('INSERT INTO ne_provider_state VALUES(?,?)', ('prnewswire', json.dumps(before)))
    config = Config('prnewswire', PRNEWSWIRE_RSS_ENDPOINT, 'Synthetic official feed',
                    enabled=True, rights='approved')
    return pipeline, store, before, config, PressFeedProvider


@pytest.mark.parametrize('failure_kind', ['timeout', 'rate_limited', 'crash'])
def test_prn_consumption_is_durable_before_effect_and_not_reset_by_restart(press_pipeline, failure_kind):
    from news_events.providers import ProviderFailure
    from news_events import provider_config
    pipeline, store, before, cfg, Provider = press_pipeline
    class Crash(BaseException):
        pass
    failures = {'timeout': ProviderFailure('transport_timeout'),
                'rate_limited': ProviderFailure('http_error', 429, 300), 'crash': Crash()}
    def saved():
        with store.transaction() as c:
            return json.loads(c.execute('SELECT state_json FROM ne_provider_state WHERE provider_id=?',
                                        ('prnewswire',)).fetchone()['state_json'])
    def attempted(endpoint):
        value = saved()
        assert value['terminal'] is True
        assert value['attempts'] == before['attempts']
        assert value['cursor'] == before['cursor']
        checkpoint = json.loads(value['checkpoint_json'])
        assert checkpoint['access_recovery_for'] == checkpoint['redirect_recovery_for'] == before['last_success']
        assert checkpoint['recovery_not_before'] == AT.isoformat()
        assert checkpoint['prior_marker'] == 'preserved'
        raise failures[failure_kind]
    transport = Mock(request=Mock(side_effect=attempted))
    provider = Provider(cfg, transport)
    if failure_kind == 'crash':
        with pytest.raises(Crash):
            pipeline.collect([provider], AT)
    else:
        pipeline.collect([provider], AT)
    assert saved()['terminal'] is True
    restored = provider_config.resumed(provider_config.suspended(saved(), 'provider_not_enabled'))
    with store.transaction(True) as c:
        c.execute('UPDATE ne_provider_state SET state_json=? WHERE provider_id=?',
                  (json.dumps(restored), 'prnewswire'))
    restarted = Pipeline(Store(store.connect, sandbox=True), pipeline.universe,
                         pipeline.membership, not_before=pipeline.not_before)
    restarted.collect([provider], AT+timedelta(days=1))
    transport.request.assert_called_once()


@pytest.mark.parametrize('change', [
    {'enabled': False}, {'rights': 'review_required'},
    {'endpoint': 'https://www.prnewswire.com/rss/news-releases-list.rss?token=secret'},
    {'endpoint': 'https://user@www.prnewswire.com/rss/news-releases-list.rss'},
    {'endpoint': 'https://127.0.0.1/rss/news-releases-list.rss'},
])
def test_prn_new_probe_never_overrides_approval_or_exact_endpoint(press_pipeline, change):
    from dataclasses import replace
    pipeline, _, _, cfg, Provider = press_pipeline
    transport = Mock()
    pipeline.collect([Provider(replace(cfg, **change), transport)], AT)
    transport.request.assert_not_called()


def test_funnel_cardinality_current_version_and_older_window_notices_are_separate(funnel_connection):
    from news_events.funnel_health import snapshot
    c = funnel_connection
    funnel_event(c, 'current', status='analyzed', reason=None, version='v2')
    funnel_event(c, 'older', status='analyzed', reason=None, age=8)
    for name, version, state in [('current', 'v1', 'failed'), ('current', 'v2', 'done'), ('older', 'v1', 'done')]:
        c.execute('INSERT INTO ne_analysis VALUES(?,?,?,?,?,?,?,?,?)',
                  (name, version, state, '{}', None, AT.isoformat(), AT.isoformat(), 0, 'synthetic'))
    for name, version, topic in [('current', 'v2', 'market_news'),
                                  ('current', 'v2', 'important_stock_news'),
                                  ('older', 'v1', 'market_news')]:
        key = name+topic
        c.execute('INSERT INTO ne_delivery VALUES(?,?,?,?,?,?)', (name, version, topic, '[]', 'outbox', AT.isoformat()))
        c.execute('INSERT INTO ne_outbox VALUES(?,?,?,?,?)', (key, name, version, topic, 1))
        c.execute('INSERT INTO scanner_telegram_outbox VALUES(?,?,?,?)',
                  (key, 'market_news', 'sent', (AT-timedelta(seconds=1)).isoformat()))
    statements = []
    c.set_trace_callback(statements.append)
    value = snapshot(c, AT)
    assert value['counts']['events'] == 1
    assert value['counts']['current_analysis_done'] == 1
    assert value['counts']['current_analysis_failed'] == 0
    assert value['counts']['routed_events'] == value['counts']['cohort_sent_events'] == 1
    assert value['counts']['sent_window_notices'] == 3
    assert all(query.lstrip().upper().startswith('SELECT') for query in statements)


def test_funnel_halfopen_window_and_activation_clamp(funnel_connection):
    from news_events.funnel_health import snapshot
    c = funnel_connection
    funnel_event(c, 'lower-bound', age=6)
    funnel_event(c, 'upper-bound', age=0)
    funnel_event(c, 'future', age=-.1)
    funnel_event(c, 'recent', age=.5)
    assert snapshot(c, AT)['counts']['events'] == 2
    narrowed = snapshot(c, AT, not_before=AT-timedelta(hours=1))
    assert narrowed['counts']['events'] == 1
    assert narrowed['window_start'] == (AT-timedelta(hours=1)).isoformat()
    assert snapshot(c, AT, not_before=AT+timedelta(seconds=1))['status'] == 'unknown'


@pytest.mark.parametrize('invalid_kind', ['missing', 'stale', 'future', 'malformed'])
def test_admin_funnel_missing_or_bad_evidence_is_unknown_not_zero(funnel_connection, invalid_kind):
    from admin_system_status import news_funnel
    from news_events.funnel_health import snapshot
    value = snapshot(funnel_connection, AT)
    now = AT
    if invalid_kind == 'missing':
        value = None
    elif invalid_kind == 'stale':
        now += timedelta(seconds=181)
    elif invalid_kind == 'future':
        now -= timedelta(seconds=6)
    else:
        value['counts']['events'] = True
        value['article_body'] = 'private-fixture'
    node = {'state': 'healthy', 'reason': 'recent_completed_check', 'metrics': {}}
    news_funnel(node, {'funnel': value}, now)
    assert node['state'] == 'unknown' and node['reason'] == 'news_funnel_unverified'
    assert all(v is None for v in node['metrics'].values())
    assert 'private-fixture' not in json.dumps(node)


def test_admin_funnel_cannot_clear_existing_failure_or_disabled_feed(funnel_connection):
    from admin_system_status import news_funnel
    from news_events.funnel_health import snapshot
    for state in ('failed', 'disabled', 'stale'):
        node = {'state': state, 'reason': 'existing-state', 'metrics': {}}
        news_funnel(node, {'funnel': snapshot(funnel_connection, AT)}, AT)
        assert node['state'] == state and node['reason'] == 'existing-state'


def test_actual_watch_records_recall_advisory_without_phase1_failback(tmp_path, monkeypatch):
    from news_events import watch, reporting
    import sys
    from types import SimpleNamespace
    path = tmp_path/'watch-independent.sqlite'
    def connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    Store(connect, sandbox=True).install()
    with connect() as c:
        c.executescript('''
            CREATE TABLE scanner_telegram_outbox(dedupe_key TEXT PRIMARY KEY,event_type TEXT,status TEXT,sent_at TEXT);
            CREATE TABLE ne_outbox(dedupe_key TEXT PRIMARY KEY,event_id TEXT,version TEXT,topic TEXT,epoch INTEGER);
            CREATE TABLE scanner_service_status(component TEXT,status TEXT,last_success_at TEXT,last_attempt_at TEXT,detail TEXT);
            CREATE TABLE ne_ai_call_links(event_id TEXT,call_id TEXT);
            CREATE TABLE ai_call_usage(call_id TEXT,timestamp TEXT,actual_cost REAL);
            CREATE TABLE scanner_news_providers(provider TEXT,status TEXT,last_success_at TEXT,next_check_at TEXT,error TEXT);
            CREATE TABLE scanner_settings(key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);
        ''')
        for n in range(100):
            funnel_event(c, n, age=4)
    monkeypatch.setattr(watch, 'connect', connect)
    monkeypatch.setattr(watch, 'state', lambda: {'mode': 'canonical', 'not_before': (AT-timedelta(hours=6)).isoformat()})
    monkeypatch.setattr(watch, 'queue_rows', lambda c: [])
    monkeypatch.setattr(reporting, 'health_report', lambda *args: dict(
        canonical_events=100, source_versions=100, known_cost=0, provider_health={}))
    failback = Mock(side_effect=AssertionError('Recall warning cannot trigger failback'))
    monkeypatch.setattr(watch, 'fail_back', failback)
    enqueue = Mock()
    monkeypatch.setitem(sys.modules, 'ai_operations', SimpleNamespace(enqueue=enqueue))
    value = watch.check(AT)
    assert value['alarms'] == []
    assert value['funnel']['status'] == 'review_required'
    failback.assert_not_called()
    enqueue.assert_called_once()
    assert enqueue.call_args.args[0] == watch.summary_key(AT)
    with connect() as c:
        saved = json.loads(c.execute("SELECT value_json FROM scanner_settings WHERE key='news_canonical_health'").fetchone()['value_json'])
    assert saved['funnel'] == value['funnel']
