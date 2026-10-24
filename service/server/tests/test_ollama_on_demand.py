"""Demand-only model lifetime: synthetic upstream, no installed Ollama calls."""
import copy
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


def gateway():
    path = Path(__file__).resolve().parents[3] / 'scripts/ollama_inference_gateway.py'
    spec = importlib.util.spec_from_file_location('demand_gateway', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Native:
    """Mock native expiry occurs after request completion, never while active."""
    def __init__(self, module, engine):
        self.g, self.engine = module, engine
        self.now = 100.0
        self.resident = False
        self.active = False
        self.finished_at = None
        self.calls = []
        self.loads = 0
        self.entered = None
        self.release = None
        self.fail = None

    def expire(self):
        if self.finished_at is not None and not self.active and self.now-self.finished_at >= 120:
            self.resident = False

    def __call__(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path, copy.deepcopy(payload), kwargs))
        self.expire()
        if path == '/api/tags':
            return {'models': [{'name': self.g.MODEL, 'digest': self.g.DIGEST}]}
        if path == '/api/version':
            return {'version': '0.34.4'}
        if path == '/api/ps':
            return {'models': [{'name': self.g.MODEL, 'digest': self.g.DIGEST,
                                'context_length': 8192}] if self.resident else []}
        assert (method, path) == ('POST', '/api/chat')
        assert self.engine.slot.locked()
        if not self.resident:
            self.loads += 1
        self.resident = True
        self.active = True
        try:
            if self.entered:
                self.entered.set()
                assert self.release.wait(3)
            if self.fail:
                raise self.fail
            return {'model': self.g.MODEL, 'done': True, 'done_reason': 'stop',
                    'message': {'role': 'assistant', 'content': '{"ok":true}'}}
        finally:
            self.active = False
            self.finished_at = self.now


@pytest.fixture
def setup_gateway():
    g = gateway()
    engine = g.Inference()
    upstream = Native(g, engine)
    g.time = SimpleNamespace(monotonic=lambda: upstream.now)
    engine.http = upstream
    return g, engine, upstream


def payload(g):
    return dict(protocol=1, model=g.MODEL, digest=g.DIGEST,
                messages=[{'role': 'user', 'content': 'Synthetic compatibility input'}],
                schema={'type': 'object'}, predict=16, request_id='synthetic-demand')


@pytest.mark.parametrize('already_loaded', [False, True])
def test_health_refresh_is_read_only_and_cold_is_eligible(setup_gateway, already_loaded):
    g, engine, native = setup_gateway
    native.resident = already_loaded
    for _ in range(5):
        engine.refresh()
        assert engine.health()['ready'] is True
        assert engine.health()['model_loaded'] is already_loaded
        native.now += 30
    assert all(method == 'GET' for method, *_ in native.calls)
    assert native.loads == 0


def test_first_real_request_loads_without_preload_and_preserves_input(setup_gateway):
    g, engine, native = setup_gateway
    body = payload(g)
    before = copy.deepcopy(body)
    # Includes direct admission before the first periodic metadata observation.
    assert engine.complete(body)['model_digest'] == g.DIGEST
    chats = [row for row in native.calls if row[:2] == ('POST', '/api/chat')]
    assert len(chats) == native.loads == 1
    sent, options = chats[0][2:]
    assert sent['messages'] == body['messages'] and body == before
    assert sent['keep_alive'] == '2m'
    assert sent['truncate'] is False and sent['shift'] is False and sent['think'] is False
    assert sent['options'] == {'temperature': 0, 'num_ctx': 8192, 'num_predict': 16}
    assert options['timeout'] == 45
    assert engine.health()['ready'] and not engine.slot.locked()


def test_native_idle_unload_is_not_reversed_by_health_then_reloads_on_demand(setup_gateway):
    g, engine, native = setup_gateway
    engine.complete(payload(g))
    native.now += 121
    for _ in range(5):
        engine.refresh()
        assert not native.resident
        assert engine.health()['ready'] and engine.health()['model_loaded'] is False
        native.now += 30
    assert native.loads == 1
    assert engine.complete(payload(g))['done']
    assert native.loads == 2
    assert all(row[2]['messages'] for row in native.calls if row[0] == 'POST')


def test_parallel_requests_do_not_queue_or_duplicate_cold_load(setup_gateway):
    g, engine, native = setup_gateway
    native.entered, native.release = threading.Event(), threading.Event()
    result, errors = [], []
    def first():
        try:
            result.append(engine.complete(payload(g)))
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=first)
    worker.start()
    try:
        assert native.entered.wait(2)
        calls = len(native.calls)
        assert not engine.health()['ready']
        for _ in range(7):
            with pytest.raises(ValueError, match='local_not_ready'):
                engine.complete(payload(g))
        engine.refresh()
        assert len(native.calls) == calls
        # A prior idle lease expiring during real work cannot unload the
        # active request; stay within the unchanged45s admission deadline.
        native.finished_at = native.now-119
        native.now += 2
        native.expire()
        engine.refresh()
        assert native.resident and native.active and len(native.calls) == calls
    finally:
        native.release.set()
        worker.join(3)
    assert not worker.is_alive() and not errors and len(result) == 1
    assert native.loads == 1 and engine.health()['ready']


def test_unavailable_metadata_never_loads_and_recovers_read_only(setup_gateway):
    g, engine, native = setup_gateway
    real = engine.http
    engine.http = lambda method, path, *a, **kw: (
        {'models': []} if path == '/api/tags' else real(method, path, *a, **kw))
    engine.refresh()
    assert not engine.health()['ready']
    with pytest.raises(ValueError):
        engine.complete(payload(g))
    assert native.loads == 0 and not engine.slot.locked()
    engine.http = real
    engine.refresh()
    assert engine.health()['ready'] and native.loads == 0
