"""Independent, synthetic capacity metadata controls; no inference or network."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import types
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parents[3]
BASE = '621d1981582b48e662f66a4ade5d93491dc39772'
NATIVE = dict(version=1, source='native_token_limit', context_tokens=8192, prompt_tokens=12001)
DECISION = dict(action='HOLD',confidence=.1,news_sentiment=0,news_relevance=.4,
    time_horizon='1-4 weeks',reason='Synthetic HOLD; no sufficient trading evidence.')
SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}


def load(relative,name):
    path=ROOT/relative
    raw=(subprocess.check_output(['git','-C',str(ROOT),'show',BASE+':'+relative])
         if os.getenv('QA_CAPACITY_BASELINE')=='1' else path.read_bytes())
    module=types.ModuleType(name);module.__file__=str(path)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


@pytest.fixture
def modules(monkeypatch):
    import socket
    monkeypatch.setattr(socket,'create_connection',Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(requests.sessions.Session,'request',Mock(side_effect=AssertionError('network forbidden')))
    r=load('service/server/ai_routing.py','qa_routing')
    monkeypatch.setitem(sys.modules,'ai_routing',r)
    f=load('service/server/final_ai.py','qa_final')
    g=load('scripts/ollama_inference_gateway.py','qa_gateway')
    return r,f,g


def wrapped(prompt=12001,context=8192,**extra):
    detail=dict(code=400,type='exceed_context_size_error',n_prompt_tokens=prompt,n_ctx=context,
        message=f'request ({prompt} tokens) exceeds the available context size ({context} tokens), try increasing it')
    detail.update(extra)
    return {'error':json.dumps({'error':detail})}


def fake_native(monkeypatch,g,payload):
    response=Mock(status_code=400)
    response.iter_content.return_value=[json.dumps(payload).encode()]
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    session=Mock();session.request.return_value=response
    session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    monkeypatch.setattr(g.requests,'Session',lambda:session)
    return session


def relay_response(monkeypatch,r,header,*,status=413,body=None):
    response=Mock(status=status,read=lambda n:(body or b'{"reason":"local_context_capacity"}')[:n],
        getheader=lambda k:header)
    conn=Mock(sock=None);conn.getresponse.return_value=response
    monkeypatch.setattr(r,'UnixHTTP',lambda *a,**k:conn)
    return conn


def test_native_counter_survives_actual_http_refusal(modules,monkeypatch):
    r,f,g=modules
    session=fake_native(monkeypatch,g,wrapped())
    with pytest.raises(g.ContextCapacity) as error: g.Inference().http('POST','/api/chat',{})
    assert getattr(error.value,'local_capacity',None)==NATIVE
    assert str(error.value)=='local_context_capacity'
    assert session.request.call_count==1


def test_header_survives_actual_private_relay_refusal(modules,monkeypatch):
    r,f,g=modules
    conn=relay_response(monkeypatch,r,json.dumps(NATIVE))
    with pytest.raises(r.LocalCapacity) as error: r.relay('POST','/completion',{})
    assert getattr(error.value,'local_capacity',None)==NATIVE
    assert '12001' not in str(error.value)
    conn.close.assert_called_once()


def test_legacy_guard_keeps_bytes_as_units_not_native_tokens(modules,monkeypatch):
    r,f,g=modules
    relay=Mock(return_value={});monkeypatch.setattr(r,'relay',relay)
    with pytest.raises(r.LocalCapacity) as error:
        r.local_completion([dict(role='user',content='א'*5000)],SCHEMA,450)
    assert getattr(error.value,'local_capacity',None)==dict(version=1,source='legacy_guard_upper_bound',
        context_tokens=8192,legacy_guard_units=11090,requested_output_tokens=450)
    assert relay.call_count==1 and relay.call_args.args[:2]==('GET','/health')


def telemetry_db(tmp_path,monkeypatch):
    import database,target_evidence
    path=tmp_path/'telemetry.sqlite'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE scanner_final_ai_telemetry(review_id TEXT PRIMARY KEY,scan_id,ticker,rank,provider,model,input_tokens,output_tokens,latency,retry_count,result,reject_reason,ai_call_saved,estimated_cost,attempts_json,updated_at)')
    monkeypatch.setattr(database,'get_db_connection',lambda:sqlite3.connect(path))
    for name in ('persist_checks','persist_decision','persist_input_facts'):
        monkeypatch.setattr(target_evidence,name,Mock())
    return path


def configure_review(monkeypatch,r):
    import ai_budget,ai_operations
    for key,value in dict(AI_INFERENCE_MODE='ollama_first',AI_TRADER_CLOUD='true',
        STOCK_SCANNER_FINAL_AI_PROVIDER='openrouter',STOCK_SCANNER_FINAL_AI_MODEL='approved-fixture',
        OPENROUTER_API_KEY='synthetic-only').items():monkeypatch.setenv(key,value)
    monkeypatch.setattr(r,'ready',lambda:True)
    budget=Mock();slot=Mock();ledger=Mock()
    monkeypatch.setattr(ai_budget,'check',budget);monkeypatch.setattr(ai_budget,'acquire_request_slot',slot)
    monkeypatch.setattr(ai_operations,'record',ledger)
    paid=Mock(return_value=Mock(json=lambda:dict(choices=[dict(finish_reason='stop',
        message=dict(content=json.dumps(DECISION)))],usage=dict(prompt_tokens=15,completion_tokens=9,cost=.001))))
    monkeypatch.setattr(requests,'post',paid)
    return budget,slot,ledger,paid


def test_actual_persist_retains_optional_capacity_once_and_usage_stays_unknown(modules,monkeypatch,tmp_path):
    r,f,g=modules
    path=telemetry_db(tmp_path,monkeypatch)
    budget,slot,ledger,paid=configure_review(monkeypatch,r)
    failure=r.LocalCapacity('local_context_capacity');failure.local_capacity=dict(NATIVE,requested_output_tokens=450)
    local=Mock(side_effect=failure);monkeypatch.setattr(r,'local_completion',local)
    messages=[dict(role='user',content='Whole unchanged Hebrew עברית and economic source evidence.')]
    before=copy.deepcopy(messages);trace=f.new_trace('independent','TEST',1);token=f.TRACE.set(trace)
    try: assert f.review(messages,lambda value:value)==DECISION
    finally: f.TRACE.reset(token)
    f.persist(trace)
    with sqlite3.connect(path) as c:
        rows=c.execute('SELECT attempts_json,input_tokens,retry_count FROM scanner_final_ai_telemetry').fetchall()
    assert len(rows)==1
    attempts=json.loads(rows[0][0])
    assert attempts[0].get('local_capacity')==dict(NATIVE,requested_output_tokens=450)
    assert 'local_capacity' not in attempts[1] and rows[0][1] is None and rows[0][2]==1
    assert len(attempts)==ledger.call_count==2 and paid.call_count==budget.call_count==slot.call_count==1
    assert local.call_args.args[0]==paid.call_args.kwargs['json']['messages']==before==messages
    assert local.call_args.args[2]==450 and r._until==0
    assert all(a['logical_messages_sha256']==hashlib.sha256(json.dumps(before,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest() for a in attempts)
    assert 'Whole unchanged' not in rows[0][0]


@pytest.mark.parametrize('header',[None,'', 'x'*513, '[]', '{"version":NaN}',
    json.dumps(dict(NATIVE,version=True)),json.dumps(dict(NATIVE,prompt_tokens=True)),
    json.dumps(dict(NATIVE,prompt_tokens=8192)),json.dumps(dict(NATIVE,prompt_tokens=10000001)),
    json.dumps(dict(NATIVE,raw_prompt='PRIVATE_SENTINEL')),json.dumps(NATIVE)+'\r\nSECRET',
    '{"version":1,"version":1,"source":"native_token_limit","context_tokens":8192,"prompt_tokens":12001}'])
def test_malformed_or_old_header_never_changes_safe_fallback(modules,monkeypatch,header):
    r,f,g=modules;relay_response(monkeypatch,r,header)
    with pytest.raises(r.LocalCapacity) as error:r.relay('POST','/completion',{})
    assert not getattr(error.value,'local_capacity',None)
    assert str(error.value)=='local_context_capacity'


@pytest.mark.parametrize('change',[dict(n_ctx=16384),dict(n_prompt_tokens=True),dict(code=True),
    dict(message='PRIVATE_SENTINEL'),dict(extra='PRIVATE_SENTINEL')])
def test_invalid_native_structured_error_is_not_diagnostic_evidence(modules,change):
    r,f,g=modules
    assert not g.context_error(wrapped(**change))
    assert g.context_capacity_evidence(wrapped(**change))=={}


@pytest.mark.parametrize('evidence',[NATIVE,
    dict(version=1,source='native_capacity_unspecified',context_tokens=8192),
    dict(version=1,source='legacy_guard_upper_bound',context_tokens=8192,legacy_guard_units=10000000),
    dict(version=1,source='gateway_request_bytes',request_byte_limit=131072,request_bytes=10000000)])
def test_standalone_cloud_schema_parity_and_maximal_header_bound(modules,evidence):
    r,f,g=modules;value=dict(evidence,requested_output_tokens=2048)
    assert r.safe_local_capacity(value)==g.safe_local_capacity(value)==value
    assert r.safe_local_capacity(value) is not value
    assert len(json.dumps(value).encode('ascii'))<256


def test_handler_old_body_exact_optional_header_only_on_413(modules):
    r,f,g=modules
    error=g.ContextCapacity('local_context_capacity')
    error.local_capacity=dict(NATIVE)
    engine=Mock(complete=Mock(side_effect=error))
    handler=object.__new__(g.handler(engine));body=b'{}'
    handler.path='/completion';handler.headers={'Content-Length':str(len(body))}
    handler.rfile=io.BytesIO(body);handler.wfile=io.BytesIO();handler.connection=Mock()
    statuses=[];headers={};handler.send_response=statuses.append
    handler.send_header=headers.__setitem__;handler.end_headers=lambda:None
    handler.do_POST()
    assert statuses==[413] and handler.wfile.getvalue()==b'{"reason": "local_context_capacity"}'
    assert json.loads(headers['X-AI-Local-Capacity'])==NATIVE


def test_native_complete_adds_actual_output_request_without_changing_payload(modules,monkeypatch):
    r,f,g=modules
    engine=g.Inference();engine.loaded=True;engine.at=time.monotonic()
    calls=[]
    def http(method,path,payload=None,**kw):
        if path=='/api/tags':return {'models':[dict(name=g.MODEL,digest=g.DIGEST)]}
        calls.append(copy.deepcopy(payload))
        exc=g.ContextCapacity('local_context_capacity');exc.local_capacity=dict(NATIVE)
        raise exc
    monkeypatch.setattr(engine,'http',http)
    messages=[dict(role='user',content='מקור מלא '+'fact '*2000)]
    payload=dict(protocol=1,model=g.MODEL,digest=g.DIGEST,messages=messages,schema=SCHEMA,predict=450,request_id='fixture')
    with pytest.raises(g.ContextCapacity) as error:engine.complete(payload)
    assert error.value.local_capacity==dict(NATIVE,requested_output_tokens=450)
    assert calls[0]['messages']==messages and calls[0]['options']==dict(temperature=0,num_ctx=8192,num_predict=450)
    assert calls[0]['truncate'] is False and calls[0]['shift'] is False
    assert engine.slot.locked() is False
