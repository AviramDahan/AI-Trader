"""Synthetic SEC extraction failures retain diagnostics, not new eligibility."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_events.engine import Pipeline
from news_events.evidence import SECEvidence
from news_events.model import Source
from news_events.store import Store
from news_evidence import EvidenceError

NOW = datetime(2026, 10, 16, 15, tzinfo=timezone.utc)
URL = 'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/form4.xml'
XML = ('<ownershipDocument><documentType>4</documentType><issuer>'
       '<issuerCik>123456</issuerCik><issuerName>Fixture Corp</issuerName>'
       '<issuerTradingSymbol>FIX</issuerTradingSymbol></issuer>'
       '<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common</value>'
       '</securityTitle></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>')
HTML = ('<ix:nonnumeric name="dei:EntityCentralIndexKey">123456</ix:nonnumeric>'
        '<ix:nonnumeric name="dei:TradingSymbol">FIX</ix:nonnumeric><p>Item 1.01</p>')
CASES = [
    ('unsafe_xml', '<!DOCTYPE fixture>' + XML, URL),
    ('invalid_xml', '<ownershipDocument>', URL),
    ('unsupported_document', XML.replace('>4</documentType>', '>144</documentType>'), URL),
    ('issuer_mismatch', XML.replace('>123456</issuerCik>', '>999999</issuerCik>'), URL),
    ('no_transaction_facts', XML[:XML.index('<nonDerivativeTable>')] + '</ownershipDocument>', URL),
    ('excerpt_too_large', XML.replace('</ownershipDocument>', '<footnotes><footnote>' + 'x' * 2100 +
                                   '</footnote></footnotes></ownershipDocument>'), URL),
    ('tabular_layout_unsupported', HTML + '<table><tr><td>100</td></tr></table>', URL.replace('.xml', '.htm')),
    ('insufficient_excerpt', HTML, URL.replace('.xml', '.htm')),
    ('unsafe_url', XML, 'https://example.invalid/form4.xml'),
    ('unsupported_filing_url', XML, URL.replace('.xml', '.txt')),
]


def seeded(store):
    pipeline = Pipeline(store, {'FIX': {'company': 'Fixture Corp', 'cik': '123456'}},
                        lambda: (set(), set()), not_before=NOW - timedelta(days=1))
    event_id = pipeline.ingest(Source('fixture', 'one', URL, 'Fixture', NOW.isoformat(),
        NOW.isoformat(), 'Fixture Corp Form 4', 'Fixture Corp filed Form 4.',
        tickers=('FIX',), cik='123456', event_type='regulatory', rights='approved'), NOW)
    assert event_id is not None
    return pipeline, event_id


def retained(store, provider, event):
    with store.transaction() as conn:
        state = json.loads(conn.execute('SELECT state_json FROM ne_provider_state WHERE provider_id=?',
                           ('evidence:' + provider.cache_key(event),)).fetchone()['state_json'])
        metrics = [json.loads(row['data_json']) for row in conn.execute(
            "SELECT data_json FROM ne_metrics WHERE stage='enrichment' AND result='failed'")]
        counts = {table: conn.execute('SELECT COUNT(*) n FROM ' + table).fetchone()['n']
                  for table in ('ne_evidence_cache', 'ne_analysis', 'ne_delivery', 'ne_sources')}
    return state, metrics, counts


@pytest.fixture
def store(tmp_path):
    def connect():
        conn = sqlite3.connect(tmp_path / 'isolated.sqlite')
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn
    value = Store(connect, sandbox=True)
    value.install()
    return value


@pytest.mark.parametrize('reason,raw,url', CASES, ids=[case[0] for case in CASES])
def test_known_extraction_reason_is_terminal_persisted_and_restart_safe(store, reason, raw, url):
    pipeline, event_id = seeded(store)
    before = pipeline.store.event(event_id)
    fetcher = Mock(return_value=(raw, url))
    provider = SECEvidence('fixture@example.invalid', fetcher, lambda: NOW)
    assert pipeline.enrich(event_id, [provider], NOW) is False
    state, metrics, counts = retained(store, provider, before['body'])
    assert state == {'next_at': (NOW + timedelta(seconds=120)).isoformat(),
                     'status': 'degraded', 'attempts': 1, 'error': reason, 'terminal': True}
    assert metrics == [{'reason': reason, 'http_status': None}]
    assert counts == {'ne_evidence_cache': 0, 'ne_analysis': 0, 'ne_delivery': 0, 'ne_sources': 1}
    assert store.event(event_id)['evidence_version'] == before['evidence_version']
    restarted = Pipeline(Store(store.connect, sandbox=True), pipeline.universe,
                         pipeline.membership, not_before=pipeline.not_before)
    assert restarted.enrich(event_id, [provider], NOW + timedelta(days=1)) is False
    assert fetcher.call_count == 1
    assert retained(store, provider, before['body']) == (state, metrics, counts)


@pytest.mark.parametrize('reason', ['PRIVATE_SYNTHETIC_SENTINEL', '', None, ['invalid_xml']])
def test_unknown_extraction_reason_remains_generic_without_text(store, monkeypatch, reason):
    import news_evidence
    pipeline, event_id = seeded(store)
    error = EvidenceError('unknown')
    error.reason = reason
    monkeypatch.setattr(news_evidence, 'extract', Mock(side_effect=error))
    provider = SECEvidence('fixture@example.invalid', Mock(return_value=(XML, URL)), lambda: NOW)
    assert pipeline.enrich(event_id, [provider], NOW) is False
    state, metrics, _ = retained(store, provider, store.event(event_id)['body'])
    assert state['error'] == 'EvidenceError' and state['terminal'] is True
    assert metrics == [{'reason': 'EvidenceError', 'http_status': None}]
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in json.dumps([state, metrics])


def test_fetch_retry_after_is_unchanged_and_extraction_stays_local(store):
    pipeline, event_id = seeded(store)
    fetcher = Mock(side_effect=EvidenceError('http_error', 429, 900, True))
    provider = SECEvidence('fixture@example.invalid', fetcher, lambda: NOW)
    assert pipeline.enrich(event_id, [provider], NOW) is False
    state, metrics, _ = retained(store, provider, store.event(event_id)['body'])
    assert state['error'] == 'http_error' and state['terminal'] is False
    assert state['next_at'] == (NOW + timedelta(seconds=900)).isoformat()
    assert metrics == [{'reason': 'http_error', 'http_status': 429}]
    assert pipeline.enrich(event_id, [provider], NOW + timedelta(seconds=899)) is False
    assert fetcher.call_count == 1


def test_success_keeps_original_publication_and_cached_restart(store):
    pipeline, event_id = seeded(store)
    fetcher = Mock(return_value=(XML, URL))
    provider = SECEvidence('fixture@example.invalid', fetcher, lambda: NOW)
    assert pipeline.enrich(event_id, [provider], NOW) is True
    assert pipeline.enrich(event_id, [provider], NOW + timedelta(minutes=1)) is False
    assert fetcher.call_count == 1
    assert store.event(event_id)['body']['published_at'] == NOW.isoformat()
