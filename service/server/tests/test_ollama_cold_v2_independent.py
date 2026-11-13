"""Independent adversarial v2 boundaries; no actual socket/model/DB activity."""
import pytest
import requests

from test_ollama_cold_start_v2 import gateway, native, payload, capabilities


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch):
    import socket
    def denied(*args, **kwargs):
        raise AssertionError('Independent v2 QA must not perform external IO')
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    monkeypatch.setattr(socket, 'socket', denied)


@pytest.mark.parametrize('models', [
    [{'name':'gemma4:12b','digest':'6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b','context_length':16384}],
    {'invalid':'not a model list'},
])
def test_fresh_native_metadata_rejects_bad_resident_even_with_warm_cache(models):
    g=gateway();engine,clock,calls=native(g,resident=True,duration=1)
    engine.available=engine.loaded=True;engine.at=clock.now
    original=engine.http
    def changed(method,path,body=None,timeout=2):
        if path=='/api/ps':return {'models':models}
        return original(method,path,body,timeout)
    engine.http=changed
    with pytest.raises(ValueError):engine.complete(payload(g))
    assert not any(c[0]=='POST' for c in calls) and not engine.slot.locked()
    assert engine.last_request['phase']=='metadata' and engine.last_request['cold'] is None


def test_valid_native_output_at_budget_boundary_cannot_skip_post_identity_gate():
    g=gateway();engine,clock,calls=native(g,duration=118,metadata_delay=.5)
    with pytest.raises(requests.Timeout):engine.complete(payload(g))
    assert clock.now==220 and not engine.slot.locked()
    assert engine.last_request['phase']=='post_identity'
    assert engine.last_request['outcome']=='deadline_exceeded'
    assert len([c for c in calls if c[0]=='POST'])==1


def test_gateway_overrides_forged_native_negotiation_metadata_with_actual_warm_budget():
    g=gateway();engine,_,_=native(g,resident=True,duration=1)
    original=engine.http
    def forged(method,path,body=None,timeout=2):
        result=original(method,path,body,timeout)
        if method=='POST':result.update(gateway_protocol=True,gateway_request_budget_seconds=999)
        return result
    engine.http=forged
    result=engine.complete(payload(g))
    assert type(result['gateway_protocol']) is int and result['gateway_protocol']==2
    assert result['gateway_request_budget_seconds']==45 and engine.last_request['cold'] is False


def test_busy_slot_and_boolean_protocol_never_start_native_work():
    g=gateway();engine,_,calls=native(g)
    with pytest.raises(ValueError):engine.complete(payload(g,True))
    assert calls==[] and engine.last_request is None
    engine.slot.acquire()
    try:
        with pytest.raises(ValueError):engine.complete(payload(g))
        assert calls==[] and engine.last_request is None
    finally:engine.slot.release()


def test_health_latency_exhausts_absolute_client_budget_before_post(monkeypatch):
    import ai_routing as r
    from types import SimpleNamespace
    clock=[100.0];calls=[]
    monkeypatch.setattr(r,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    def relay(method,path,payload=None,timeout=2):
        calls.append((method,path,timeout));assert method=='GET'
        clock[0]+=126
        return capabilities(r)
    monkeypatch.setattr(r,'relay',relay)
    with pytest.raises(requests.Timeout):r.local_completion([{'role':'user','content':'synthetic'}],None,16)
    assert calls==[('GET','/health',2)]


def test_gateway_rollback_after_negotiation_never_automatically_downgrades_or_retries(monkeypatch):
    import ai_routing as r
    from types import SimpleNamespace
    calls=[];monkeypatch.setattr(r,'time',SimpleNamespace(monotonic=lambda:100))
    def relay(method,path,payload=None,timeout=2):
        calls.append((method,path,payload))
        if method=='GET':return capabilities(r)
        assert payload['protocol']==2
        raise requests.ConnectionError('synthetic old gateway rejected v2')
    monkeypatch.setattr(r,'relay',relay)
    with pytest.raises(requests.ConnectionError):r.local_completion([{'role':'user','content':'synthetic'}],None,16)
    assert [c[0] for c in calls]==['GET','POST']


def test_last_request_diagnostic_has_only_bounded_metadata_no_input_or_native_body():
    g=gateway();engine,_,_=native(g,duration=1)
    p=payload(g);p['request_id']='private_request_sentinel';p['messages'][0]['content']='private_prompt_sentinel'
    engine.complete(p)
    assert set(engine.last_request)=={'protocol','cold','phase','outcome','budget_seconds','elapsed_ms'}
    assert 'sentinel' not in str(engine.last_request)
    assert engine.last_request['outcome']=='completed'
