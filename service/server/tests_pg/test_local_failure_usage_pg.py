"""Real disposable PostgreSQL persistence; native inference is entirely fake."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests


@pytest.mark.parametrize('stage', ['editorial_repair', 'repair_review'])
@pytest.mark.parametrize('failure_kind', ['length', 'transport'])
def test_failed_native_usage_survives_persistence_and_restart_without_publication(pg, monkeypatch, stage, failure_kind):
    import ai_routing
    from database import get_db_connection
    from news_events.analysis import CanonicalAnalyzer
    from news_events.engine import Pipeline
    from news_events.model import Source
    from news_events.runtime import completion, queue_outbox
    from news_events.store import Store

    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    monkeypatch.setenv('AI_INFERENCE_MODE', 'ollama_first')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-only')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL', 'synthetic-paid-never-called')
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'true')
    monkeypatch.setattr(ai_routing, 'ready', lambda: True)
    monkeypatch.setattr(ai_routing, '_until', 0)
    monkeypatch.setattr('ai_budget.check', Mock(side_effect=AssertionError('Paid request forbidden')))
    monkeypatch.setattr('ai_budget.acquire_request_slot', Mock(side_effect=AssertionError('Paid slot forbidden')))
    with get_db_connection() as c:
        assert c.execute('SELECT current_schema() AS name').fetchone()['name'].startswith('test_')
        c.execute("UPDATE ne_control SET mode='canonical',not_before=?,epoch=42 WHERE id=1",
                  ((now - timedelta(days=1)).isoformat(),))

    store = Store(get_db_connection, production=True)
    pipeline = Pipeline(store, {}, lambda: (set(), set()), not_before=now - timedelta(days=1))
    source = Source('synthetic_primary', 'local-failure-fixture',
                    'https://example.invalid/news/policy', 'Synthetic primary',
                    now.isoformat(), now.isoformat(),
                    'Central bank announces a policy decision',
                    'The central bank announces its latest policy decision and explains the available economic evidence.',
                    event_type='market', rights='approved')
    eid = pipeline.ingest(source, now)
    assert eid is not None
    draft = dict(related=True, title_he='הבנק המרכזי פרסם החלטה',
                 summary_he='הבנק פרסם את החלטתו והסביר את הרקע הכלכלי.',
                 interpretation_he='זהו מידע כלכלי ולא המלצת מסחר.',
                 sentiment='neutral', materiality='low', relevance=.4)
    review = dict(faithful=False, fluent_hebrew=True, unsupported_claims=False,
                  duplicate_of=0, material_new_fact=False, explanation='Synthetic correction.',
                  scope_related=True)

    def native(value, reason='stop'):
        return dict(model=ai_routing.MODEL, model_digest=ai_routing.DIGEST,
                    done=True, done_reason=reason,
                    message={'content': json.dumps(value)},
                    prompt_eval_count=143, eval_count=37)

    responses = [native(draft), native(review)]
    expected_stages = ['source_analysis', 'quality_review', 'editorial_repair']
    if stage == 'repair_review':
        responses.append(native(draft))
        expected_stages.append('repair_review')
    secret = 'PRIVATE_PARTIAL_OUTPUT_NOT_TO_PERSIST'
    terminal = native({'private': secret}, 'length')
    terminal['private_metadata'] = secret
    if failure_kind == 'transport':
        terminal = requests.ConnectionError('local_relay_unavailable')
        terminal.local_transport_failure = {'reason': 'relay_http_error', 'http_status': 503,
                                            'body': secret}
    responses.append(terminal)
    iterator = iter(responses)
    generated = []

    def relay(method, path, payload=None, **kwargs):
        if method == 'GET' and path == '/health':
            return dict(context_policy=ai_routing.CONTEXT_POLICY, context_length=8192)
        assert method == 'POST' and path == '/completion' and 0 < kwargs['timeout'] <= 50
        assert payload['predict'] == 1000
        generated.append(payload)
        value = next(iterator)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(ai_routing, 'relay', relay)
    assert pipeline.analyze(eid, CanonicalAnalyzer(completion), now) == 'failed'
    assert len(generated) == len(expected_stages)
    assert queue_outbox(pipeline, eid, now) == 0
    restarted = Pipeline(Store(get_db_connection, production=True), {}, pipeline.membership,
                         not_before=pipeline.not_before)
    assert restarted.ingest(source, now + timedelta(seconds=1)) == eid
    assert restarted.analyze(eid, CanonicalAnalyzer(completion), now + timedelta(seconds=1)) == 'quality_failed'
    assert queue_outbox(restarted, eid, now + timedelta(seconds=1)) == 0
    assert len(generated) == len(expected_stages)

    with get_db_connection() as c:
        calls = [dict(r) for r in c.execute('''SELECT l.stage,u.success,u.input_tokens,
            u.output_tokens,u.actual_cost,u.model,u.failure FROM ne_ai_call_links l
            JOIN ai_call_usage u ON u.call_id=l.call_id ORDER BY u.timestamp''')]
        assert [r['stage'] for r in calls] == expected_stages
        assert len(calls) == c.execute('SELECT count(*) AS n FROM ai_call_usage').fetchone()['n']
        assert all(r['model'].startswith('ollama/') and r['actual_cost'] == 0 for r in calls)
        failed = calls[-1]
        assert failed['success'] == 0
        diagnostic = json.loads(failed['failure'])
        if failure_kind == 'length':
            assert (failed['input_tokens'], failed['output_tokens']) == (143, 37)
            assert diagnostic['reason'] == 'ai_output_truncated'
            assert diagnostic['local_finish_reason'] == 'length'
        else:
            assert (failed['input_tokens'], failed['output_tokens']) == (None, None)
            assert diagnostic['exception'] == 'ConnectionError' and diagnostic['http_status'] is None
            assert diagnostic['local_transport'] == {'reason': 'relay_http_error', 'http_status': 503}
        metric = c.execute("SELECT data_json FROM ne_metrics WHERE event_id=? AND stage='analysis'", (eid,)).fetchone()
        saved = json.loads(metric['data_json'])['calls']
        assert [r['stage'] for r in saved] == expected_stages
        if failure_kind == 'length':
            assert saved[-1]['local_finish_reason'] == 'length'
            assert (saved[-1]['input_tokens'], saved[-1]['output_tokens']) == (143, 37)
        else:
            assert saved[-1]['failure_reason'] == 'local_transport_failed'
            assert 'local_finish_reason' not in saved[-1]
        analysis = c.execute('SELECT status,error,result_json FROM ne_analysis WHERE event_id=?', (eid,)).fetchone()
        assert analysis['status'] == 'failed'
        reason = 'ai_output_truncated' if failure_kind == 'length' else 'local_transport_failed'
        assert analysis['error'] == 'completion_failed:' + stage + ':' + reason
        alerts = [dict(r) for r in c.execute('SELECT status,attempts,message FROM admin_alerts')]
        assert len(alerts) == 1 and alerts[0]['status'] == 'pending' and alerts[0]['attempts'] == 0
        for table in ('ne_delivery', 'ne_outbox', 'scanner_telegram_outbox', 'scanner_signals',
                      'scanner_orders', 'scanner_trades', 'scanner_fills'):
            assert c.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'] == 0
        assert c.execute('SELECT count(*) AS n FROM ne_analysis').fetchone()['n'] == 1
        assert secret not in repr(calls) + metric['data_json'] + repr(dict(analysis)) + repr(alerts)
