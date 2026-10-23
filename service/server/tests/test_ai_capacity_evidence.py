"""Synthetic capacity evidence, not a model run or a capacity-setting change."""
import copy
import io
import json
import time
from unittest.mock import Mock

import pytest

from test_ai_routing import gateway, fixture, cloud, DECISION, SCHEMA
from test_signal_inputs import db, clock
import ai_routing as routing
import final_ai


NATIVE = {'version': 1, 'source': 'native_token_limit',
          'context_tokens': 8192, 'prompt_tokens': 93917}
REAL_RELAY = routing.relay
REAL_PERSIST = final_ai.persist


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch, request):
    import socket
    monkeypatch.setattr(socket, 'create_connection', Mock(side_effect=AssertionError('network forbidden')))
    if 'db' not in request.fixturenames:
        monkeypatch.setattr('database.get_db_connection', Mock(side_effect=AssertionError('DB forbidden')))


def native_error():
    detail = dict(code=400, type='exceed_context_size_error',
        message='request (93917 tokens) exceeds the available context size (8192 tokens), try increasing it',
        n_prompt_tokens=93917, n_ctx=8192)
    return {'error': json.dumps({'error': detail})}


def test_validated_native_counts_survive_gateway_without_raw_error(monkeypatch):
    g = gateway()
    response = Mock(status_code=400)
    response.iter_content.return_value = [json.dumps(native_error()).encode()]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.request.return_value = response
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(g.requests, 'Session', lambda: session)
    with pytest.raises(g.ContextCapacity) as caught:
        g.Inference().http('POST', '/api/chat', {}, timeout=1)
    assert getattr(caught.value, 'local_capacity', None) == NATIVE
    assert str(caught.value) == 'local_context_capacity'


def test_optional_capacity_header_preserves_old_413_body_and_exact_counts(monkeypatch):
    response = Mock(status=413)
    response.read.return_value = b'{"reason":"local_context_capacity"}'
    response.getheader.return_value = json.dumps(NATIVE)
    conn = Mock()
    conn.getresponse.return_value = response
    monkeypatch.setattr(routing, 'UnixHTTP', lambda *a, **k: conn)
    with pytest.raises(routing.LocalCapacity) as caught:
        routing.relay('POST', '/completion', {})
    assert getattr(caught.value, 'local_capacity', None) == NATIVE
    conn.close.assert_called_once()


def test_final_review_persists_capacity_only_on_failed_local_attempt(fixture, monkeypatch):
    _, paid, budget, _, ledger = fixture
    failure = routing.LocalCapacity('local_context_capacity')
    failure.local_capacity = dict(NATIVE)
    monkeypatch.setattr(routing, 'local_completion', Mock(side_effect=failure))
    paid.side_effect = None
    paid.return_value = cloud(DECISION)
    messages = [{'role': 'user', 'content': 'Complete synthetic evidence; no truncation.'}]
    trace = final_ai.new_trace('synthetic-scan', 'TEST', 1)
    token = final_ai.TRACE.set(trace)
    try:
        assert final_ai.review(messages, lambda v: v) == DECISION
    finally:
        final_ai.TRACE.reset(token)
    assert trace['attempts'][0].get('local_capacity') == NATIVE
    assert 'local_capacity' not in trace['attempts'][1]
    assert trace['attempts'][0]['input_tokens'] is None  # refused input is not generated/billed usage
    assert trace['attempts'][1]['fallback_reason'] == 'local_context_capacity'
    assert len(trace['attempts']) == ledger.call_count == 2
    assert paid.call_count == budget.call_count == 1 and routing._until == 0
    assert paid.call_args.kwargs['json']['messages'] == messages


