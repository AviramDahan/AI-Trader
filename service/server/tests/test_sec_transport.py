"""Local TLS fixtures only: no SEC/provider, database, AI or Telegram calls."""
import os
import importlib
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import urllib3.connection

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sec_transport as transport

URL='https://data.sec.gov/submissions/CIK0000320193.json'
UA='Synthetic Operator fixture@example.com'


@pytest.fixture(autouse=True)
def stdlib_tls_context():
    # This Windows interpreter injects pip truststore globally; its context is
    # client-only. Use its public extract/restore hooks for the local TLS server.
    name=ssl.SSLContext.__module__
    injected=None
    if name=='truststore._api' or name.endswith('.truststore._api'):
        injected=importlib.import_module(name.rpartition('.')[0])
        injected.extract_from_ssl()
    try:yield
    finally:
        if injected:injected.inject_into_ssl()


@pytest.fixture(scope='module')
def tls_certificate(tmp_path_factory):
    # Generate an ephemeral test-only CA/leaf. No key is stored in the repo.
    openssl=shutil.which('openssl')
    if not openssl and os.name=='nt':
        candidate=Path('C:/Program Files/Git/usr/bin/openssl.exe')
        if candidate.is_file():openssl=str(candidate)
    assert openssl,'Local TLS fixture requires the OpenSSL CLI'
    directory=tmp_path_factory.mktemp('sec-local-tls')
    cert,key=directory/'fixture.pem',directory/'fixture-key.pem'
    result=subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes',
        '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=data.sec.gov',
        '-addext','subjectAltName=DNS:data.sec.gov,DNS:www.sec.gov'],
        capture_output=True,timeout=15,check=False)
    assert result.returncode==0,'Ephemeral local TLS certificate generation failed'
    return cert,key


@contextmanager
def local_tls(monkeypatch,tls_certificate,mode):
    cert,key=tls_certificate
    stop=threading.Event()
    sockets=[]
    responses=[]
    sessions=[]
    timers=[]
    class Server(ThreadingHTTPServer):
        daemon_threads=False
        block_on_close=True
        def get_request(self):
            sock,address=super().get_request()
            try:return context.wrap_socket(sock,server_side=True),address
            except BaseException:sock.close();raise
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def do_GET(self):
            try:
                if mode=='headers':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Fixture: ')
                    for _ in range(8):
                        if stop.wait(.05):return
                        self.wfile.write(b'x')
                    self.wfile.write(b'\r\nContent-Length: 2\r\n\r\nok')
                elif mode=='body':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n')
                    for _ in range(8):
                        if stop.wait(.05):return
                        self.wfile.write(b'x')
                else:
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nETag: fixture\r\n\r\nok')
            except (OSError,ssl.SSLError):pass
    server=Server(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert),str(key))
    worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},name='sec-fixture-server')
    worker.start()
    original_dns=socket.getaddrinfo
    original_connect=urllib3.connection.HTTPSConnection.connect
    original_timer=threading.Timer
    original_session=requests.Session
    def fixture_dns(host,port,*args,**kwargs):
        assert host=='data.sec.gov','SEC fixture forbids every external hostname'
        assert port==443
        return original_dns('127.0.0.1',server.server_port,*args,**kwargs)
    def tracked_connect(connection):
        original_connect(connection)
        sockets.append(connection.sock)
    def tracked_timer(*args,**kwargs):
        timer=original_timer(*args,**kwargs);timers.append(timer);return timer
    class Session(original_session):
        def __init__(self):super().__init__();self.closed=False;sessions.append(self)
        def send(self,request,**kwargs):
            assert kwargs['verify'] is True # Production keeps normal verified TLS.
            kwargs['verify']=str(cert) # Trust only this ephemeral fixture CA.
            response=super().send(request,**kwargs)
            responses.append(response)
            return response
        def close(self):
            super().close();self.closed=True
    with monkeypatch.context() as patch:
        patch.setattr(socket,'getaddrinfo',fixture_dns)
        patch.setattr(urllib3.connection.HTTPSConnection,'connect',tracked_connect)
        patch.setattr(transport.threading,'Timer',tracked_timer)
        patch.setattr(transport.requests,'Session',Session)
        patch.setattr(transport,'reserve',lambda:None)
        try:
            yield {'sockets':sockets,'responses':responses,'sessions':sessions,'timers':timers}
        finally:
            stop.set();server.shutdown();server.server_close();worker.join(timeout=2)
            assert not worker.is_alive(),'Local TLS fixture worker leaked'
            assert all(not timer.is_alive() for timer in timers),'SEC deadline timer leaked'
            assert sessions and all(session.closed for session in sessions)
            assert all(response.raw.closed for response in responses)
            try:
                # The old Requests-only baseline may defer pool socket GC.
                # The new deadline owner must explicitly close its own socket.
                if timers:
                    assert sockets and all(sock.fileno()==-1 for sock in sockets),'SEC client socket leaked'
            finally:
                for sock in sockets:sock.close()


