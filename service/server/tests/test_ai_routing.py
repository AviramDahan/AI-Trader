"""Synthetic inference; no paid requests, workers, trading or Telegram."""
import copy
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import jsonschema
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_provider
import ai_routing as routing
import final_ai

SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
DECISION = dict(action='HOLD', confidence=.1, news_sentiment=0, news_relevance=.5,
                time_horizon='1-4 weeks', reason='Synthetic fixture, insufficient evidence.')


def native(value):
    return dict(model=routing.MODEL, model_digest=routing.DIGEST, done=True, done_reason='stop',
                message={'content':json.dumps(value)}, prompt_eval_count=12, eval_count=8)


def cloud(value):
    return Mock(json=Mock(return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
        'usage':{'cost':.001,'prompt_tokens':12,'completion_tokens':8}}))


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-only')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','existing-luna')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','openrouter')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_MODEL','existing-luna')
    monkeypatch.setattr(routing,'_until',0)
    relay=Mock(side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else native({'ok':True}))
    monkeypatch.setattr(routing,'relay',relay)
    paid=Mock(side_effect=AssertionError('Paid request forbidden'))
    monkeypatch.setattr(ai_provider.requests,'post',paid)
    budget=Mock();slot=Mock();ledger=Mock()
    monkeypatch.setattr('ai_budget.check',budget)
    monkeypatch.setattr('ai_budget.acquire_request_slot',slot)
    monkeypatch.setattr('ai_operations.record',ledger)
    monkeypatch.setattr(final_ai,'persist',Mock())
    monkeypatch.setattr(ai_provider.time,'sleep',lambda _:None)
    return relay,paid,budget,slot,ledger


def test_cloud_only_default_never_probes_local(fixture,monkeypatch):
    relay,paid,budget,slot,_=fixture
    monkeypatch.delenv('AI_INFERENCE_MODE')
    paid.side_effect=None;paid.return_value=cloud({'ok':True})
    assert ai_provider.json_completion('fixture',{},schema=SCHEMA)=={'ok':True}
    relay.assert_not_called();budget.assert_called_once();slot.assert_called_once()


@pytest.mark.parametrize('task',['news','translation','summary'])
def test_all_shared_tasks_local_and_no_paid_budget_dependency(fixture,task):
    relay,paid,budget,slot,ledger=fixture
    budget.side_effect=RuntimeError('paid_budget_exhausted')
    usage={}
    assert ai_provider.json_completion('fixture',{},schema=SCHEMA,task=task,usage_sink=usage)=={'ok':True}
    paid.assert_not_called();budget.assert_not_called();slot.assert_not_called()
    assert usage['provider']=='ollama_relay' and usage['model_digest']==routing.DIGEST and usage['cost']==0
    assert ledger.call_args.args[1].startswith('ollama/gemma4:12b@')
    assert ledger.call_args.args[2]['usage']['cost']==0


def test_canonical_native_contract_does_not_weaken_cloud_function_envelope(fixture):
    relay,paid,*_=fixture
    from news_structured_envelope import output_instruction
    ai_provider.json_completion('fixture '+output_instruction(),{},schema=SCHEMA,
        structured_news=True,news_json_wrapping=True,max_attempts=1)
    request=relay.call_args.args[2]
    assert 'submit_news_result' not in request['messages'][0]['content']
    assert request['schema']==SCHEMA
    paid.assert_not_called()


@pytest.mark.parametrize('failure',[requests.Timeout(),requests.ConnectionError(),ValueError('invalid_response_structure'),
    json.JSONDecodeError('bad','bad',0),jsonschema.ValidationError('synthetic')])
def test_local_failure_then_one_cloud_attempt_with_shared_allowance(fixture,failure):
    relay,paid,budget,slot,ledger=fixture
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else (_ for _ in ()).throw(failure)
    paid.side_effect=None;paid.return_value=cloud({'ok':True})
    usage={}
    assert ai_provider.json_completion('fixture',{},schema=SCHEMA,usage_sink=usage)=={'ok':True}
    assert paid.call_count==1 and ledger.call_count==2
    assert usage['provider']=='openrouter' and usage['fallback_reason'] in {'local_transport_failed','local_schema_failed'}
    budget.assert_called_once();slot.assert_called_once()
    assert ledger.call_args_list[0].args[2]['usage']['cost']==0
    assert ledger.call_args_list[1].kwargs['retry'] is True