def test_legacy_upper_bound_is_identified_as_units_not_measured_tokens(monkeypatch):
    relay = Mock(return_value={})
    monkeypatch.setattr(routing, 'relay', relay)
    with pytest.raises(routing.LocalCapacity) as caught:
        routing.local_completion([{'role': 'user', 'content': 'x' * 10000}], SCHEMA, 450)
    assert getattr(caught.value, 'local_capacity', None) == {
        'version': 1, 'source': 'legacy_guard_upper_bound', 'context_tokens': 8192,
        'legacy_guard_units': 11090, 'requested_output_tokens': 450}
    assert relay.call_count == 1


@pytest.mark.parametrize('value', [None, {}, dict(NATIVE, version=True), dict(NATIVE, version=2),
    dict(NATIVE, prompt_tokens=True), dict(NATIVE, prompt_tokens=8192), dict(NATIVE, prompt_tokens=-1),
    dict(NATIVE, prompt_tokens=10_000_001), dict(NATIVE, prompt_tokens=93917.0),
    dict(NATIVE, context_tokens=16384), dict(NATIVE, requested_output_tokens=0),
    dict(NATIVE, requested_output_tokens=True), dict(NATIVE, requested_output_tokens=2049),
    dict(NATIVE, raw_prompt='PRIVATE_SENTINEL'), dict(NATIVE, source='unknown')])
def test_capacity_schema_strict_and_identical_in_standalone_gateway(value):
    assert routing.safe_local_capacity(value) == gateway().safe_local_capacity(value) == {}


@pytest.mark.parametrize('value', [NATIVE,
    dict(NATIVE, requested_output_tokens=450),
    {'version': 1, 'source': 'native_capacity_unspecified', 'context_tokens': 8192},
    {'version': 1, 'source': 'legacy_guard_upper_bound', 'context_tokens': 8192, 'legacy_guard_units': 10000},
    {'version': 1, 'source': 'gateway_request_bytes', 'request_bytes': 131073, 'request_byte_limit': 131072}])
def test_valid_capacity_shapes_are_copied_and_not_conflated(value):
    assert routing.safe_local_capacity(value) == gateway().safe_local_capacity(value) == value
    assert routing.safe_local_capacity(value) is not value


def test_all_maximal_capacity_shapes_fit_header_and_retained_attempt_bound():
    samples = [dict(NATIVE, prompt_tokens=10_000_000),
        {'version': 1, 'source': 'native_capacity_unspecified', 'context_tokens': 8192},
        {'version': 1, 'source': 'legacy_guard_upper_bound', 'context_tokens': 8192, 'legacy_guard_units': 10_000_000},
        {'version': 1, 'source': 'gateway_request_bytes', 'request_bytes': 10_000_000, 'request_byte_limit': 131072}]
    for sample in samples:
        sample['requested_output_tokens'] = 2048
        checked = routing.safe_local_capacity(sample)
        assert checked == sample
        assert len(json.dumps(checked, separators=(',', ':')).encode('ascii')) < 256
        assert len(json.dumps(checked).encode('ascii')) < 256


@pytest.mark.parametrize('status,body', [(503, {'reason': 'local_context_capacity'}),
    (413, {'reason': 'other'}), (413, {'reason': 'local_context_capacity', 'extra': True})])
def test_capacity_header_never_overrides_other_http_failure(monkeypatch, status, body):
    import requests
    response = Mock(status=status)
    response.read.return_value = json.dumps(body).encode()
    response.getheader.return_value = json.dumps(NATIVE)
    conn = Mock()
    conn.getresponse.return_value = response
    monkeypatch.setattr(routing, 'UnixHTTP', lambda *a, **k: conn)
    with pytest.raises(requests.ConnectionError) as caught:
        REAL_RELAY('POST', '/completion', {})
    assert not isinstance(caught.value, routing.LocalCapacity)
    assert not getattr(caught.value, 'local_capacity', None)
    response.getheader.assert_not_called()


@pytest.mark.parametrize('header', [None, '', 'x' * 513, json.dumps(dict(NATIVE, prompt='PRIVATE_SENTINEL')),
    '{"version":1,"version":1,"source":"native_token_limit","context_tokens":8192,"prompt_tokens":93917}',
    json.dumps(NATIVE) + '\r\nPRIVATE_SENTINEL', '{"version":NaN}', '[]'])
