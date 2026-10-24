"""Independent synthetic on-demand lifecycle; no live sockets/model/provider IO."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import types

import pytest
import requests


def gateway():
    root=Path(__file__).resolve().parents[3]
    path=root/'scripts/ollama_inference_gateway.py'
    if os.getenv('QA_ON_DEMAND_BASELINE')=='1':
        raw=subprocess.check_output(['git','-C',str(root),'show',
            'e63461e278fe4ee6ce26a7194226da8499b9ef78:scripts/ollama_inference_gateway.py'])
        assert hashlib.sha256(raw).hexdigest()=='8c9c5832765c1f615db11abf9070ddfd49643ec4d8ceea16baa488e329c9bbd0'
        module=types.ModuleType('independent_exact_old_gateway');module.__file__=str(path)
        exec(compile(raw,str(path),'exec'),module.__dict__)
        return module
    spec=importlib.util.spec_from_file_location('independent_current_gateway',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Native:
    def __init__(self,g):
        self.g=g;self.calls=[];self.loaded=False;self.version='0.34.4'
        self.digest=g.DIGEST;self.context=g.CONTEXT;self.failure=None;self.enter=None;self.leave=None
    def __call__(self,method,path,payload=None,timeout=2):
        self.calls.append((method,path,copy.deepcopy(payload),timeout))
        if self.failure:raise self.failure
        if method=='GET' and path=='/api/tags':return {'models':[{'name':self.g.MODEL,'digest':self.digest}]}
        if method=='GET' and path=='/api/version':return {'version':self.version}
        if method=='GET' and path=='/api/ps':return {'models':([{'name':self.g.MODEL,'digest':self.digest,'context_length':self.context}] if self.loaded else [])}
        assert method=='POST' and path=='/api/chat','Unexpected native action'
        if not payload['messages']:
            # Model a successful legacy preload so its observable effect is tested.
            self.loaded=True;return {'done':True}
        if self.enter:self.enter.set()
        if self.leave:assert self.leave.wait(2),'Synthetic concurrency gate timeout'
        self.loaded=True
        return {'model':self.g.MODEL,'done':True,'done_reason':'stop','message':{'content':'{"ok":true}'}}
    def posts(self):return [c for c in self.calls if c[0]=='POST']


@pytest.fixture
def setup(monkeypatch):
    g=gateway();clock=[1000.0]
    monkeypatch.setattr(g.time,'monotonic',lambda:clock[0])
    def denied(*a,**kw):raise AssertionError('Real transport forbidden in independent tests')
    monkeypatch.setattr(requests.sessions.Session,'request',denied)
    monkeypatch.setattr(socket,'socket',denied)
    engine=g.Inference();native=Native(g);engine.http=native
    payload={'protocol':1,'model':g.MODEL,'digest':g.DIGEST,
      'messages':[{'role':'system','content':'Synthetic full policy'},{'role':'user','content':'Synthetic actual job'}],
      'schema':{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False},
      'predict':450,'request_id':'independent-synthetic'}
    return g,engine,native,clock,payload


@pytest.mark.parametrize('loaded',[False,True])
def test_metadata_refresh_never_preloads_even_first_refresh(setup,loaded):
    g,e,n,clock,p=setup;n.loaded=loaded
    e.refresh();e.refresh()
    assert n.posts()==[], 'Health/background metadata must never generate or renew keepalive'
    assert e.health()['ready'] is True
    assert e.loaded is loaded


def test_cold_complete_accepts_compatible_metadata_without_empty_preload(setup):
    g,e,n,clock,p=setup
    e.refresh();assert e.health()['ready'] is True
    result=e.complete(p)
    assert result['model_digest']==g.DIGEST
    assert len(n.posts())==1 and n.posts()[0][2]['messages']==p['messages']
    assert n.posts()[0][2]['keep_alive']=='2m'
    assert n.posts()[0][3]<=45


def test_idle_native_expiry_remains_cold_until_next_real_job(setup):
    g,e,n,clock,p=setup;e.refresh();e.complete(p)
    before=len(n.posts());n.loaded=False;clock[0]+=130
    for _ in range(4):e.refresh();clock[0]+=30
    assert len(n.posts())==before and n.loaded is False
    assert e.health()['ready'] is True
    e.complete(p)
    assert len(n.posts())==before+1 and n.posts()[-1][2]['messages']==p['messages']


def test_one_gpu_slot_and_metadata_do_not_queue_or_duplicate_load(setup):
    g,e,n,clock,p=setup;e.refresh();n.calls.clear()
    n.enter=threading.Event();n.leave=threading.Event();results=[];errors=[]
    def first():
        try:results.append(e.complete(p))
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=first);thread.start()
    try:
        assert n.enter.wait(1),'First real request did not enter synthetic native handler'
        assert e.health()['ready'] is False
        at=len(n.calls);e.refresh();assert len(n.calls)==at
        with pytest.raises(ValueError,match='not_ready'):e.complete(p)
        assert len(n.posts())==1
    finally:n.leave.set();thread.join(2)
    assert not thread.is_alive() and not errors and len(results)==1
    assert n.posts()[0][2]['keep_alive']=='2m'


@pytest.mark.parametrize('version',['0.34.3','0.9.9','broken','0.34.4junk'])
def test_unsupported_version_never_preloads_or_receives_real_job(setup,version):
    g,e,n,clock,p=setup;n.version=version;e.refresh()
    assert e.health()['ready'] is False and not n.posts()
    with pytest.raises(ValueError):e.complete(p)
    assert not n.posts()


@pytest.mark.parametrize('change',['tag_digest','active_context'])
def test_identity_or_active_context_mismatch_never_reloads_to_hide_it(setup,change):
    g,e,n,clock,p=setup
    if change=='tag_digest':n.digest='0'*64
    else:n.loaded=True;n.context=16384
    e.refresh()
    assert not e.health()['ready'] and not n.posts()
    with pytest.raises(ValueError):e.complete(p)
    assert not n.posts()


def test_stale_readiness_and_failed_refresh_fail_closed_no_load(setup):
    g,e,n,clock,p=setup;e.refresh();clock[0]+=66
    assert e.health()['ready'] is False
    n.failure=requests.Timeout('synthetic metadata failure');e.refresh()
    assert not e.health()['ready'] and not n.posts()
    with pytest.raises(ValueError):e.complete(p)
    n.failure=None;e.refresh()
    assert e.health()['ready'] and not n.posts()


def test_transport_size_and_model_rejection_do_not_acquire_native_job(setup):
    g,e,n,clock,p=setup
    bad=copy.deepcopy(p);bad['messages'][1]['content']='x'*g.MAX_BYTES
    with pytest.raises(g.ContextCapacity):e.complete(bad)
    bad=copy.deepcopy(p);bad['digest']='0'*64
    with pytest.raises(ValueError):e.complete(bad)
    assert n.calls==[] and not e.slot.locked()


def test_native_capacity_failure_releases_slot_and_preserves_metadata(setup):
    g,e,n,clock,p=setup;e.refresh();n.calls.clear()
    original=e.http
    def capacity(method,path,payload=None,timeout=2):
        if method=='POST':raise g.ContextCapacity('local_context_capacity')
        return original(method,path,payload,timeout)
    e.http=capacity
    with pytest.raises(g.ContextCapacity):e.complete(p)
    assert not e.slot.locked()
    e.http=original;e.refresh()
    assert e.health()['ready'] is True


def test_real_chat_preserves_pinned_model_context_output_and_safety_options(setup):
    g,e,n,clock,p=setup;e.refresh();e.complete(p)
    real=[r for r in n.posts() if r[2]['messages']]
    assert len(real)==1
    body=real[0][2]
    assert body['model']==g.MODEL and body['messages']==p['messages'] and body['format']==p['schema']
    assert body['stream'] is False and body['think'] is False
    assert body['truncate'] is False and body['shift'] is False
    assert body['options']=={'temperature':0,'num_ctx':8192,'num_predict':450}


def test_cold_metadata_and_generation_share_one_total_45s_budget(setup):
    g,e,n,clock,p=setup
    original=e.http
    def consume(method,path,payload=None,timeout=2):
        value=original(method,path,payload,timeout)
        clock[0]+=44 if method=='POST' else 1
        return value
    e.http=consume
    with pytest.raises((ValueError,TimeoutError,requests.Timeout)):
        e.complete(p)
    assert not e.slot.locked()
    assert len(n.posts())==1


def test_real_chat_timeout_receives_only_remaining_shared_budget(setup):
    g,e,n,clock,p=setup
    original=e.http
    def consume(method,path,payload=None,timeout=2):
        value=original(method,path,payload,timeout)
        if method=='GET':clock[0]+=1
        return value
    e.http=consume;e.complete(p)
    assert n.posts()[0][3]<=41,'Four metadata reads must not add time beyond the45s real-job budget'


def test_http_deadline_starts_before_response_headers_not_after_them(setup,monkeypatch):
    g,e,n,clock,p=setup
    body=json.dumps({'done':True,'message':{'content':'{}'}}).encode()
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def iter_content(self,n):yield body
    class Session:
        trust_env=True
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def request(self,*a,**kw):
            assert kw['allow_redirects'] is False and kw['stream'] is True
            clock[0]+=46
            return Response()
    monkeypatch.setattr(g.requests,'Session',Session)
    with pytest.raises((ValueError,TimeoutError,requests.Timeout)):
        g.Inference().http('POST','/api/chat',{'messages':p['messages']},timeout=45)


@pytest.mark.parametrize('bad', [True,0,2049,-1,1.5,'450'])
def test_invalid_predict_never_performs_any_metadata_or_model_request(setup,bad):
    g,e,n,clock,p=setup;p['predict']=bad
    with pytest.raises(ValueError):e.complete(p)
    assert n.calls==[]


def test_model_identity_changed_after_cold_generation_rejects_result(setup):
    g,e,n,clock,p=setup
    original=e.http
    def mutate(method,path,payload=None,timeout=2):
        value=original(method,path,payload,timeout)
        if method=='POST':n.digest='0'*64
        return value
    e.http=mutate
    with pytest.raises(ValueError):e.complete(p)
    assert not e.slot.locked() and e.health()['ready'] is False


def test_direct_first_request_bootstraps_without_prior_health_refresh(setup):
    g,e,n,clock,p=setup
    assert e.complete(p)['model_digest']==g.DIGEST
    assert [c[1] for c in n.calls[:3]]==['/api/tags','/api/version','/api/ps']
    assert len(n.posts())==1 and n.posts()[0][2]['messages']==p['messages']


def test_health_handler_itself_never_renews_keepalive_or_loads(setup):
    g,e,n,clock,p=setup;e.refresh();n.calls.clear()
    obj=object.__new__(g.handler(e));obj.path='/health';responses=[]
    obj.respond=lambda status,body:responses.append((status,body))
    for _ in range(20):obj.do_GET()
    assert len(responses)==20 and all(r[0]==200 and r[1]['ready'] is True for r in responses)
    assert n.calls==[]


@pytest.mark.parametrize('path,body', [('/api/pull',b'{}'),('/completion',b'{"command":"BUY"}'),('/completion',b'x'*131073)], ids=['pull','command','size'])
def test_handler_rejects_unapproved_routes_and_requests_without_native_io(setup,path,body):
    g,e,n,clock,p=setup
    obj=object.__new__(g.handler(e));obj.path=path;obj.headers={'Content-Length':str(len(body))}
    obj.rfile=io.BytesIO(body);obj.connection=types.SimpleNamespace(settimeout=lambda *_:None)
    responses=[];obj.respond=lambda status,value:responses.append((status,value))
    obj.do_POST()
    assert responses==[(503,{'reason':'local_inference_unavailable'})] and n.calls==[]


def test_eight_handler_nonblocking_bound_and_permit_release_without_socket(setup,monkeypatch):
    g,e,n,clock,p=setup;accepted=[];closed=[]
    parent=g.http.server.ThreadingHTTPServer
    monkeypatch.setattr(parent,'__init__',lambda self,*a:None)
    monkeypatch.setattr(parent,'process_request',lambda self,request,address:accepted.append(request))
    monkeypatch.setattr(parent,'process_request_thread',lambda self,*a:None)
    server=g.BoundedServer(None,None)
    server.shutdown_request=lambda request:closed.append(request)
    for i in range(9):server.process_request(i,('synthetic',0))
    assert accepted==list(range(8)) and closed==[8]
    server.process_request_thread(0,('synthetic',0))
    server.process_request(9,('synthetic',0))
    assert accepted==list(range(8))+[9]


@pytest.mark.parametrize('mode',['size','error'])
def test_mock_http_response_caps_and_failures_keep_redirect_proxy_policy(setup,monkeypatch,mode):
    g,e,n,clock,p=setup
    class Response:
        status_code=503 if mode=='error' else 200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def iter_content(self,n):yield b'x'*(g.MAX_BYTES+1) if mode=='size' else b'{"error":"synthetic failure"}'
    class Session:
        trust_env=True
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def request(self,method,url,**kwargs):
            assert self.trust_env is False and kwargs['allow_redirects'] is False
            assert url=='http://127.0.0.1:11434/api/chat' and kwargs['stream'] is True
            return Response()
    monkeypatch.setattr(g.requests,'Session',Session)
    with pytest.raises(ValueError):g.Inference().http('POST','/api/chat',{})
