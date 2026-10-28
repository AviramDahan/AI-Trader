"""Failure usage is metadata only: no real model, network, DB or messages."""
import json
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_provider
import ai_routing

SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
          'required': ['ok'], 'additionalProperties': False}


def native(value=None, *, reason='length', prompt=71, output=1000):
    return dict(model=ai_routing.MODEL, model_digest=ai_routing.DIGEST,
                done=True, done_reason=reason,
                message={'content': json.dumps({'ok': True} if value is None else value)},
                prompt_eval_count=prompt, eval_count=output)


@pytest.fixture
def client(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('External work forbidden by usage metadata fixture')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr('database.get_db_connection', forbidden)
    monkeypatch.setattr(ai_provider.requests, 'post', forbidden)
    monkeypatch.setattr(ai_provider.requests, 'get', forbidden)
    monkeypatch.setattr('ai_budget.check', forbidden)
    monkeypatch.setattr('ai_budget.acquire_request_slot', forbidden)
    monkeypatch.setattr('news_forensics.capture', forbidden)
    monkeypatch.setenv('AI_INFERENCE_MODE', 'ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', 'true')
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-only')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL', 'synthetic-paid-never-called')
    monkeypatch.setattr(ai_routing, '_until', 0)
    monkeypatch.setattr(ai_routing, 'ready', lambda: True)
    ledger = Mock()
    monkeypatch.setattr('ai_operations.record', ledger)

    def install(responses):
        values = iter(responses)
        requests = []
        def relay(method, path, payload=None, **_kwargs):
            if method == 'GET' and path == '/health':
                return dict(protocol=1, ready=True, model=ai_routing.MODEL,
                    digest=ai_routing.DIGEST, capacity=1,
                    context_policy=ai_routing.CONTEXT_POLICY, context_length=8192)
            assert method == 'POST' and path == '/completion'
            requests.append(payload)
            return next(values)
        monkeypatch.setattr(ai_routing, 'relay', relay)
        return ledger, requests
    return install


def invoke(usage):
    return ai_provider.json_completion('Synthetic instruction', {}, schema=SCHEMA,
        max_attempts=1, structured_news=True, usage_sink=usage)


def test_truncated_local_keeps_available_counters_and_terminal_classification(client):
    ledger, requests = client([native()])
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated'):
        invoke(usage)
    assert len(requests) == ledger.call_count == 1
    assert requests[0]['predict'] == 1000
    assert usage['input_tokens'] == 71
    assert usage['output_tokens'] == 1000
    assert usage['local_finish_reason'] == 'length'
    assert usage['provider'] == 'ollama_relay'
    assert usage['cost'] == 0
    recorded = ledger.call_args.args[2]['usage']
    assert recorded == {'cost': 0, 'prompt_tokens': 71, 'completion_tokens': 1000}
    diagnostic = json.loads(ledger.call_args.args[5])
    assert diagnostic['reason'] == 'ai_output_truncated'
    assert diagnostic['local_finish_reason'] == 'length'


def test_positive_stop_preserves_existing_usage(client):
    ledger, requests = client([native(reason='stop', output=7)])
    usage = {}
    assert invoke(usage) == {'ok': True}
    assert len(requests) == ledger.call_count == 1
    assert usage['input_tokens'] == 71 and usage['output_tokens'] == 7
    assert usage['cost'] == 0 and usage['provider'] == 'ollama_relay'
    assert ledger.call_args.args[4] is True


@pytest.mark.parametrize('invalid', [None, True, False, -1, 1.0, float('nan'),
    float('inf'), float('-inf'), '71', {}, [], 10_000_001, 10**100])
def test_invalid_failure_counters_are_unknown_not_estimated(client, invalid):
    ledger, _ = client([native(prompt=invalid, output=invalid)])
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated'):
        invoke(usage)
    assert usage['input_tokens'] is None and usage['output_tokens'] is None
    assert usage['local_finish_reason'] == 'length'
    assert ledger.call_args.args[2]['usage'] == {
        'cost': 0, 'prompt_tokens': None, 'completion_tokens': None}


@pytest.mark.parametrize('count', [0, 1, 10_000_000])
def test_true_integer_metadata_bounds(client, count):
    ledger, _ = client([native(prompt=count, output=count)])
    usage = {}
    with pytest.raises(ValueError):
        invoke(usage)
    assert usage['input_tokens'] == usage['output_tokens'] == count
    assert ledger.call_args.args[2]['usage']['completion_tokens'] == count


