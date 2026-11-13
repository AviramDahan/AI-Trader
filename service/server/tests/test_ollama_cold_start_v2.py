"""Bounded cold start negotiation; all time/native traffic is synthetic."""
import importlib.util
import os
from pathlib import Path
import subprocess
from types import ModuleType, SimpleNamespace

import pytest
import requests


def gateway():
    root = Path(__file__).resolve().parents[3]
    baseline = os.getenv('COLD_START_BASELINE')
    if baseline:
        source = subprocess.check_output(['git', 'show', baseline+':scripts/ollama_inference_gateway.py'], cwd=root)
        module = ModuleType('cold_gateway_baseline')
        exec(compile(source, '<immutable gateway baseline>', 'exec'), module.__dict__)
        return module
    spec = importlib.util.spec_from_file_location('cold_gateway_v2', root/'scripts/ollama_inference_gateway.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native(module, *, resident=False, duration=70, metadata_delay=0):
    clock = SimpleNamespace(now=100.0)
    module.time = SimpleNamespace(monotonic=lambda: clock.now)
    engine = module.Inference()
    calls = []
    def http(method, path, body=None, timeout=2):
        calls.append((method, path, body, timeout))
        if method == 'GET':
            clock.now += metadata_delay
            if path == '/api/tags':
                return {'models': [{'name': module.MODEL, 'digest': module.DIGEST}]}
            if path == '/api/version':
                return {'version': '0.40.7'}
            if path == '/api/ps':
                return {'models': [{'name': module.MODEL, 'digest': module.DIGEST,
                                    'context_length': 8192}] if resident else []}
            raise AssertionError(path)
        assert engine.slot.locked() and path == '/api/chat' and body['messages']
        assert body['keep_alive'] == '2m' and body['options']['num_ctx'] == 8192
        assert body['options']['temperature'] == 0 and body['think'] is False
        clock.now += min(duration, timeout)
        if duration > timeout:
            raise requests.Timeout('synthetic_native_deadline')
        return {'model': module.MODEL, 'done': True, 'done_reason': 'stop',
                'message': {'role': 'assistant', 'content': '{"ok":true}'}}
    engine.http = http
    return engine, clock, calls


def payload(module, protocol=2):
    return dict(protocol=protocol, model=module.MODEL, digest=module.DIGEST,
        messages=[{'role': 'user', 'content': 'Synthetic cold fixture'}],
        schema={'type': 'object'}, predict=16, request_id='synthetic-cold-v2')


def test_versioned_cold_request_can_finish_after_legacy_45_seconds():
    module = gateway()
    engine, clock, calls = native(module)
    result = engine.complete(payload(module))
    assert result['done'] and result['gateway_protocol'] == 2
    assert result['gateway_request_budget_seconds'] == 120
    assert clock.now == 170 and len([c for c in calls if c[0] == 'POST']) == 1
    assert engine.last_request == dict(protocol=2, cold=True, phase='post_identity',
        outcome='completed', budget_seconds=120, elapsed_ms=70000)


@pytest.mark.parametrize('protocol,resident,budget', [(1, False, 45), (1, True, 45), (2, True, 45), (2, False, 120)])
def test_no_deadline_extension_for_legacy_or_warm_requests(protocol, resident, budget):
    module = gateway()
    engine, clock, calls = native(module, resident=resident, duration=200)
    with pytest.raises(requests.Timeout):
        engine.complete(payload(module, protocol))
    assert clock.now == 100+budget and not engine.slot.locked()
    assert engine.last_request['outcome'] == 'deadline_exceeded'
    assert len([c for c in calls if c[0] == 'POST']) == 1


def test_budget_includes_fresh_metadata_not_cached_residency():
    module = gateway()
    engine, clock, calls = native(module, metadata_delay=1, duration=70)
    engine.available = engine.loaded = True  # Stale warm observation before native expiry.
    engine.at = clock.now
    engine.complete(payload(module))
    sent = next(c for c in calls if c[0] == 'POST')
    assert sent[3] == 116  # tags/version/ps plus pre-identity tags consumed4s.
    assert engine.last_request['cold'] is True and engine.last_request['elapsed_ms'] == 75000


def capabilities(router):
    return dict(protocol=1, ready=True, model=router.MODEL, digest=router.DIGEST,
        capacity=1, context_policy=router.CONTEXT_POLICY, context_length=8192,
        completion_policy='bounded_cold_start_v2', supported_completion_protocols=[1, 2],
        completion_timeout_seconds=120)


def completion(router):
    return dict(model=router.MODEL, model_digest=router.DIGEST, done=True,
        done_reason='stop', message={'content':'{"ok":true}'},
        gateway_protocol=2, gateway_request_budget_seconds=120)


def client(monkeypatch, *, duration=70, changes=None, response_changes=None):
    import ai_routing as router
    if os.getenv('COLD_START_BASELINE'):
        root = Path(__file__).resolve().parents[3]
        source = subprocess.check_output(['git', 'show', os.environ['COLD_START_BASELINE']+':service/server/ai_routing.py'], cwd=root)
        router = ModuleType('cold_client_baseline')
        exec(compile(source, '<immutable client baseline>', 'exec'), router.__dict__)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(router, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    health = capabilities(router)
    health.update(changes or {})
    body = completion(router)
    body.update(response_changes or {})
    calls=[]
    def relay(method, path, payload=None, timeout=2):
        calls.append((method,path,payload,timeout))
        if method == 'GET':
            clock.now += 1
            return health
        clock.now += duration
        return body
    monkeypatch.setattr(router, 'relay', relay)
    return router, clock, calls


def test_actual_client_negotiates_one_cold_completion_and_total_budget(monkeypatch):
    router, clock, calls = client(monkeypatch)
    value, _ = router.local_completion([{'role':'user','content':'Synthetic fixture'}],None,16)
    assert value == {'ok': True} and calls[1][2]['protocol'] == 2
    assert calls[1][3] == 124 and len(calls) == 2 and clock.now == 171


@pytest.mark.parametrize('changes', [
    {'completion_policy':None}, {'completion_timeout_seconds':120.0},
    {'completion_timeout_seconds':True}, {'supported_completion_protocols':[True,2]},
    {'context_length':4096}, {'digest':'unapproved'}, {'model':'unapproved'},
])
def test_unknown_or_malformed_caps_do_not_extend_legacy_budget(monkeypatch, changes):
    router, _, calls = client(monkeypatch,duration=1,changes=changes)
    router.local_completion([{'role':'user','content':'Synthetic fixture'}],None,16)
    assert calls[1][2]['protocol'] == 1 and calls[1][3] <= 50 and len(calls) == 2


@pytest.mark.parametrize('response_changes', [{'gateway_protocol':True}, {'gateway_request_budget_seconds':120.0}, {'gateway_protocol':1}])
def test_negotiated_response_cannot_silently_downgrade(monkeypatch, response_changes):
    router, _, calls = client(monkeypatch,duration=1,response_changes=response_changes)
    with pytest.raises(ValueError,match='invalid_response_structure'):
        router.local_completion([{'role':'user','content':'Synthetic fixture'}],None,16)
    assert len(calls) == 2


def test_late_v2_result_rejected_without_an_extra_post(monkeypatch):
    router, _, calls = client(monkeypatch,duration=125)
    with pytest.raises(requests.Timeout):
        router.local_completion([{'role':'user','content':'Synthetic fixture'}],None,16)
    assert len(calls) == 2


def test_reported_warm_response_keeps_legacy_freshness_deadline(monkeypatch):
    router, _, calls = client(monkeypatch,duration=70,
        response_changes={'gateway_request_budget_seconds':45})
    with pytest.raises(requests.Timeout):
        router.local_completion([{'role':'user','content':'Synthetic fixture'}],None,16)
    assert len(calls) == 2
