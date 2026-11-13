"""Synthetic rate decisions only; no live replay, provider or model requests."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import socket
import sqlite3
from unittest.mock import Mock

import pytest
import requests

from news_events.engine import Analysis, Pipeline
from news_events.factual_evidence import factual_title
from news_events.macro_rules import factual_macro_title, market_headline
from news_events.model import Source, anchors, event_type
from news_events.store import Store


AT = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)
# These values and sources are synthetic, not retained Production observations.
BULLETIN = ('RUSSIAN INTEREST RATE DECISION ACTUAL 8.75% '
            '(FORECAST 8.5%, PREVIOUS 9.00%) $MACRO|FJ')
DECISION = 'Russia Holds Key Rate At 9.25%, As Expected'
POSITIVE = [
    BULLETIN,
    DECISION,
    'BRAZIL POLICY RATE DECISION ACTUAL 7% (FORECAST 7%, PREVIOUS 7.5%)',
    '‼ BREAKING: CANADIAN INTEREST RATE DECISION ACTUAL 2.25% (FORECAST 2.5%, PREVIOUS 2.5%)',
    'ECB POLICY RATE DECISION ACTUAL -0.25% (FORECAST -0.25%, PREVIOUS 0%)',
    'Bank of England leaves its policy rate unchanged at 2.5%',
    'Federal Reserve held the benchmark interest rate at 2.75%',
    'Bank of Japan raises its policy rate to 0.25% from 0%',
    'Australia cuts the cash rate to 1.75%, as expected',
    'South Africa maintained its key interest rate at 5.25%',
    'Reserve Bank of New Zealand lowered its policy rate to 2%',
]
NEGATIVE = [
    'Russian interest rate decision forecast 8.75%',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 8.75% (FORECAST 8.5%)',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 8.75 (FORECAST 8.5%, PREVIOUS 9%)',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 8.75% (FORECAST NaN%, PREVIOUS 9%)',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 8.75% (FORECAST 8.5%, PREVIOUS inf%)',
    'RUSSIAN INTEREST RATE DECISION ACTUAL 8.75% (FORECAST 8.5%, PREVIOUS 9%) buy now',
    'Preview: Russia holds key rate at 9.25%, as expected',
    'Russia expected to hold key rate at 9.25%',
    'Russia will hold key rate at 9.25%',
    'Russia may hold key rate at 9.25%',
    'If Russia holds key rate at 9.25%, stocks could rise',
    'Russia holds key rate at 9.25%?',
    'Russia holds key rate at 9.25% tomorrow',
    'Why Russia holds key rate at 9.25%',
    'Analyst says Russia holds key rate at 9.25%',
    'Russia Holdings cuts key rate to 9.25%',
    'Bank of America cuts interest rate to 4.5%',
    'Canada Mortgage Corporation cuts interest rate to 4.5%',
    'Russian Interest Rate Decision Incorporated reports earnings actual 8%',
    'Russia holds corporate deposit rate at 9.25%',
    'Russia holds key rate at 9.25%junk',
    'Russia holds key rate at NaN%',
    'Russia holds key rate at 9,25%',
    'Russia holds key rate at 9.25% and Synthetic Devices raises guidance',
    'Russia holds key rate at 9.25%, according to a prediction',
    'Russia holds key rate at 9.25%\nCompany announces record earnings',
]


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('external I/O forbidden in synthetic macro tests')
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', denied)


@pytest.mark.parametrize('title', POSITIVE)
def test_complete_actual_policy_rate_forms_are_market_facts(title):
    assert market_headline(title) is True
    assert factual_macro_title(title) is True
    assert event_type(title, title) == 'market'


@pytest.mark.parametrize('title', NEGATIVE)
def test_forecast_opinion_incomplete_and_company_forms_do_not_gain_macro_factuality(title):
    assert market_headline(title) is False
    assert factual_macro_title(title) is False


def make_pipeline(tmp_path):
    def connect():
        c = sqlite3.connect(tmp_path/'rates.sqlite')
        c.row_factory = sqlite3.Row
        return c
    store = Store(connect, sandbox=True)
    store.install()
    pipeline = Pipeline(store, {'TST': {'company': 'Synthetic Devices Incorporated'}},
                        lambda: (set(), set()), not_before=AT-timedelta(days=1))
    return pipeline, store


def source(title=BULLETIN, **overrides):
    item = Source('telegram_channels', 'synthetic-rate', 'https://example.invalid/rate-release',
                  'Synthetic approved relay', AT.isoformat(), AT.isoformat(), title, '',
                  event_type=event_type(title, ''), rights='approved')
    return replace(item, **overrides)


def analysis(**overrides):
    result = dict(related=True, title_he='דיווח על החלטת ריבית',
                  summary_he='המקור דיווח על החלטה והשווה אותה לנתון הקודם ולצפי.',
                  interpretation_he='זהו דיווח מקור ולא אימות ראשוני או המלצת מסחר.',
                  sentiment='neutral', materiality='low', relevance=.8)
    return Analysis({**result, **overrides})


@pytest.mark.parametrize('title', [BULLETIN, DECISION])
@pytest.mark.parametrize('quality,reason', [
    ({'materiality': 'low'}, 'low_importance'),
    ({'materiality': 'high', 'related': False}, 'irrelevant'),
    ({'materiality': 'high', 'relevance': .1}, 'below_market_threshold'),
])
def test_new_classification_reaches_only_mocked_review_keeps_existing_news_gates(tmp_path, title, quality, reason):
    pipeline, store = make_pipeline(tmp_path)
    item = source(title)
    eid = pipeline.ingest(item, AT)
    record = store.event(eid)
    assert record['status'] == 'pending' and record['reason'] is None
    assert record['body']['tickers'] == []
    assert factual_title(record['body']) is True
    analyzer = Mock(return_value=analysis(**quality))
    assert pipeline.analyze(eid, analyzer, AT) == 'done'
    assert pipeline.queue(eid, AT) == []
    assert store.event(eid)['reason'] == reason
    # Same exact source cannot create another model invocation or a new event.
    assert pipeline.ingest(item, AT) == eid
    assert pipeline.analyze(eid, analyzer, AT) == 'done'
    assert analyzer.call_count == 1


@pytest.mark.parametrize('change,expected', [
    ({'rights': 'review_required'}, 'insufficient_information'),
    ({'published_at': (AT-timedelta(hours=7)).isoformat()}, 'stale_or_future'),
    ({'published_at': (AT+timedelta(seconds=1)).isoformat()}, 'stale_or_future'),
])
def test_rights_freshness_and_future_guards_still_avoid_analysis(tmp_path, change, expected):
    pipeline, store = make_pipeline(tmp_path)
    eid = pipeline.ingest(source(**change), AT)
    analyzer = Mock(return_value=analysis(materiality='high'))
    assert pipeline.analyze(eid, analyzer, AT) in (expected, 'blocked')
    assert store.event(eid)['reason'] == expected
    analyzer.assert_not_called()


def test_reported_rate_does_not_invent_period_or_cross_source_dedupe_anchor():
    a = source()
    b = replace(a, source_id='synthetic-rate-b', url='https://example.invalid/another-release')
    # Headline-only numeric releases with unknown calendar period keep exact URL
    # identities; no same-country/day "decision" or invented primary-release key.
    assert not set(anchors(a, [])).intersection(anchors(b, []))


def test_oversized_and_nontext_titles_do_not_gain_macro_factuality():
    from news_events.macro_rules import reported_rate_decision
    for title in (None, 1, True, DECISION+' '*401):
        assert reported_rate_decision(title) is False