def test_bad_or_old_header_does_not_change_capacity_classification(monkeypatch, header):
    response = Mock(status=413)
    response.read.return_value = b'{"reason":"local_context_capacity"}'
    response.getheader.return_value = header
    conn = Mock()
    conn.getresponse.return_value = response
    monkeypatch.setattr(routing, 'UnixHTTP', lambda *a, **k: conn)
    with pytest.raises(routing.LocalCapacity) as caught:
        REAL_RELAY('POST', '/completion', {})
    assert not getattr(caught.value, 'local_capacity', None)
    assert 'PRIVATE_SENTINEL' not in str(caught.value)


def test_native_unspecified_error_never_fabricates_prompt_count():
    g = gateway()
    evidence = g.context_capacity_evidence({'error': 'the input length exceeds the context length'})
    assert evidence == {'version': 1, 'source': 'native_capacity_unspecified', 'context_tokens': 8192}
    assert g.context_capacity_evidence({'error': 'PRIVATE_SENTINEL'}) == {}


def test_gateway_transport_bytes_are_exact_not_prompt_tokens():
    g = gateway()
    payload = dict(protocol=1, model=g.MODEL, digest=g.DIGEST,
        messages=[{'role': 'user', 'content': 'א' * 70000}], schema=SCHEMA, predict=450, request_id='synthetic')
    engine = g.Inference()
    engine.http = Mock(side_effect=AssertionError('inference forbidden'))
    with pytest.raises(g.ContextCapacity) as caught:
        engine.complete(payload)
    assert caught.value.local_capacity == {
        'version': 1, 'source': 'gateway_request_bytes', 'request_byte_limit': 131072,
        'request_bytes': len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()),
        'requested_output_tokens': 450}
    engine.http.assert_not_called()


def test_real_mocked_gateway_handler_header_relay_and_final_consumer(fixture, monkeypatch):
    _, paid, budget, _, ledger = fixture
    g = gateway()
    engine = g.Inference()
    engine.loaded = True
    engine.at = time.monotonic()
    upstream = Mock(status_code=400)
    upstream.iter_content.return_value = [json.dumps(native_error()).encode()]
    upstream.__enter__ = Mock(return_value=upstream)
    upstream.__exit__ = Mock(return_value=False)
    session = Mock()
    session.request.return_value = upstream
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(g.requests, 'Session', lambda: session)
    actual_http = engine.http
    engine.http = lambda method, path, payload=None, **kw: (
        {'models': [{'name': g.MODEL, 'digest': g.DIGEST}]} if path == '/api/tags'
        else actual_http(method, path, payload, **kw))
    outputs = []

    class Connection:
        sock = None

        def request(self, method, path, *, body, headers):
            self.body = body

        def getresponse(self):
            h = object.__new__(g.handler(engine))
            h.path = '/completion'
            h.headers = {'Content-Length': str(len(self.body))}
            h.connection = Mock()
            h.rfile = io.BytesIO(self.body)
            h.wfile = io.BytesIO()
            status = []
            headers = {}
            h.send_response = status.append
            h.send_header = headers.__setitem__
            h.end_headers = lambda: None
            h.do_POST()
            raw = h.wfile.getvalue()
            outputs.append((raw, headers))
            return Mock(status=status[0], read=lambda limit: raw[:limit],
                        getheader=lambda key: headers.get(key))

        def close(self):
            pass

    monkeypatch.setattr(routing, 'UnixHTTP', lambda *a, **k: Connection())
    monkeypatch.setattr(routing, 'relay', lambda method, path, payload=None, **kw:
        engine.health() if path == '/health' else REAL_RELAY(method, path, payload, **kw))
    paid.side_effect = None
    paid.return_value = cloud(DECISION)
    messages = [{'role': 'system', 'content': 'No missing facts.'},
                {'role': 'user', 'content': 'Complete עברית evidence ' + 'facts ' * 3000}]
    before = copy.deepcopy(messages)
    trace = final_ai.new_trace('synthetic', 'TEST', 1)
    token = final_ai.TRACE.set(trace)
    try:
        assert final_ai.review(messages, lambda value: value) == DECISION
    finally:
        final_ai.TRACE.reset(token)
    assert trace['attempts'][0]['local_capacity'] == dict(NATIVE, requested_output_tokens=450)
    assert outputs[0][0] == b'{"reason": "local_context_capacity"}'  # old reader's exact JSON body
    assert len(outputs[0][1][g.CAPACITY_HEADER]) <= 512
    assert 'local_capacity' not in trace['attempts'][1]
    assert messages == before == session.request.call_args.kwargs['json']['messages']
    sent = session.request.call_args.kwargs['json']
    assert sent['options'] == {'temperature': 0, 'num_ctx': 8192, 'num_predict': 450}
    assert sent['truncate'] is False and sent['shift'] is False
    assert paid.call_args.kwargs['json']['messages'] == before
    assert budget.call_count == paid.call_count == 1 and ledger.call_count == 2
    assert routing._until == 0 and engine.health()['ready']


