"""Independent synthetic metadata/privacy checks; no real inference or DB."""
import json
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_provider
import ai_routing

SECRET = 'PRIVATE_MODEL_CONTENT_MUST_NOT_SURVIVE'
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
          'required': ['ok'], 'additionalProperties': False}


def native(value=None, reason='length', **metadata):
    result = dict(model=ai_routing.MODEL, model_digest=ai_routing.DIGEST,
                  done=True, done_reason=reason,
                  message={'content': SECRET if reason == 'length' else json.dumps(value)},
                  prompt_eval_count=83, eval_count=17)
    result.update(metadata)
    return result


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('Real external work forbidden')
    for owner, name in [(socket, 'getaddrinfo'), (socket.socket, 'connect'),
                        (subprocess, 'run'), (subprocess, 'Popen')]:
        monkeypatch.setattr(owner, name, denied)
    monkeypatch.setattr('database.get_db_connection', denied)
    monkeypatch.setattr('ai_operations.enqueue', denied)
    monkeypatch.setattr('ai_budget.check', denied)
    monkeypatch.setattr('ai_budget.acquire_request_slot', denied)
    monkeypatch.setattr('news_forensics.capture', denied)
    monkeypatch.setattr(ai_provider.requests, 'get', denied)
    monkeypatch.setattr(ai_provider.requests, 'post', denied)
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    monkeypatch.setenv('AI_INFERENCE_MODE', 'ollama_first')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL', 'synthetic-paid-model')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-only')
    monkeypatch.setattr(ai_routing, 'ready', lambda: True)
    monkeypatch.setattr(ai_routing, '_until', 0)
    ledger = Mock()
    monkeypatch.setattr('ai_operations.record', ledger)
    relay = Mock()
    monkeypatch.setattr(ai_routing, 'relay', relay)
    return relay, ledger


def install(relay, response):
    relay.side_effect = lambda method, path, *args, **kwargs: (
        {'context_policy': ai_routing.CONTEXT_POLICY, 'context_length': 8192}
        if path == '/health' else response)


def test_actual_failed_counts_are_retained_not_configured_predict(isolated):
    relay, ledger = isolated
    install(relay, native())
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated') as caught:
        ai_provider.json_completion('Synthetic instruction', {}, schema=SCHEMA,
                                    max_attempts=1, usage_sink=usage)
    assert (usage['input_tokens'], usage['output_tokens']) == (83, 17)
    assert usage['local_finish_reason'] == 'length'
    assert ledger.call_count == 1
    assert ledger.call_args.args[2]['usage']['completion_tokens'] == 17
    assert json.loads(ledger.call_args.args[5])['local_finish_reason'] == 'length'
    assert SECRET not in repr(vars(caught.value)) + repr(usage) + repr(ledger.call_args)


def test_existing_stop_usage_positive_control(isolated):
    relay, ledger = isolated
    install(relay, native({'ok': True}, reason='stop'))
    usage = {}
    assert ai_provider.json_completion('Synthetic instruction', {}, schema=SCHEMA,
                                      max_attempts=1, usage_sink=usage) == {'ok': True}
    assert (usage['input_tokens'], usage['output_tokens']) == (83, 17)
    assert ledger.call_count == 1
    assert usage.get('local_finish_reason') is None


def failed_usage(relay, response):
    install(relay, response)
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated') as caught:
        ai_provider.json_completion('Synthetic instruction', {}, schema=SCHEMA,
                                    max_attempts=1, usage_sink=usage)
    assert SECRET not in repr(vars(caught.value)) + repr(usage)
    return usage, caught.value


class CounterSubclass(int):
    pass


@pytest.mark.parametrize('invalid', [True, False, -1, 1.25, '17', None, {},
                                    10_000_001, float('inf'), float('nan'), CounterSubclass(4)])
def test_malformed_native_counters_remain_unknown(isolated, invalid):
    relay, ledger = isolated
    usage, _ = failed_usage(relay, native(prompt_eval_count=invalid, eval_count=invalid,
                                        private_payload=SECRET))
    assert usage['input_tokens'] is None and usage['output_tokens'] is None
    assert usage['local_finish_reason'] == 'length'
    assert ledger.call_count == 1
    assert SECRET not in repr(ledger.call_args)


@pytest.mark.parametrize('counter', [0, 10_000_000])
def test_sanitizer_uses_metadata_bound_not_predict_limit(isolated, counter):
    relay, ledger = isolated
    usage, _ = failed_usage(relay, native(prompt_eval_count=counter, eval_count=counter))
    assert usage['input_tokens'] == usage['output_tokens'] == counter
    assert ledger.call_count == 1