@pytest.mark.parametrize('field', ['prompt_eval_count', 'eval_count'])
def test_missing_counter_remains_unknown_without_losing_other_counter(client, field):
    response = native()
    del response[field]
    ledger, _ = client([response])
    usage = {}
    with pytest.raises(ValueError):
        invoke(usage)
    assert usage['input_tokens'] == (None if field == 'prompt_eval_count' else 71)
    assert usage['output_tokens'] == (None if field == 'eval_count' else 1000)
    assert ledger.call_count == 1


@pytest.mark.parametrize('changes', [dict(model='other'), dict(model=None),
    dict(model_digest='0'*64), dict(model_digest=None), dict(done=False),
    dict(done=1), dict(done='true')])
def test_unverified_native_identity_does_not_lend_truncation_usage(client, changes):
    response = native()
    response.update(changes)
    ledger, _ = client([response])
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated'):
        invoke(usage)
    assert usage['input_tokens'] is None and usage['output_tokens'] is None
    assert 'local_finish_reason' not in usage
    assert 'local_finish_reason' not in json.loads(ledger.call_args.args[5])


def test_exception_bridge_never_attaches_body_or_content(client):
    response = native()
    response['message'] = {'content': 'PRIVATE_SENTINEL', 'tool_calls': ['PRIVATE_SENTINEL']}
    response['messages'] = ['PRIVATE_SENTINEL']
    client([response])
    with pytest.raises(ValueError) as caught:
        ai_routing.local_completion([{'role': 'user', 'content': 'PRIVATE_SENTINEL'}], SCHEMA, 1000)
    assert str(caught.value) == 'ai_output_truncated'
    assert vars(caught.value) == {'local_failure_usage': {
        'done_reason': 'length', 'prompt_eval_count': 71, 'eval_count': 1000}}
    assert 'PRIVATE_SENTINEL' not in repr(vars(caught.value))


@pytest.mark.parametrize('metadata', [None, [], 'PRIVATE_SENTINEL',
    {'done_reason': 'PRIVATE_SENTINEL', 'eval_count': 1000},
    {'done_reason': True, 'eval_count': 1000}])
def test_provider_revalidates_hostile_exception_metadata(client, monkeypatch, metadata):
    ledger, _ = client([])
    error = ValueError('ai_output_truncated')
    error.local_failure_usage = metadata
    monkeypatch.setattr(ai_routing, 'local_completion', Mock(side_effect=error))
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated'):
        invoke(usage)
    assert usage['input_tokens'] is None and usage['output_tokens'] is None
    assert 'local_finish_reason' not in usage
    assert 'PRIVATE_SENTINEL' not in repr(usage) + ledger.call_args.args[5]


def test_provider_drops_extra_fields_and_revalidates_counters(client, monkeypatch):
    ledger, _ = client([])
    error = ValueError('ai_output_truncated')
    error.local_failure_usage = dict(done_reason='length', prompt_eval_count=True,
        eval_count=23, body={'content': 'PRIVATE_SENTINEL'}, cost=999, messages=['PRIVATE_SENTINEL'])
    monkeypatch.setattr(ai_routing, 'local_completion', Mock(side_effect=error))
    usage = {}
    with pytest.raises(ValueError):
        invoke(usage)
    assert usage['input_tokens'] is None and usage['output_tokens'] == 23
    assert usage['cost'] == 0
    assert 'PRIVATE_SENTINEL' not in repr(usage) + repr(ledger.call_args)


def test_paid_response_usage_and_contract_are_unchanged(client, monkeypatch):
    from news_structured_envelope import FUNCTION_NAME
    ledger, requests = client([])
    monkeypatch.setattr(ai_routing, 'ready', lambda: False)
    check = Mock()
    slot = Mock()
    monkeypatch.setattr('ai_budget.check', check)
    monkeypatch.setattr('ai_budget.acquire_request_slot', slot)
    response = Mock()
    response.json.return_value = {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'content': None, 'tool_calls': [{'type': 'function', 'function': {
            'name': FUNCTION_NAME, 'arguments': '{"ok":true}'}}]}}],
        'usage': {'cost': .001, 'prompt_tokens': 12, 'completion_tokens': 8}}
    post = Mock(return_value=response)
    monkeypatch.setattr(ai_provider.requests, 'post', post)
    usage = {}
    assert invoke(usage) == {'ok': True}
    assert usage['input_tokens'] == 12 and usage['output_tokens'] == 8
    assert usage['provider'] == 'openrouter' and usage['cost'] == .001
    assert 'local_finish_reason' not in usage
    assert requests == [] and post.call_count == ledger.call_count == 1
    assert post.call_args.kwargs['json']['max_tokens'] == 1000
    check.assert_called_once()
    slot.assert_called_once()