def test_paid_error_cannot_inject_local_capacity(fixture, monkeypatch):
    _, paid, _, _, _ = fixture
    monkeypatch.setenv('AI_INFERENCE_MODE', 'cloud_only')
    failure = routing.LocalCapacity('local_context_capacity')
    failure.local_capacity = NATIVE
    paid.side_effect = failure
    trace = final_ai.new_trace('synthetic', 'TEST', 1)
    token = final_ai.TRACE.set(trace)
    try:
        with pytest.raises(routing.LocalCapacity):
            final_ai.review([{'role': 'user', 'content': 'synthetic'}], lambda value: value)
    finally:
        final_ai.TRACE.reset(token)
    assert all('local_capacity' not in row for row in trace['attempts'])


def test_real_stock_review_writer_roundtrip_keeps_only_bounded_capacity(db, clock, fixture, monkeypatch):
    import database
    import stock_scanner as scanner
    from test_review_evidence import candidate, NOW
    _, paid, _, _, _ = fixture
    monkeypatch.setattr(final_ai, 'persist', REAL_PERSIST)
    failure = routing.LocalCapacity('local_context_capacity')
    failure.local_capacity = dict(NATIVE, requested_output_tokens=450)
    monkeypatch.setattr(routing, 'local_completion', Mock(side_effect=failure))
    paid.side_effect = None
    paid.return_value = cloud(dict(DECISION, entry_price_relation='equal', entry_price_concern='none'))
    clock.instant = NOW
    c = candidate()
    c['validated_target_plan'] = {'entry': 110, 'stop': 100, 'targets': [130]}
    trace = final_ai.new_trace('synthetic-scan', 'TEST', 1)
    token = final_ai.TRACE.set(trace)
    try:
        assert scanner.ai_review(c, [], {})['action'] == 'HOLD'
        REAL_PERSIST(trace)  # same-review idempotent upsert, no duplicate attempt
    finally:
        final_ai.TRACE.reset(token)
    with database.get_db_connection() as conn:
        rows = conn.execute('SELECT * FROM scanner_final_ai_telemetry').fetchall()
        assert len(rows) == 1
        stored = json.loads(rows[0]['attempts_json'])
        assert len(stored) == 2 and rows[0]['retry_count'] == 1
        assert stored[0]['local_capacity'] == dict(NATIVE, requested_output_tokens=450)
        assert len(json.dumps(stored[0]['local_capacity']).encode()) < 256
        assert 'local_capacity' not in stored[1]
        assert stored[0]['input_tokens'] is None and rows[0]['input_tokens'] is None
        assert len(json.dumps(stored).encode()) < 4096
        assert 'Complete synthetic evidence' not in rows[0]['attempts_json']
        assert conn.execute('SELECT count(*) FROM scanner_orders').fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM scanner_candidates WHERE stage='review_input'").fetchone()[0] == 1
