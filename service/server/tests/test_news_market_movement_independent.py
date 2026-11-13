"""Independent synthetic movement coverage and unchanged publication gates."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import socket
import sqlite3
import subprocess
from unittest.mock import Mock

import pytest

from news_events.analysis import CanonicalAnalyzer
from news_events.engine import Pipeline, Policy, route
from news_events.factual_evidence import factual_title, sufficient
from news_events.macro_rules import market_headline, factual_macro_title
from news_events.model import Source, event_type
from news_events.store import Store

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
TITLE = 'Nasdaq nears one-month low as chip shares slide on financing concerns'
GOLD = 'Gold rebounds as yields dip and the dollar softens'


@pytest.fixture(autouse=True)
def no_live_work(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Independent movement fixtures forbid live work')
    monkeypatch.setattr(socket, 'getaddrinfo', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)
    monkeypatch.setattr('requests.sessions.Session.request', denied)
    monkeypatch.setattr('database.get_db_connection', denied)
    monkeypatch.setattr('news_quality.get_db_connection', denied)


def source(title=TITLE, **changes):
    values = dict(provider_id='synthetic_movement', source_id='fixture',
        url='https://example.invalid/news/movement-10001', publisher='Synthetic publisher',
        published_at=NOW.isoformat(), collected_at=NOW.isoformat(), title=title,
        source_excerpt='', event_type=event_type(title, ''), rights='approved')
    values.update(changes)
    return Source(**values)


def event(item):
    return dict(event_type=item.event_type, tickers=[], title=item.title,
        sources=[item.data()], normalized_evidence=[{'text':item.title}])


@pytest.fixture
def isolated(tmp_path):
    path = tmp_path / 'movement.sqlite'
    def connect():
        c = sqlite3.connect(path); c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON'); return c
    store = Store(connect, sandbox=True); store.install()
    return Pipeline(store, {}, lambda:(set(), set()), not_before=NOW-timedelta(days=1))


@pytest.mark.parametrize('title', [TITLE, GOLD,
    'Nasdaq 100 drops as chip shares retreat',
    'S&P 500 rises as bank shares gain',
    'Dow Jones falls as industrial shares weaken',
    'Gold prices climb as the dollar weakens',
    'Brent crude falls as supplies expand',
    'WTI crude rises as inventories decline',
    'Gold hits 3000',
    'Nasdaq reaches 12000',
    'Gold reaches a record high',
    'S&P 500 closes higher',
    'Nasdaq rises 2% today',
    'Gold traded at 3000'])
def test_actual_reported_index_or_commodity_move_is_title_evidence(title):
    item = source(title)
    assert item.event_type == 'market'
    assert market_headline(title) and factual_macro_title(title)
    assert factual_title(event(item)) and sufficient(event(item))


@pytest.mark.parametrize('title', [
    'Nasdaq Inc. reports earnings as revenue rises',
    'Gold Hart Copper agrees to buy Fixture Mining',
    'S&P Global announces a merger as revenue rises',
    'S&P Global reports higher EPS for the quarter',
    'Nasdaq-listed Fixture Ltd. shares rise after earnings',
    'Gold Star Holdings shares rebound after earnings',
    'Copper River Corporation shares climb after earnings',
    'Unidentified Company shares rise after earnings',
    'Nasdaq could rise if trading conditions improve',
    'Nasdaq is expected to climb tomorrow',
    'Analysts forecast gold prices will rise',
    'Gold forecast: prices rise next week',
    'S&P 500 may fall if data disappoint',
    'Nasdaq to surge tomorrow',
    'Gold prices set to rally tomorrow',
    'Could Nasdaq rise after the next meeting?',
    'Why gold prices rise in a changing world',
    'How to profit as Nasdaq rises',
    'My opinion: Gold rises next year',
    'Gold hits 3000 tomorrow',
    'Nasdaq rises 2% next week',
    'Gold reaches a record high tomorrow',
    'Gold hits 2jobs',
    'Gold hits 3000 next Monday',
    'Nasdaq rises 2% next Friday'])
def test_new_movement_rule_never_promotes_company_or_speculative_titles(title):
    # Other historical macro rules are not broadened by this new rule.
    assert not market_headline(title)
    assert not factual_macro_title(title)
    assert not factual_title(event(source(title)))


@pytest.mark.parametrize('changes', [
    {'rights':'review_required'}, {'rights':'internal_review'}, {'publisher':''},
    {'url':'not-a-url'}, {'published_at':'2026-10-15 12:00:00'},
    {'title':'Different unapproved observation'},
])
def test_title_gate_requires_its_own_approved_valid_same_source(changes):
    original = source(); body = event(original)
    body['sources'] = [replace(original, **changes).data()]
    assert not factual_title(body)
    assert not sufficient(body)


def test_absent_normalized_evidence_never_becomes_sufficient():
    body = event(source()); body['normalized_evidence'] = []
    assert not sufficient(body)


@pytest.mark.parametrize('field', ['rights', 'publisher', 'url', 'published_at'])
def test_missing_approval_or_source_metadata_fails_closed(field):
    body = event(source()); body['sources'][0].pop(field)
    assert not factual_title(body)
    assert not sufficient(body)


def test_approved_other_headline_cannot_lend_rights_to_unapproved_movement():
    body = event(source())
    body['sources'] = [source(rights='review_required').data(),
        source(title='Another unrelated observation', event_type='unknown').data()]
    assert not factual_title(body)
    assert not sufficient(body)


def test_new_rule_does_not_change_unidentified_corporate_ingestion(isolated):
    item = source('Gold Hart Copper agrees to buy Fixture Mining')
    eid = isolated.ingest(item, NOW)
    assert isolated.store.event(eid)['reason'] == 'identity_unverified'
    completion = Mock()
    assert isolated.analyze(eid, completion, NOW) == 'blocked'
    completion.assert_not_called()


@pytest.mark.parametrize('age_hours', [-1, 7])
def test_stale_or_future_movement_never_reaches_completion(isolated, age_hours):
    item = source(published_at=(NOW-timedelta(hours=age_hours)).isoformat())
    eid = isolated.ingest(item, NOW); completion = Mock()
    assert isolated.analyze(eid, completion, NOW) in ('blocked', 'stale_or_future')
    completion.assert_not_called()
    assert isolated.queue(eid, NOW) == []


def result(**changes):
    return dict(dict(related=True, title_he='מדד המניות נסוג ברקע חולשה במניות',
        summary_he='לפי הכותרת הסינתטית מדד המניות נסוג ברקע חולשה במניות.',
        interpretation_he='זהו תיאור של תנועה מדווחת ולא המלצת מסחר.',
        sentiment='negative', materiality='medium', relevance=.4), **changes)


def review(**changes):
    return dict(dict(faithful=True, fluent_hebrew=True, unsupported_claims=False,
        duplicate_of=0, material_new_fact=False, explanation='בדיקה סינתטית',
        scope_related=True), **changes)


def test_new_title_runs_existing_reviewer_once_and_preview_dedupes(isolated):
    item = source(); before = deepcopy(item.data()); eid = isolated.ingest(item, NOW)
    client = Mock(side_effect=[(result(), {}), (review(), {})])
    assert isolated.analyze(eid, CanonicalAnalyzer(client), NOW) == 'done'
    assert [c.args[0] for c in client.call_args_list] == ['source_analysis', 'quality_review']
    assert client.call_args_list[0].args[2]['title'] == TITLE
    assert item.data() == before
    assert isolated.deliver_preview(eid, NOW)[0]['topic'] == 'market_news'
    restarted = Pipeline(Store(isolated.store.connect, sandbox=True), {}, isolated.membership,
        not_before=isolated.not_before)
    assert restarted.ingest(item, NOW+timedelta(seconds=1)) == eid
    assert restarted.analyze(eid, CanonicalAnalyzer(client), NOW) == 'done'
    assert restarted.deliver_preview(eid, NOW) == []
    assert client.call_count == 2


@pytest.mark.parametrize('kind', ['numbers', 'review'])
def test_eligibility_never_bypasses_numeric_or_editor_quality(isolated, kind):
    eid = isolated.ingest(source(), NOW)
    draft = result(title_he='מדד המניות ירד בשיעור 77%') if kind=='numbers' else result()
    editor = review(unsupported_claims=True) if kind=='review' else review()
    client = Mock(side_effect=[(draft, {}), (editor, {}), (draft, {}), (editor, {})])
    assert isolated.analyze(eid, CanonicalAnalyzer(client), NOW) == 'failed'
    reason = isolated.store.event(eid)['reason']
    assert ('numbers_grounded' if kind=='numbers' else 'no_unsupported_claims') in reason
    assert client.call_count == 4
    assert isolated.deliver_preview(eid, NOW) == []


@pytest.mark.parametrize('score,expected', [(.299, []), (.30, [('market_news', [])])])
def test_existing_market_threshold_is_not_lowered(score, expected):
    assert Policy().market_relevance == .30
    routes, _ = route(event(source()), result(relevance=score), set(), set(), {}, Policy())
    assert routes == expected