def test_finish_metadata_does_not_follow_local_failure_into_paid_retry(client, monkeypatch):
    ledger, requests = client([native()])
    monkeypatch.setattr('ai_budget.check', Mock())
    monkeypatch.setattr('ai_budget.acquire_request_slot', Mock())
    monkeypatch.setattr(ai_provider.time, 'sleep', lambda _: None)
    post = Mock()
    post.return_value.json.return_value = {'choices': [{'finish_reason': 'stop',
        'message': {'content': '{"ok":true}'}}],
        'usage': {'cost': .001, 'prompt_tokens': 12, 'completion_tokens': 8}}
    monkeypatch.setattr(ai_provider.requests, 'post', post)
    usage = {}
    assert ai_provider.json_completion('Synthetic', {}, schema=SCHEMA,
        max_attempts=2, usage_sink=usage) == {'ok': True}
    assert usage['provider'] == 'openrouter'
    assert 'local_finish_reason' not in usage
    assert len(requests) == post.call_count == 1 and ledger.call_count == 2
    assert json.loads(ledger.call_args_list[0].args[5])['local_finish_reason'] == 'length'


def test_finish_metadata_does_not_survive_sink_reuse_on_positive_stop(client):
    ledger, requests = client([native(), native(reason='stop', output=7)])
    usage = {}
    with pytest.raises(ValueError):
        invoke(usage)
    assert usage['local_finish_reason'] == 'length'
    assert invoke(usage) == {'ok': True}
    assert usage['input_tokens'] == 71 and usage['output_tokens'] == 7
    assert 'local_finish_reason' not in usage
    assert len(requests) == ledger.call_count == 2


DRAFT = dict(related=True, title_he='דיווח בדיקה', summary_he='זהו דיווח בדיקה.',
    interpretation_he='זהו פירוש זהיר.', sentiment='neutral', materiality='low', relevance=.4)
REVIEW = dict(faithful=False, fluent_hebrew=True, unsupported_claims=False,
    duplicate_of=0, material_new_fact=False, explanation='Synthetic check.', scope_related=True)
EVENT = dict(event_id='synthetic', evidence_version='v1', company_identity=[], tickers=[],
    event_type='market', title='Synthetic factual report',
    normalized_evidence=[{'text': 'Synthetic factual report.'}], conflicts=[])


@pytest.mark.parametrize('stage', ['editorial_repair', 'repair_review'])
def test_exact_terminal_canonical_paths_keep_usage_without_another_call(client, stage):
    from news_events.analysis import AnalysisFailure, CanonicalAnalyzer
    from news_events.runtime import completion
    from news_structured_envelope import output_instruction
    responses = [native(DRAFT, reason='stop'), native(REVIEW, reason='stop')]
    expected = ['source_analysis', 'quality_review', 'editorial_repair']
    if stage == 'editorial_repair':
        responses += [native(DRAFT)]
    else:
        responses += [native(DRAFT, reason='stop'), native(REVIEW)]
        expected += ['repair_review']
    ledger, requests = client(responses)
    with pytest.raises(AnalysisFailure) as caught:
        CanonicalAnalyzer(completion, contract=lambda _: ' '+output_instruction())(EVENT)
    assert caught.value.safe_reason == 'completion_failed:'+stage+':ai_output_truncated'
    assert [r['stage'] for r in caught.value.calls] == expected
    assert len(requests) == ledger.call_count == len(expected)
    assert caught.value.calls[-1]['input_tokens'] == 71
    assert caught.value.calls[-1]['output_tokens'] == 1000
    assert caught.value.calls[-1]['local_finish_reason'] == 'length'
    assert caught.value.calls[-1]['provider'] == 'ollama_relay'
    assert all(r['predict'] == 1000 for r in requests)


@pytest.mark.parametrize('provider,finish', [('ollama_relay', 'PRIVATE_SENTINEL'),
    ('openrouter', 'length'), ('ollama_relay', True)])
def test_canonical_metric_finish_field_is_fixed_allowlist(provider, finish):
    from news_events.analysis import CanonicalAnalyzer
    usage = dict(provider=provider, local_finish_reason=finish)
    client = Mock(side_effect=[(DRAFT, usage), ({**REVIEW, 'faithful': True}, usage)])
    result = CanonicalAnalyzer(client)(EVENT)
    assert all('local_finish_reason' not in r for r in result.calls)