def test_one_request_stage_never_adds_hidden_fallback_generation(fixture):
    relay,paid,_,_,ledger=fixture
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else native({'wrong':True})
    with pytest.raises(ValueError,match='schema_failed'):
        ai_provider.json_completion('fixture',{},schema=SCHEMA,max_attempts=1)
    paid.assert_not_called();assert ledger.call_count==1 and not routing.ready()


def test_native_truncation_retains_terminal_canonical_policy(fixture):
    relay,paid,*_=fixture
    body=native({'ok':True});body['done_reason']='length'
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else body
    from news_events.analysis import schema_reason
    with pytest.raises(ValueError) as caught:
        ai_provider.json_completion('fixture',{},schema=SCHEMA,max_attempts=1)
    assert schema_reason(caught.value) is None
    paid.assert_not_called()


@pytest.mark.parametrize('state',[{'ready':False},{'capacity':0},{'model':'other'},{'digest':'0'*64},{'protocol':2}])
def test_unavailable_model_capacity_or_protocol_uses_cloud_before_generation(fixture,state):
    relay,paid,budget,*_=fixture
    relay.return_value=dict(protocol=1,ready=True,model=routing.MODEL,digest=routing.DIGEST,capacity=1,**{})
    relay.return_value.update(state);relay.side_effect=None
    paid.side_effect=None;paid.return_value=cloud({'ok':True})
    assert ai_provider.json_completion('fixture',{},schema=SCHEMA)=={'ok':True}
    assert all(c.args[1]=='/health' for c in relay.call_args_list)
    assert paid.call_count==budget.call_count==1


def test_failed_local_cannot_bypass_paid_cap(fixture):
    relay,paid,budget,*_=fixture
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else (_ for _ in ()).throw(requests.Timeout())
    budget.side_effect=RuntimeError('paid_cap')
    with pytest.raises(RuntimeError,match='paid_cap'):ai_provider.json_completion('fixture',{},schema=SCHEMA)
    paid.assert_not_called()


def test_valid_hold_no_cloud_or_repair(fixture):
    relay,paid,budget,*_=fixture
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else native(DECISION)
    trace=final_ai.new_trace('synthetic-scan','FIXTURE',1)
    token=final_ai.TRACE.set(trace)
    try:assert final_ai.review([{'role':'user','content':'fixture'}],lambda v:v)==DECISION
    finally:final_ai.TRACE.reset(token)
    paid.assert_not_called();budget.assert_not_called()
    assert len(trace['attempts'])==1 and trace['provider']=='ollama_relay'


def test_final_transport_fallback_budget_and_trace(fixture):
    relay,paid,budget,_,ledger=fixture
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else (_ for _ in ()).throw(requests.Timeout())
    paid.side_effect=None;paid.return_value=cloud(DECISION)
    trace=final_ai.new_trace('synthetic-scan','FIXTURE',1)
    token=final_ai.TRACE.set(trace)
    try:assert final_ai.review([{'role':'user','content':'fixture'}],lambda v:v)==DECISION
    finally:final_ai.TRACE.reset(token)
    assert len(trace['attempts'])==2 and trace['provider']=='openrouter' and ledger.call_count==2
    assert trace['attempts'][0]['provider']=='ollama_relay'
    assert trace['attempts'][1]['fallback_reason']=='local_transport_failed'
    assert paid.call_count==budget.call_count==1


