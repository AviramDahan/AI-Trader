"""Final-review contracts with denied network and synthetic provider responses."""
import copy
import json
import socket
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_operations
import ai_routing
import final_ai
from review_rationale import Validator
from stock_scanner import validate_ai_decision


HOLD = dict(action='HOLD', confidence=.9, news_sentiment=0, news_relevance=.9,
            time_horizon='1-4 weeks', reason='Synthetic insufficient confirmation.',
            entry_price_relation='equal', entry_price_concern='none')
RECORD = ai_operations.record


def response_body(content=None):
    return {'id': 'synthetic-generation', 'choices': [{'finish_reason': 'stop',
        'message': {'content': json.dumps(HOLD) if content is None else content}}],
        'usage': {'prompt_tokens': 101, 'completion_tokens': 32, 'cost': .001}}


@pytest.fixture
def cloud(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Audit network denied')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    monkeypatch.setenv('AI_INFERENCE_MODE', 'cloud_only')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER', 'openrouter')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_MODEL', 'synthetic-only')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-only')
    monkeypatch.setattr('ai_budget.check', Mock())
    monkeypatch.setattr('ai_budget.acquire_request_slot', Mock())
    ledger = Mock()
    monkeypatch.setattr(ai_operations, 'record', ledger)
    monkeypatch.setattr(ai_operations, 'enqueue', Mock())
    monkeypatch.setattr(final_ai, 'persist', Mock())
    monkeypatch.setattr(final_ai.time, 'sleep', Mock())
    post = Mock(return_value=Mock(json=Mock(return_value=response_body())))
    monkeypatch.setattr(final_ai.requests, 'post', post)
    return post, ledger


def review():
    return final_ai.review([{'role': 'user', 'content': 'Synthetic immutable facts.'}],
        Validator({'relation': 'equal'}, lambda value: validate_ai_decision(value, 'BUY')))


@pytest.mark.parametrize('content', [
    json.dumps(HOLD).replace('"action": "HOLD"', '"action": "HOLD", "action": "BUY"'),
    json.dumps(HOLD).replace('"confidence": 0.9', '"confidence": 0.1, "confidence": 0.9'),
    json.dumps(dict(HOLD, confidence=float('nan'))),
    json.dumps(dict(HOLD, confidence=float('inf'))),
])
def test_ambiguous_or_nonfinite_json_cannot_return_a_decision(cloud, content):
    post, ledger = cloud
    post.return_value = Mock(json=Mock(return_value=response_body(content)))
    with pytest.raises(final_ai.SchemaFailure):
        review()
    assert post.call_count == ledger.call_count == 2
    assert all(call.args[4] is False for call in ledger.call_args_list)


def invalid_envelopes():
    body = response_body()
    yield dict(body, choices=body['choices'] * 2)
    for finish in ('length', 'content_filter', None):
        bad = copy.deepcopy(body)
        bad['choices'][0]['finish_reason'] = finish
        yield bad
    bad = copy.deepcopy(body)
    del bad['choices'][0]['finish_reason']
    yield bad
    for field, value in (('refusal', 'Synthetic refusal'), ('tool_calls', [{'type': 'function'}]),
                         ('function_call', {'name': 'unexpected'}), ('content', ''), ('content', None)):
        bad = copy.deepcopy(body)
        bad['choices'][0]['message'][field] = value
        yield bad
    yield dict(body, choices=[])
    yield dict(body, choices=[None])
    yield dict(body, choices=[{'finish_reason': 'stop', 'message': None}])
    yield []


@pytest.mark.parametrize('body', list(invalid_envelopes()))
def test_invalid_cloud_envelope_fails_closed_with_shared_attempt_limit(cloud, body):
    post, ledger = cloud
    post.return_value = Mock(json=Mock(return_value=body))
    with pytest.raises(final_ai.SchemaFailure):
        review()
    assert post.call_count == ledger.call_count == 2
    assert ledger.call_args_list[0].kwargs['retry'] is False
    assert ledger.call_args_list[1].kwargs['retry'] is True


def test_valid_cloud_hold_uses_one_attempt(cloud):
    post, ledger = cloud
    result = review()
    assert all(result[key] == value for key, value in HOLD.items())
    assert post.call_count == ledger.call_count == 1
    assert ledger.call_args.args[4] is True


def test_invalid_envelope_then_valid_hold_keeps_usage_and_two_attempts(cloud):
    post, ledger = cloud
    bad = response_body()
    bad['choices'][0]['finish_reason'] = 'length'
    post.side_effect = [Mock(json=Mock(return_value=bad)), Mock(json=Mock(return_value=response_body()))]
    trace = final_ai.new_trace('synthetic-scan', 'FIXTURE', 1)
    token = final_ai.TRACE.set(trace)
    try:
        assert review()['action'] == 'HOLD'
    finally:
        final_ai.TRACE.reset(token)
    assert post.call_count == ledger.call_count == len(trace['attempts']) == 2
    assert [attempt['result'] for attempt in trace['attempts']] == ['error', 'validated']
    assert final_ai._total(trace['attempts'], 'input_tokens') == 202
    assert final_ai._total(trace['attempts'], 'estimated_cost') == .002
    assert ledger.call_args_list[0].args[2]['usage']['cost'] == .001