@pytest.mark.parametrize('missing', ['prompt_eval_count', 'eval_count'])
def test_one_missing_counter_does_not_erase_other_verified_count(isolated, missing):
    relay, ledger = isolated
    response = native()
    response.pop(missing)
    usage, _ = failed_usage(relay, response)
    assert usage['input_tokens'] == (None if missing == 'prompt_eval_count' else 83)
    assert usage['output_tokens'] == (None if missing == 'eval_count' else 17)
    assert ledger.call_count == 1


@pytest.mark.parametrize('field,value', [('model', 'wrong-model'),
                                       ('model_digest', 'wrong-digest'), ('done', False), ('done', 1)])
def test_unverified_native_identity_keeps_old_failure_but_no_new_usage(isolated, field, value):
    relay, ledger = isolated
    usage, _ = failed_usage(relay, native(**{field: value}))
    assert usage['input_tokens'] is None and usage['output_tokens'] is None
    assert usage.get('local_finish_reason') is None
    assert 'local_finish_reason' not in json.loads(ledger.call_args.args[5])
    assert ledger.call_count == 1


def test_exception_contains_only_sanitized_metadata_not_native_body(isolated):
    relay, _ = isolated
    response = native(private_payload=SECRET, usage={'completion_tokens': SECRET})
    install(relay, response)
    with pytest.raises(ValueError, match='ai_output_truncated') as caught:
        ai_routing.local_completion([{'role': 'user', 'content': 'Synthetic'}], SCHEMA, 1000)
    metadata = caught.value.local_failure_usage
    assert metadata == {'prompt_eval_count': 83, 'eval_count': 17, 'done_reason': 'length'}
    assert type(metadata) is dict
    assert set(vars(caught.value)) == {'local_failure_usage'}
    assert SECRET not in str(caught.value) + repr(vars(caught.value))
    assert 'body' not in vars(caught.value) and 'message' not in metadata


@pytest.mark.parametrize('forged', [
    SECRET,
    {'prompt_eval_count': 83, 'eval_count': 17, 'done_reason': SECRET},
    {'prompt_eval_count': 83, 'eval_count': 17, 'done_reason': 'stop'},
])
def test_provider_revalidates_forged_exception_metadata(isolated, monkeypatch, forged):
    _, ledger = isolated
    error = ValueError('ai_output_truncated')
    error.local_failure_usage = forged
    monkeypatch.setattr(ai_routing, 'local_completion', Mock(side_effect=error))
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated') as caught:
        ai_provider.json_completion('Synthetic', {}, schema=SCHEMA,
                                    max_attempts=1, usage_sink=usage)
    assert usage['input_tokens'] is None and usage['output_tokens'] is None
    assert usage.get('local_finish_reason') is None
    assert ledger.call_count == 1
    assert SECRET not in repr(vars(caught.value)) + repr(usage) + repr(ledger.call_args)


@pytest.mark.parametrize('stage', ['editorial_repair', 'repair_review'])
def test_canonical_terminal_paths_keep_three_or_four_requests_and_numeric_calls(isolated, stage):
    from news_events.analysis import AnalysisFailure, CanonicalAnalyzer
    from news_events import runtime
    from news_events.call_context import CURRENT
    relay, ledger = isolated
    draft = dict(related=True, title_he='דיווח בדיקה', summary_he='זהו דיווח בדיקה.',
                 interpretation_he='זהו פירוש זהיר.', sentiment='neutral',
                 materiality='low', relevance=.4)
    review = dict(faithful=False, fluent_hebrew=True, unsupported_claims=False,
                  duplicate_of=0, material_new_fact=False, explanation='Synthetic correction.',
                  scope_related=True)
    responses = [native(draft, 'stop'), native(review, 'stop')]
    expected_stages = ['source_analysis', 'quality_review', 'editorial_repair']
    if stage == 'repair_review':
        responses.append(native(draft, 'stop'))
        expected_stages.append('repair_review')
    responses.append(native(prompt_eval_count=99, eval_count=37))
    iterator = iter(responses)
    generated = []
    def fake_relay(method, path, payload=None, **kwargs):
        if path == '/health':
            return {'context_policy': ai_routing.CONTEXT_POLICY, 'context_length': 8192}
        assert method == 'POST' and path == '/completion' and kwargs['timeout'] == 50
        generated.append(payload)
        return next(iterator)
    relay.side_effect = fake_relay
    event = dict(event_id='independent-synthetic', evidence_version='synthetic-v',
                 company_identity=[], tickers=[], event_type='market', title='Synthetic report',
                 normalized_evidence=[{'text': 'Synthetic report.'}], conflicts=[])
    with pytest.raises(AnalysisFailure) as caught:
        CanonicalAnalyzer(runtime.completion)(event)
    calls = caught.value.calls
    assert caught.value.safe_reason == 'completion_failed:' + stage + ':ai_output_truncated'
    assert [c['stage'] for c in calls] == expected_stages
    assert len(generated) == ledger.call_count == len(expected_stages)
    assert all(c['provider'] == 'ollama_relay' for c in calls)
    assert all(p['predict'] == 1000 for p in generated)
    assert calls[-1]['local_finish_reason'] == 'length'
    assert (calls[-1]['input_tokens'], calls[-1]['output_tokens']) == (99, 37)
    assert calls[-1]['success'] is False and calls[-1]['failure_reason'] == 'ai_output_truncated'
    assert ai_routing._until > 0  # Existing process-local cooldown is preserved.
    assert CURRENT.get() is None
    assert SECRET not in repr(calls) + repr(ledger.call_args_list)