def test_local_parseable_hold_remains_locked_during_cloud_schema_repair(fixture):
    relay,paid,*_=fixture
    from review_rationale import Validator
    validator=Validator({'relation':'equal'},lambda v:v)
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else native(DECISION)
    paid.side_effect=None
    paid.return_value=cloud(dict(DECISION,action='BUY',entry_price_relation='equal',entry_price_concern='none'))
    with pytest.raises(ValueError,match='rationale_repair_changed_decision'):
        final_ai.review([{'role':'user','content':'fixture'}],validator)
    assert paid.call_count==1
    assert json.loads(paid.call_args.kwargs['json']['messages'][-1]['content'])['locked_decision']['action']=='HOLD'


def test_rationale_correction_stays_local_and_does_not_change_hold(fixture):
    relay,paid,*_=fixture
    from review_rationale import Validator
    responses=iter([native(dict(DECISION,entry_price_relation='above',entry_price_concern='quote_above_planned_entry')),
                    native(dict(DECISION,entry_price_relation='equal',entry_price_concern='none'))])
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else next(responses)
    validator=Validator({'relation':'equal'},lambda v:v)
    assert final_ai.review([{'role':'user','content':'fixture'}],validator)['action']=='HOLD'
    paid.assert_not_called()


def test_late_local_response_is_never_returned(fixture,monkeypatch):
    relay,*_=fixture
    at=[0]
    monkeypatch.setattr(routing.time,'monotonic',lambda:at[0])
    def late(*a,**k):at[0]=51;return native({'ok':True})
    relay.side_effect=late
    with pytest.raises(requests.Timeout,match='deadline'):
        routing.local_completion([{'role':'user','content':'fixture'}],SCHEMA,20)


def test_semantic_rejection_never_shops_for_other_decision(fixture):
    relay,paid,*_=fixture
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else native(DECISION)
    def reject(value):raise ValueError('semantic_direction')
    with pytest.raises(ValueError,match='semantic_direction'):
        final_ai.review([{'role':'user','content':'fixture'}],reject)
    paid.assert_not_called()
    assert len([c for c in relay.call_args_list if c.args[1]=='/completion'])==1


@pytest.mark.parametrize('bad',['{"ok":true,"ok":false}','{"ok":NaN}','{} {}'])
def test_native_duplicate_keys_nonfinite_multiple_objects_rejected(fixture,bad):
    relay,*_=fixture
    body=native({'ok':True});body['message']['content']=bad
    relay.side_effect=None;relay.return_value=body
    with pytest.raises(ValueError):routing.local_completion([],SCHEMA,20)