def test_semantic_direction_conflict_is_not_repaired(cloud):
    post, ledger = cloud
    post.return_value = Mock(json=Mock(return_value=response_body(json.dumps(dict(HOLD, action='SELL')))))
    with pytest.raises(ValueError, match='direction conflicts'):
        review()
    assert post.call_count == ledger.call_count == 1


def test_rationale_repair_cannot_promote_hold(cloud):
    post, ledger = cloud
    bad = dict(HOLD, entry_price_relation='above')
    post.side_effect = [Mock(json=Mock(return_value=response_body(json.dumps(bad)))),
                       Mock(json=Mock(return_value=response_body(json.dumps(dict(HOLD, action='BUY')))))]
    with pytest.raises(ValueError, match='rationale_repair_changed_decision'):
        review()
    assert post.call_count == ledger.call_count == 2


def test_local_capacity_then_invalid_cloud_does_not_add_third_attempt(cloud, monkeypatch):
    post, ledger = cloud
    monkeypatch.setenv('AI_INFERENCE_MODE', 'ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', 'true')
    monkeypatch.setattr(ai_routing, '_until', 0)
    def relay(method, path, *args, **kwargs):
        if path == '/health':
            return dict(protocol=1, ready=True, model=ai_routing.MODEL,
                digest=ai_routing.DIGEST, capacity=1, context_policy=ai_routing.CONTEXT_POLICY,
                context_length=8192)
        raise ai_routing.LocalCapacity('local_context_capacity')
    monkeypatch.setattr(ai_routing, 'relay', relay)
    bad = response_body()
    bad['choices'][0]['finish_reason'] = 'length'
    post.return_value = Mock(json=Mock(return_value=bad))
    with pytest.raises(final_ai.SchemaFailure):
        review()
    assert post.call_count == 1 and ledger.call_count == 2
    assert ledger.call_args_list[0].args[2]['usage']['cost'] == 0
    assert ledger.call_args_list[1].args[2]['usage']['cost'] == .001


@pytest.mark.parametrize('malformed', ['truncated', 'non_object', 'malformed_usage',
    'generation_list', 'generation_object', 'generation_number', 'generation_oversized',
    'malformed_model_metadata'])
def test_failed_and_repaired_calls_enter_actual_temporary_ledger_once(cloud, tmp_path, monkeypatch, malformed):
    import database
    post, _ = cloud
    monkeypatch.setattr(database, 'DATABASE_URL', '')
    monkeypatch.setattr(database, '_SQLITE_DB_PATH', str(tmp_path / 'audit.db'))
    database.init_database()
    ddl = (Path(final_ai.__file__).parent / 'migrations' / '003_ai_operations.sql').read_text()
    with database.get_db_connection() as conn:
        for statement in ddl.split(';'):
            if statement.strip():
                conn.execute(statement)
    monkeypatch.setattr(ai_operations, 'record', RECORD)
    bad = response_body()
    bad['choices'][0]['finish_reason'] = 'length'
    if malformed == 'non_object':
        bad = []
    elif malformed == 'malformed_usage':
        bad['usage'] = []
    elif malformed.startswith('generation_'):
        bad['id'] = {'generation_list': [], 'generation_object': {},
                     'generation_number': 123, 'generation_oversized': 'x' * 257}[malformed]
    elif malformed == 'malformed_model_metadata':
        bad.update(model={'unexpected': True}, provider=['unexpected'])
    post.side_effect = [Mock(json=Mock(return_value=bad)), Mock(json=Mock(return_value=response_body()))]
    assert review()['action'] == 'HOLD'
    with database.get_db_connection() as conn:
        rows = conn.execute('SELECT call_id,task,actual_cost,success,generation_id FROM ai_call_usage ORDER BY timestamp').fetchall()
    assert len(rows) == len({row['call_id'] for row in rows}) == post.call_count == 2
    assert [row['task'] for row in rows] == ['final_stock_review', 'retry_repair']
    assert [row['success'] for row in rows] == [0, 1]
    assert [row['actual_cost'] for row in rows] == [None if malformed in {'non_object', 'malformed_usage'} else .001, .001]
    if malformed.startswith('generation_'):
        assert rows[0]['generation_id'] is None
    assert rows[1]['generation_id'] == 'synthetic-generation'


@pytest.mark.parametrize('value', [None, [], {}, 1, '', ' ', 'x' * 257])
def test_invalid_provider_identifier_is_unknown_not_a_durable_object(value):
    assert final_ai._metadata_string(value) is None


def test_valid_provider_identifier_keeps_exact_provenance():
    assert final_ai._metadata_string('synthetic-generation-1') == 'synthetic-generation-1'