@pytest.mark.parametrize('mode',['headers','body'])
def test_cumulative_response_deadline_interrupts_trickling_tls(monkeypatch,tls_certificate,mode):
    # Bytes arrive every 50ms, far inside the unchanged 12-second inactivity
    # timeout. A 120ms fixture response budget must interrupt a blocked read.
    monkeypatch.setattr(transport,'RESPONSE_TIMEOUT_SECONDS',.12,raising=False)
    with local_tls(monkeypatch,tls_certificate,mode) as owned:
        began=time.monotonic()
        with pytest.raises(requests.exceptions.Timeout,match='sec_response_deadline'):
            transport.fetch(URL,UA)
        assert time.monotonic()-began<.35
        assert len(owned['timers'])==1


def test_normal_tls_response_keeps_metadata_and_cleans_up(monkeypatch,tls_certificate):
    with local_tls(monkeypatch,tls_certificate,'normal'):
        assert transport.fetch(URL,UA)==(b'ok',{'etag':'fixture','modified':''})


def test_expiry_racing_with_connect_return_aborts_owned_socket(monkeypatch):
    timers=[]
    class ImmediateTimer:
        def __init__(self,seconds,callback):
            self.callback=callback;self.cancelled=False;self.joined=False;timers.append(self)
        def start(self):self.callback()
        def cancel(self):self.cancelled=True
        def join(self):self.joined=True
    monkeypatch.setattr(transport.threading,'Timer',ImmediateTimer)
    deadline=transport._ResponseDeadline();owned=Mock()
    try:
        with pytest.raises(requests.exceptions.Timeout,match='sec_response_deadline'):
            deadline.bind(owned)
    finally:deadline.close()
    owned.shutdown.assert_called_with(socket.SHUT_RDWR)
    owned.close.assert_called_once()
    assert timers[0].cancelled and timers[0].joined


def test_cleanup_joins_an_abort_callback_already_in_progress(monkeypatch):
    entered,release,closed,closer_started=(threading.Event() for _ in range(4))
    class Owned:
        def shutdown(self,_how):
            entered.set();assert release.wait(2)
        def close(self):closed.set()
    monkeypatch.setattr(transport,'RESPONSE_TIMEOUT_SECONDS',.05)
    deadline=transport._ResponseDeadline()
    closer=None
    try:
        deadline.bind(Owned())
        assert entered.wait(1)
        def cleanup():closer_started.set();deadline.close()
        closer=threading.Thread(target=cleanup,name='sec-fixture-deadline-cleanup')
        closer.start();assert closer_started.wait(1)
        assert not closed.wait(.02),'Socket closed before running abort callback joined'
        release.set();closer.join(timeout=1)
        assert not closer.is_alive() and closed.is_set() and not deadline.timer.is_alive()
    finally:
        release.set()
        if closer:closer.join(timeout=1)
        deadline.close()
