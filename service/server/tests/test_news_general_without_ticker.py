"""Synthetic general-news policy: no provider, model, Telegram or trading I/O."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_events.engine import Analysis, Pipeline, Policy, route
from news_events.model import IdentityResolver
from news_events.store import Store
from signal_news import eligible_observations
from test_news_events import env, source, NOW, RESULT


TITLE = 'Example Robotics announces closure of its regional factory'
EXCERPT = ('Example Robotics announced the closure of its regional factory after losing '
           'a major supply contract, affecting production and its current workforce.')
GENERAL_RESULT = {**RESULT, 'title_he': 'חברת רובוטיקה מדווחת על סגירת מפעל',
                  'summary_he': 'החברה דיווחה על סגירת מפעל אזורי לאחר אובדן חוזה אספקה.',
                  'interpretation_he': 'הדיווח עשוי להשפיע על הייצור ועל כוח האדם; זו אינה המלצת מסחר.'}


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    import requests
    import socket
    import psycopg
    def denied(*args, **kwargs):
        raise AssertionError('No external I/O in synthetic general-news tests')
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(psycopg, 'connect', denied)


def item(**changes):
    return source(title=TITLE, source_excerpt=EXCERPT, event_type='business_update',
                  event_refs=(), **changes)


def test_general_publication_does_not_require_verified_stock_identity(env):
    p, s, members = env
    candidate = item(tickers=('AAPL',))  # Deliberately unverified provider hint.
    assert IdentityResolver(p.universe).resolve(candidate) == []
    eid = p.ingest(candidate, NOW)
    assert s.event(eid)['status'] == 'pending'
    body = s.event(eid)['body']
    assert body['event_type'] == 'business_update'
    assert body['tickers'] == body['company_identity'] == body['cik'] == []
    ai = Mock(return_value=Analysis(GENERAL_RESULT))
    assert p.analyze(eid, ai, NOW) == 'done'
    assert p.queue(eid, NOW) == [('market_news', [])]
    assert eligible_observations(s.event(eid), {'ticker': 'AAPL', 'company': 'Apple Inc.'}, 6, NOW) == []
    assert p.deliver_preview(eid, NOW)[0]['topic'] == 'market_news'
    restarted = Pipeline(Store(s.connect, sandbox=True), p.universe,
                         lambda: members, not_before=p.not_before)
    assert restarted.ingest(candidate, NOW + timedelta(minutes=1)) == eid
    assert restarted.analyze(eid, ai, NOW + timedelta(minutes=1)) == 'done'
    assert restarted.deliver_preview(eid, NOW + timedelta(minutes=1)) == []
    ai.assert_called_once()


@pytest.mark.parametrize('changes', [
    {'title': 'Why investors should watch Example Robotics?'},
    {'title': 'Example Robotics could be ready for a rally?'},
    {'source_excerpt': ''},
    {'source_excerpt': 'Factory closure announced.'},
    {'source_excerpt': '<b> </b>' * 20},
    {'event_type': 'unknown'},
    {'rights': 'review_required'},
    {'rights': 'internal_review'},
    {'publisher': ''},
    {'publisher': False},
    {'source_excerpt': ['not source text'] * 20},
    {'title': '  A company reports earnings'},
    {'title': 'Example Robotics announces employee inducement grants'},
])
def test_missing_identity_is_not_a_blanket_content_or_rights_bypass(env, changes):
    p, s, _ = env
    eid = p.ingest(replace(item(), **changes), NOW)
    ai = Mock(return_value=Analysis(RESULT))
    if eid is None:  # Malformed metadata was rejected before event creation.
        ai.assert_not_called()
        return
    assert p.analyze(eid, ai, NOW) != 'done'
    assert p.queue(eid, NOW) == []
    ai.assert_not_called()


@pytest.mark.parametrize('result,reason', [
    ({'related': False}, 'irrelevant'),
    ({'materiality': 'low'}, 'low_importance'),
    ({'relevance': .29}, 'below_market_threshold'),
])
def test_general_news_keeps_existing_editorial_gates(env, result, reason):
    p, s, _ = env
    eid = p.ingest(item(), NOW)
    assert p.analyze(eid, lambda _: Analysis({**RESULT, **result}), NOW) == 'done'
    assert p.queue(eid, NOW) == []
    assert s.event(eid)['reason'] == reason


@pytest.mark.parametrize('changes', [
    {'published_at': (NOW - timedelta(hours=7)).isoformat()},
    {'published_at': (NOW + timedelta(seconds=1)).isoformat()},
])
def test_general_news_keeps_freshness_and_future_rejection(env, changes):
    p, _, _ = env
    eid = p.ingest(replace(item(), **changes), NOW)
    ai = Mock(return_value=Analysis(RESULT))
    assert p.analyze(eid, ai, NOW) != 'done'
    assert p.queue(eid, NOW) == []
    ai.assert_not_called()


def test_existing_verified_company_and_true_macro_routes_are_unchanged(env):
    p, s, _ = env
    eid = p.ingest(source(), NOW)
    assert s.event(eid)['body']['tickers'] == ['AAPL']
    assert p.analyze(eid, lambda _: Analysis(RESULT), NOW) == 'done'
    assert p.queue(eid, NOW) == [('portfolio_watchlist', ['AAPL'])]
    assert route({'tickers': [], 'event_type': 'market'}, RESULT,
                 set(), set(), {}, Policy())[0] == [('market_news', [])]


def test_raw_unknown_event_cannot_obtain_general_route(env):
    p, s, _ = env
    eid = p.ingest(item(), NOW)
    body = s.event(eid)['body']
    body['event_type'] = 'unknown'
    assert route(body, RESULT, {'AAPL'}, {'AAPL'}, p.universe, p.policy)[0] == []


def test_unchanged_historical_identity_block_is_not_requeued(env):
    p, s, _ = env
    candidate = item()
    eid = p.ingest(candidate, NOW)
    with s.transaction(True) as c:
        c.execute("UPDATE ne_events SET status='blocked',reason='identity_unverified' WHERE event_id=?", (eid,))
    assert p.ingest(candidate, NOW + timedelta(minutes=1)) == eid
    assert s.event(eid)['status'] == 'blocked'
    assert s.event(eid)['reason'] == 'identity_unverified'
    ai = Mock()
    p.analyze(eid, ai, NOW + timedelta(minutes=1))
    ai.assert_not_called()


def test_no_ticker_story_runs_the_real_independent_market_quality_contract(env):
    from news_events.analysis import CanonicalAnalyzer
    p, s, _ = env
    eid = p.ingest(item(), NOW)
    review = dict(faithful=True, fluent_hebrew=True, unsupported_claims=False,
                  duplicate_of=0, material_new_fact=False, explanation='בדיקה סינתטית', scope_related=True)
    client = Mock(side_effect=[(GENERAL_RESULT, {}), (review, {})])
    assert p.analyze(eid, CanonicalAnalyzer(client), NOW) == 'done'
    assert client.call_count == 2
    context = client.call_args_list[0].args[2]
    assert context['scope'] == 'market' and context['verified_company_identity'] == []
    assert 'scope_related' in client.call_args_list[1].args[3]['required']
    assert p.queue(eid, NOW) == [('market_news', [])]


@pytest.mark.parametrize('key,value', [
    ('company_identity', [{'ticker': 'AAPL'}]), ('company_identity', None),
    ('cik', ['320193']), ('cik', None), ('sources', []), ('conflicts', ['different facts']),
])
def test_general_route_rejects_missing_inconsistent_or_contested_evidence(env, key, value):
    p, s, _ = env
    body = s.event(p.ingest(item(), NOW))['body']
    body[key] = value
    assert route(body, RESULT, set(), set(), p.universe, p.policy)[0] == []


@pytest.mark.parametrize('changes', [
    {'publisher': {'name': 'Not a string'}}, {'publisher': False},
    {'source_excerpt': ['not source text'] * 20},
    {'source_excerpt': {'invented_' + str(i): 'word' for i in range(20)}},
])
def test_retained_general_source_types_cannot_be_stringified_into_evidence(changes):
    from news_events.general_news import eligible_source
    assert eligible_source(replace(item(), **changes)) is False


def test_publication_key_is_exact_facts_time_destination_not_ticker_or_syndication_url(env):
    from news_events.general_news import publication_keys
    p, s, _ = env
    first = s.event(p.ingest(item(), NOW))
    other = replace(item(), provider_id='other', source_id='other', url='https://other.example/story')
    second = s.event(p.ingest(other, NOW))
    a = publication_keys(first['body'], first['evidence_version'], ['synthetic-destination', 42])
    assert a == publication_keys(second['body'], second['evidence_version'], ['synthetic-destination', 42])
    assert a != publication_keys(first['body'], first['evidence_version'], ['synthetic-destination', 43])
    assert a != publication_keys(first['body'], 'materially-corrected-version', ['synthetic-destination', 42])
    changed = {**first['body'], 'sources': [{**first['body']['sources'][0], 'published_at': (NOW + timedelta(minutes=1)).isoformat()}]}
    assert a != publication_keys(changed, first['evidence_version'], ['synthetic-destination', 42])