def gateway():
    path=Path(__file__).resolve().parents[3]/'scripts/ollama_inference_gateway.py'
    spec=importlib.util.spec_from_file_location('synthetic_gateway',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_gateway_no_model_download_single_slot_and_pinned_identity():
    g=gateway();engine=g.Inference();engine.loaded=True;engine.available=True;engine.at=time.monotonic()
    tags={'models':[{'name':g.MODEL,'digest':g.DIGEST}]}
    engine.http=Mock(side_effect=[tags,native({'ok':True}),tags])
    payload=dict(protocol=1,model=g.MODEL,digest=g.DIGEST,messages=[{'role':'user','content':'fixture'}],
                 schema=SCHEMA,predict=50,request_id='synthetic')
    assert engine.complete(payload)['model_digest']==g.DIGEST
    assert [c.args[1] for c in engine.http.call_args_list]==['/api/tags','/api/chat','/api/tags']
    assert engine.http.call_args_list[1].args[2]['think'] is False
    with engine.slot:
        with pytest.raises(ValueError,match='not_ready'):engine.complete(payload)
    payload['digest']='0'*64
    with pytest.raises(ValueError,match='unapproved'):engine.complete(payload)


def test_gateway_transport_capacity_fails_before_inference():
    g=gateway();engine=g.Inference();engine.http=Mock()
    payload=dict(protocol=1,model=g.MODEL,digest=g.DIGEST,messages=[{'role':'user','content':'x'*g.MAX_BYTES}],
                 schema=SCHEMA,predict=50,request_id='synthetic')
    with pytest.raises(ValueError,match='context_capacity'):engine.complete(payload)
    engine.http.assert_not_called()


def test_disabled_kill_switch_restores_paid_precheck(fixture,monkeypatch):
    relay,_,budget,*_=fixture
    routing.check_available();budget.assert_not_called()
    monkeypatch.setenv('AI_INFERENCE_MODE','cloud_only')
    routing.check_available();budget.assert_called_once()
    assert relay.call_count==1


def test_invalid_mode_fails_closed(fixture,monkeypatch):
    monkeypatch.setenv('AI_INFERENCE_MODE','all_free')
    with pytest.raises(ValueError,match='invalid_ai_inference_mode'):routing.ready()


@pytest.mark.skipif(sys.platform=='win32',reason='Linux Unix-socket integration runs in mandatory Linux CI')
def test_real_private_socket_and_no_public_http_endpoint(tmp_path,monkeypatch):
    import http.server
    import socket
    class Server(http.server.HTTPServer):
        address_family=socket.AF_UNIX
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            raw=json.dumps(dict(protocol=1,ready=True,model=routing.MODEL,digest=routing.DIGEST,capacity=1)).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=Server(str(tmp_path/'private.sock'),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    implementation=routing.UnixHTTP
    monkeypatch.setattr(routing,'UnixHTTP',lambda _,timeout:implementation(str(tmp_path/'private.sock'),timeout=timeout))
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first');monkeypatch.setattr(routing,'_until',0)
    try:
        assert routing.ready()
        monkeypatch.setenv('OLLAMA_RELAY_SOCKET','https://attacker.example/')
        with pytest.raises(ValueError,match='private_relay'):routing.ready()
    finally:
        server.shutdown();thread.join(2);server.server_close()


def test_gateway_real_loopback_http_rejects_extra_routes_and_prompts(monkeypatch):
    g=gateway();engine=g.Inference();engine.loaded=True;engine.available=True;engine.at=time.monotonic()
    engine.http=Mock(side_effect=AssertionError('Upstream inference forbidden'))
    server=g.BoundedServer(('127.0.0.1',0),g.handler(engine))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    # Unit suite's Telegram-only guard does not mock loopback. This is real HTTP,
    # without an actual model or any connection to the production server.
    endpoint='http://127.0.0.1:'+str(server.server_port)
    try:
        with requests.Session() as session:
            session.trust_env=False
            assert session.get(endpoint+'/health',timeout=2).json()['ready']
            assert session.post(endpoint+'/api/pull',json={'model':'other'},timeout=2).status_code==503
            assert session.post(endpoint+'/completion',json={'command':'BUY'},timeout=2).status_code==503
        engine.http.assert_not_called()
    finally:
        server.shutdown();thread.join(2);server.server_close()


def test_canonical_transport_uses_existing_global_repair_not_new_budget(fixture):
    relay,paid,_,_,ledger=fixture
    from news_events.analysis import CanonicalAnalyzer
    from news_quality import ANALYSIS_SCHEMA
    from news_structured_envelope import FUNCTION_NAME
    draft=dict(related=True,title_he='דיווח בדיקה',summary_he='דיווח בדיקה',interpretation_he='פרשנות בדיקה',
        sentiment='neutral',materiality='medium',relevance=.6)
    review=dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,duplicate_of=0,
                material_new_fact=False,explanation='בדיקה',scope_related=True)
    relay.side_effect=lambda method,path,*a,**k: dict(protocol=1,ready=True,model=routing.MODEL,
        digest=routing.DIGEST,capacity=1) if path=='/health' else (_ for _ in ()).throw(requests.Timeout())
    paid.side_effect=[Mock(json=Mock(return_value={'choices':[{'finish_reason':'tool_calls','message':{
        'content':None,'tool_calls':[{'type':'function','function':{'name':FUNCTION_NAME,'arguments':json.dumps(v)}}]}}],
        'usage':{'cost':.001}})) for v in (draft,review)]
    event=dict(event_id='synthetic',company_identity=[],evidence_version='1',event_type='market',tickers=[],
        title='Synthetic factual event',normalized_evidence=[{'text':'Synthetic factual event.'}],conflicts=[],sources=[])
    stages=[]
    def completion(stage,system,payload,schema):
        stages.append(stage);usage={}
        try:return ai_provider.json_completion(system,payload,schema=schema,max_attempts=1,
            structured_news=True,usage_sink=usage),usage
        except Exception as exc:exc.canonical_usage=usage;raise
    result=CanonicalAnalyzer(completion)(event)
    assert result.result==draft and len(result.calls)==3 and ledger.call_count==3
    assert stages==['source_analysis','local_fallback:source_analysis','quality_review']
    assert paid.call_count==2
    assert result.calls[0]['failure_reason']=='local_transport_failed'


@pytest.mark.parametrize('attempts', [1, 2])
def test_shared_transport_diagnostic_revalidated_once_without_new_attempt(fixture, monkeypatch, attempts):
    relay, paid, budget, _, ledger = fixture
    failure = requests.ConnectionError('local_relay_unavailable')
    failure.local_transport_failure = {'reason': 'relay_http_error', 'http_status': 503,
                                       'body': 'PRIVATE_SENTINEL'}
    monkeypatch.setattr(routing, 'local_completion', Mock(side_effect=failure))
    paid.side_effect = None
    paid.return_value = cloud({'ok': True})
    usage = {}
    if attempts == 1:
        with pytest.raises(ValueError, match='transport_failed'):
            ai_provider.json_completion('fixture', {}, schema=SCHEMA, max_attempts=attempts, usage_sink=usage)
        paid.assert_not_called()
    else:
        assert ai_provider.json_completion('fixture', {}, schema=SCHEMA, max_attempts=attempts, usage_sink=usage) == {'ok': True}
        paid.assert_called_once()
        assert ledger.call_args_list[1].args[5] is None
    assert ledger.call_count == attempts
    detail = json.loads(ledger.call_args_list[0].args[5])
    assert detail['exception'] == 'ConnectionError' and detail['http_status'] is None
    assert detail['local_transport'] == {'reason': 'relay_http_error', 'http_status': 503}
    assert 'PRIVATE_SENTINEL' not in json.dumps(detail)
    assert 'local_transport' not in usage


def test_final_transport_attempt_diagnostic_does_not_leak_into_paid_attempt(fixture, monkeypatch):
    _, paid, _, _, ledger = fixture
    failure = requests.ConnectionError('local_relay_unavailable')
    failure.local_transport_failure = {'reason': 'relay_http_error', 'http_status': 503,
                                       'body': 'PRIVATE_SENTINEL'}
    monkeypatch.setattr(routing, 'local_completion', Mock(side_effect=failure))
    paid.side_effect = None
    paid.return_value = cloud(DECISION)
    trace = final_ai.new_trace('synthetic-scan', 'FIXTURE', 1)
    token = final_ai.TRACE.set(trace)
    try:
        assert final_ai.review([{'role': 'user', 'content': 'fixture'}], lambda v: v) == DECISION
    finally:
        final_ai.TRACE.reset(token)
    assert len(trace['attempts']) == ledger.call_count == 2
    assert trace['attempts'][0]['local_transport'] == {'reason': 'relay_http_error', 'http_status': 503}
    assert 'local_transport' not in trace['attempts'][1]
    assert trace['attempts'][1]['fallback_reason'] == 'local_transport_failed'
    assert ledger.call_args_list[0].args[5] == 'ConnectionError'
    assert 'PRIVATE_SENTINEL' not in json.dumps(trace)


def test_paid_error_cannot_inject_local_transport_metadata(fixture, monkeypatch):
    _, paid, _, _, ledger = fixture
    monkeypatch.setenv('AI_INFERENCE_MODE', 'cloud_only')
    failure = requests.ConnectionError('PRIVATE_SENTINEL')
    failure.local_transport_failure = {'reason': 'relay_http_error', 'http_status': 503}
    paid.side_effect = failure
    with pytest.raises(ValueError, match='transport_failed'):
        ai_provider.json_completion('fixture', {}, schema=SCHEMA, max_attempts=1)
    detail = json.loads(ledger.call_args.args[5])
    assert 'local_transport' not in detail and 'PRIVATE_SENTINEL' not in json.dumps(detail)