def test_paid_truncation_retains_existing_usage_without_local_extension(isolated, monkeypatch):
    _, ledger = isolated
    monkeypatch.setenv('AI_INFERENCE_MODE', 'cloud_only')
    budget = Mock()
    slot = Mock()
    monkeypatch.setattr('ai_budget.check', budget)
    monkeypatch.setattr('ai_budget.acquire_request_slot', slot)
    paid_body = {'choices': [{'finish_reason': 'length', 'message': {'content': SECRET}}],
                 'usage': {'cost': .002, 'prompt_tokens': 121, 'completion_tokens': 55}}
    post = Mock(return_value=Mock(json=Mock(return_value=paid_body)))
    monkeypatch.setattr(ai_provider.requests, 'post', post)
    usage = {}
    with pytest.raises(ValueError, match='ai_output_truncated') as caught:
        ai_provider.json_completion('Synthetic', {}, schema=SCHEMA,
                                    max_attempts=1, usage_sink=usage)
    assert (usage['input_tokens'], usage['output_tokens'], usage['cost']) == (121, 55, .002)
    assert usage['provider'] == 'openrouter' and usage.get('local_finish_reason') is None
    assert 'local_finish_reason' not in json.loads(ledger.call_args.args[5])
    assert post.call_count == ledger.call_count == budget.call_count == slot.call_count == 1
    assert SECRET not in repr(vars(caught.value)) + repr(usage) + ledger.call_args.args[5]


def test_permitted_second_paid_success_does_not_inherit_local_finish_reason(isolated, monkeypatch):
    relay, ledger = isolated
    install(relay, native())
    budget = Mock()
    slot = Mock()
    monkeypatch.setattr('ai_budget.check', budget)
    monkeypatch.setattr('ai_budget.acquire_request_slot', slot)
    monkeypatch.setattr(ai_provider.time, 'sleep', lambda _seconds: None)
    response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
                'usage': {'cost': .002, 'prompt_tokens': 121, 'completion_tokens': 55}}
    post = Mock(return_value=Mock(json=Mock(return_value=response)))
    monkeypatch.setattr(ai_provider.requests, 'post', post)
    usage = {}
    assert ai_provider.json_completion('Synthetic', {}, schema=SCHEMA,
                                      max_attempts=2, usage_sink=usage) == {'ok': True}
    assert usage['provider'] == 'openrouter'
    assert (usage['input_tokens'], usage['output_tokens']) == (121, 55)
    assert usage.get('local_finish_reason') is None
    assert post.call_count == budget.call_count == slot.call_count == 1
    assert ledger.call_count == 2
    assert ledger.call_args_list[0].args[4] is False
    assert ledger.call_args_list[1].args[4] is True


def test_reused_sink_failed_then_stop_call_has_no_stale_finish_reason(isolated):
    relay, ledger = isolated
    usage, _ = failed_usage(relay, native())
    assert usage['local_finish_reason'] == 'length'
    install(relay, native({'ok': True}, reason='stop', prompt_eval_count=88, eval_count=18))
    assert ai_provider.json_completion('Synthetic', {}, schema=SCHEMA,
                                      max_attempts=1, usage_sink=usage) == {'ok': True}
    assert usage.get('local_finish_reason') is None
    assert (usage['input_tokens'], usage['output_tokens']) == (88, 18)
    assert ledger.call_count == 2
