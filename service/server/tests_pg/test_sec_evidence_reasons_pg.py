"""Same SEC adapter/engine on isolated PostgreSQL, never a live provider."""
from datetime import timedelta
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_sec_evidence_reasons import CASES, NOW, XML, URL, seeded, retained


@pytest.mark.parametrize('reason,raw,url', CASES, ids=[case[0] for case in CASES])
def test_pg_extraction_reason_commits_terminal_state_without_replay(pg, reason, raw, url):
    from database import get_db_connection
    from news_events.engine import Pipeline
    from news_events.evidence import SECEvidence
    from news_events.store import Store
    store = Store(get_db_connection, sandbox=True)
    store.install()
    pipeline, event_id = seeded(store)
    before = store.event(event_id)
    provider = SECEvidence('fixture@example.invalid', Mock(return_value=(raw, url)), lambda: NOW)
    assert pipeline.enrich(event_id, [provider], NOW) is False
    state, metrics, counts = retained(store, provider, before['body'])
    assert state['error'] == reason and state['terminal'] is True
    assert state['attempts'] == 1 and state['next_at'] == (NOW + timedelta(seconds=120)).isoformat()
    assert metrics == [{'reason': reason, 'http_status': None}]
    assert counts == {'ne_evidence_cache': 0, 'ne_analysis': 0, 'ne_delivery': 0, 'ne_sources': 1}
    # A fresh full application object on a new connection sees the same hold.
    restarted = Pipeline(Store(get_db_connection, sandbox=True), pipeline.universe,
                         pipeline.membership, not_before=pipeline.not_before)
    assert restarted.enrich(event_id, [provider], NOW + timedelta(days=1)) is False
    assert provider.fetcher.call_count == 1
    assert retained(store, provider, before['body']) == (state, metrics, counts)
    assert store.event(event_id)['evidence_version'] == before['evidence_version']
    with get_db_connection() as conn:
        for table in ('scanner_signals', 'scanner_orders', 'scanner_trades', 'scanner_fills',
                      'scanner_telegram_outbox', 'ai_call_usage'):
            assert conn.execute('SELECT COUNT(*) n FROM ' + table).fetchone()['n'] == 0


def test_pg_unknown_extractor_reason_does_not_persist_document_text(pg, monkeypatch):
    import news_evidence
    from database import get_db_connection
    from news_events.evidence import SECEvidence
    from news_events.store import Store
    store = Store(get_db_connection, sandbox=True)
    store.install()
    pipeline, event_id = seeded(store)
    monkeypatch.setattr(news_evidence, 'extract', Mock(side_effect=news_evidence.EvidenceError('PRIVATE_SYNTHETIC_SENTINEL')))
    provider = SECEvidence('fixture@example.invalid', Mock(return_value=(XML, URL)), lambda: NOW)
    assert pipeline.enrich(event_id, [provider], NOW) is False
    state, metrics, _ = retained(store, provider, store.event(event_id)['body'])
    assert state['error'] == 'EvidenceError' and state['terminal'] is True
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in json.dumps([state, metrics])
