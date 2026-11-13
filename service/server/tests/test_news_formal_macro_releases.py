"""Synthetic values in two retained formal release forms; no provider/model I/O."""
from datetime import datetime, timedelta, timezone
import sqlite3
from unittest.mock import Mock

import pytest

from news_events.engine import Analysis, Pipeline
from news_events.factual_evidence import factual_title, sufficient
from news_events.macro_rules import factual_macro_title, market_headline
from news_events.model import Source, event_type
from news_events.store import Store


AT = datetime(2026, 10, 23, 7, tzinfo=timezone.utc)
# Deliberately synthetic numbers; these are not saved Production articles.
PMI = '‼ BREAKING: FRENCH MANUFACTURING PMI FLASH ACTUAL 48.7 (FORECAST 49.9, PREVIOUS 50.2) $MACRO|FJ'
RETAIL = '❗ UK RETAIL SALES YOY ACTUAL -0.6% (FORECAST 0.2%, PREVIOUS 1.3%) $MACRO|FJ'


@pytest.mark.parametrize('title', [PMI, RETAIL])
def test_complete_reported_actual_release_is_macro_without_a_company(title):
    assert market_headline(title) is True
    assert factual_macro_title(title) is True
    assert event_type(title, title) == 'market'


@pytest.mark.parametrize('title', [PMI, RETAIL])
def test_existing_pipeline_can_reach_mocked_analysis_but_keeps_publication_gates(tmp_path, title):
    def connect():
        c = sqlite3.connect(tmp_path/'formal.sqlite')
        c.row_factory = sqlite3.Row
        return c
    store = Store(connect, sandbox=True)
    store.install()
    pipeline = Pipeline(store, {'TST': {'company': 'Synthetic Devices Incorporated'}},
                        lambda: (set(), set()), not_before=AT-timedelta(days=1))
    source = Source('telegram_channels', 'synthetic-formal', 'https://example.invalid/release',
                    'Synthetic approved relay', AT.isoformat(), AT.isoformat(), title, title,
                    event_type=event_type(title, title), rights='approved')
    eid = pipeline.ingest(source, AT)
    record = store.event(eid)
    assert record['reason'] is None and record['status'] == 'pending'
    assert sufficient(record['body']) is True
    result = dict(related=True, title_he='נתון כלכלי שפורסם בדיווח',
                  summary_he='הנתון בפועל הושווה לצפי ולנתון הקודם בדיווח.',
                  interpretation_he='זהו דיווח מקור; אין כאן הבטחת מסחר.',
                  sentiment='neutral', materiality='low', relevance=.8)
    analyzer = Mock(return_value=Analysis(result))
    assert pipeline.analyze(eid, analyzer, AT) == 'done'
    analyzer.assert_called_once()
    assert pipeline.queue(eid, AT) == []  # Existing low-materiality guard still applies.


@pytest.mark.parametrize('title', [
    'French manufacturing PMI forecast for next month is 48.7',
    'Preview: FRENCH MANUFACTURING PMI FLASH ACTUAL 48.7 (FORECAST 49.9, PREVIOUS 50.2)',
    'FRENCH MANUFACTURING PMI FLASH FORECAST 48.7 (FORECAST 49.9, PREVIOUS 50.2)',
    'FRENCH MANUFACTURING PMI FLASH ACTUAL NaN (FORECAST 49.9, PREVIOUS 50.2)',
    'FRENCH MANUFACTURING PMI FLASH ACTUAL 48.7 (FORECAST 49.9)',
    'FRENCH MANUFACTURING PMI FLASH ACTUAL 48.7 (FORECAST 49.9, PREVIOUS 50.2) buy now',
    'UK RETAIL SALES YOY EXPECTED -0.6% (FORECAST 0.2%, PREVIOUS 1.3%)',
    'UK RETAIL SALES YOY ACTUAL -0.6 (FORECAST 0.2%, PREVIOUS 1.3%)',
    'UK RETAIL SALES YOY ACTUAL inf% (FORECAST 0.2%, PREVIOUS 1.3%)',
    'UK RETAIL SALES YOY ACTUAL -0.6% (FORECAST 0.2%)',
    'Why are UK retail sales expected to improve?',
    'French Manufacturing PMI Corporation reports earnings ACTUAL 48.7 (FORECAST 49.9, PREVIOUS 50.2)',
    'UK Retail Sales Limited announces a new financing round',
])
def test_preview_opinion_incomplete_numbers_and_corporate_names_do_not_become_formal_release(title):
    assert market_headline(title) is False
    assert factual_macro_title(title) is False


def test_unknown_prose_never_inherits_factuality_from_the_macro_keyword():
    assert factual_title(dict(event_type='market', tickers=[], title='French PMI might surprise',
                              sources=[])) is False
