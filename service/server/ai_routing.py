"""Inference only routing. No trading writes, model shopping or nested retries.

Cloud-only is the unchanged default. A failed local generation consumes an
existing attempt; it never adds a request to the caller's retry/repair allowance.
The private relay is a Unix socket, NOT an internet-accessible Ollama endpoint.
"""
import http.client
import json
import os
import socket
import threading
import time
import uuid

import jsonschema
import requests

MODEL = 'gemma4:12b'
DIGEST = '6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b'
PROTOCOL = 1
MAX_BYTES = 131072
CONTEXT = 8192
CONTEXT_POLICY = 'no_truncate_no_shift_v1'
CAPACITY_HEADER = 'X-AI-Local-Capacity'
LOCAL_TRANSPORT_REASONS = frozenset({
    'relay_http_error', 'relay_response_too_large', 'relay_invalid_json',
    'relay_timeout', 'relay_socket_error', 'relay_http_protocol_error',
})
_lock = threading.Lock()
_until = 0.0


class LocalCapacity(requests.ConnectionError):
    """Capacity rejection: fail over without poisoning healthy smaller jobs."""


def safe_local_capacity(value):
    """Optional diagnostic only: native tokens and legacy byte-units differ.

    Keep this narrow v1 schema in sync with the standalone PC gateway. Missing
    old-gateway metadata stays unknown; it never changes capacity selection.
    """
    if type(value) is not dict or type(value.get('version')) is not int or value['version'] != 1:
        return {}
    source = value.get('source')
    shapes = {
        'native_token_limit': {'context_tokens', 'prompt_tokens'},
        'native_capacity_unspecified': {'context_tokens'},
        'legacy_guard_upper_bound': {'context_tokens', 'legacy_guard_units'},
        'gateway_request_bytes': {'request_bytes', 'request_byte_limit'},
    }
    if type(source) is not str or source not in shapes:
        return {}
    required = {'version', 'source'} | shapes[source]
    if set(value) not in (required, required | {'requested_output_tokens'}):
        return {}
    if source != 'gateway_request_bytes':
        if type(value['context_tokens']) is not int or value['context_tokens'] != CONTEXT:
            return {}
    else:
        if type(value['request_byte_limit']) is not int or value['request_byte_limit'] != MAX_BYTES:
            return {}
    name, lower = (('prompt_tokens', CONTEXT) if source == 'native_token_limit' else
                   ('legacy_guard_units', CONTEXT) if source == 'legacy_guard_upper_bound' else
                   ('request_bytes', MAX_BYTES))
    if source != 'native_capacity_unspecified':
        if type(value[name]) is not int or not lower < value[name] <= 10_000_000:
            return {}
    if 'requested_output_tokens' in value:
        predict = value['requested_output_tokens']
        if type(predict) is not int or not 1 <= predict <= 2048:
            return {}
    return dict(value)


def _capacity_header(value):
    if (type(value) is not str or len(value) > 512
            or any(not 32 <= ord(ch) < 127 for ch in value)):
        return {}
    try:
        return safe_local_capacity(_strict(value))
    except (ValueError, RecursionError):
        return {}


def fallback_reason(exc):
    return 'local_context_capacity' if isinstance(exc, LocalCapacity) else 'local_transport_failed'


def safe_local_transport_failure(value):
    """Fixed cloud-observed categories, not an inference about the PC cause."""
    if type(value) is not dict:
        return {}
    reason = value.get('reason')
    if type(reason) is not str or reason not in LOCAL_TRANSPORT_REASONS:
        return {}
    result = {'reason': reason}
    status = value.get('http_status')
    if type(status) is int and 100 <= status <= 599:
        result['http_status'] = status
    return result


def _local_transport_error(reason, status=None):
    error = requests.ConnectionError('local_relay_unavailable')
    error.local_transport_failure = safe_local_transport_failure(
        {'reason': reason, 'http_status': status})
    return error


def enabled():
    mode = os.getenv('AI_INFERENCE_MODE', 'cloud_only').strip()
    if mode not in {'cloud_only', 'ollama_first'}:
        raise ValueError('invalid_ai_inference_mode')
    return mode == 'ollama_first'


def _strict(raw):
    from news_structured_envelope import _pairs, _constant
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except RecursionError:
        raise ValueError('invalid_response_structure') from None


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.host)


def relay(method, path, payload=None, timeout=2):
    """One bounded private request; never follows redirects or environment proxies."""
    endpoint = os.getenv('OLLAMA_RELAY_SOCKET', '/run/ollama/relay.sock')
    if not endpoint.startswith('/run/ollama/') or '..' in endpoint.split('/'):
        raise ValueError('invalid_private_relay_socket')
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
    if body is not None and len(body) > MAX_BYTES:
        raise requests.ConnectionError('local_request_too_large')
    conn = UnixHTTP(endpoint, timeout=timeout)
    active_socket = [None]
    response = None
    decoding = False
    def abort():
        sock = active_socket[0] or conn.sock
        if sock is not None:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
    timer = threading.Timer(timeout, abort)
    timer.daemon = True
    timer.start()
    try:
        conn.request(method, path, body=body, headers={'Content-Type': 'application/json'})
        active_socket[0] = conn.sock
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise _local_transport_error('relay_response_too_large', response.status)
        if response.status == 413:
            decoding = True
            capacity = _strict(raw) == {'reason': 'local_context_capacity'}
            decoding = False
            if capacity:
                error = LocalCapacity('local_context_capacity')
                evidence = _capacity_header(response.getheader(CAPACITY_HEADER))
                if evidence:
                    error.local_capacity = evidence
                raise error
        if response.status != 200:
            raise _local_transport_error('relay_http_error', response.status)
        decoding = True
        return _strict(raw)
    except LocalCapacity:
        raise
    except TimeoutError:
        raise _local_transport_error('relay_timeout', getattr(response, 'status', None)) from None
    except http.client.HTTPException:
        raise _local_transport_error('relay_http_protocol_error', getattr(response, 'status', None)) from None
    except OSError as exc:
        known = safe_local_transport_failure(getattr(exc, 'local_transport_failure', None))
        raise _local_transport_error(known.get('reason', 'relay_socket_error'),
            known.get('http_status', getattr(response, 'status', None))) from None
    except (ValueError, RecursionError):
        reason = 'relay_invalid_json' if decoding else 'relay_http_protocol_error'
        raise _local_transport_error(reason, getattr(response, 'status', None)) from None
    finally:
        timer.cancel()
        if response is not None:response.close()
        conn.close()


def ready():
    if not enabled():
        return False
    with _lock:
        if time.monotonic() < _until:
            return False
    try:
        state = relay('GET', '/health')
        return (isinstance(state, dict) and type(state.get('protocol')) is int and state.get('protocol') == PROTOCOL
                and state.get('ready') is True and state.get('model') == MODEL
                and state.get('digest') == DIGEST and type(state.get('capacity')) is int and state.get('capacity') == 1)
    except requests.RequestException:
        failed()
        return False


def failed():
    global _until
    with _lock:
        _until = time.monotonic() + 60


def check_available():
    """Pre-job spend check. Every paid HTTP attempt still checks the hard cap."""
    if not ready():
        from ai_budget import check
        check()


class Route:
    def __init__(self, provider, model):
        requested = enabled()
        from news_events.call_context import CURRENT
        # A canonical stage owns its ONE shared fallback. Provider selection
        # must not depend on an unrelated process-wide outage cooldown.
        stage = (CURRENT.get() or {}).get('stage', '')
        canonical_fallback = isinstance(stage, str) and stage.startswith('local_fallback:')
        self.provider = 'ollama_relay' if requested and not canonical_fallback and ready() else provider
        self.model = MODEL if self.provider == 'ollama_relay' else model
        self.cloud_provider, self.cloud_model = provider, model
        self.fallback_reason = ('canonical_local_fallback' if requested and canonical_fallback else
                               'local_not_ready' if requested and self.provider != 'ollama_relay' else None)

    def fallback(self, reason):
        if self.provider == 'ollama_relay':
            if reason != 'local_context_capacity':
                failed()
            self.provider, self.model = self.cloud_provider, self.cloud_model
            self.fallback_reason = reason

    def provenance(self):
        return dict(provider=self.provider, model=self.model,
                    model_digest=DIGEST if self.provider == 'ollama_relay' else None,
                    fallback_reason=self.fallback_reason)


def local_completion(messages, schema, predict, *, validate_response=True):
    deadline = time.monotonic() + 50
    # Rolling update: the old gateway remains safe for its conservative bound,
    # but must NEVER receive an oversized request on the new token-aware path.
    state = relay('GET', '/health')
    guarded = (isinstance(state, dict) and state.get('context_policy') == CONTEXT_POLICY
               and type(state.get('context_length')) is int and state['context_length'] == CONTEXT)
    if not guarded:
        legacy_units = sum(len(m['content'].encode())+128 for m in messages)+predict+512
        if legacy_units > CONTEXT:
            error = LocalCapacity('local_context_capacity')
            error.local_capacity = safe_local_capacity(dict(version=1, source='legacy_guard_upper_bound',
                context_tokens=CONTEXT, legacy_guard_units=legacy_units, requested_output_tokens=predict))
            raise error
    try:
        body = relay('POST', '/completion', dict(protocol=PROTOCOL, model=MODEL, digest=DIGEST,
            messages=messages, schema=schema, predict=predict, request_id=uuid.uuid4().hex), timeout=50)
    except LocalCapacity as exc:
        evidence = safe_local_capacity(getattr(exc, 'local_capacity', None))
        if evidence:
            evidence['requested_output_tokens'] = predict
            exc.local_capacity = safe_local_capacity(evidence)
        raise
    if time.monotonic() > deadline:
        raise requests.Timeout('local_deadline_exceeded')
    if isinstance(body, dict) and body.get('done_reason') == 'length':
        error = ValueError('ai_output_truncated')
        if (body.get('model') == MODEL and body.get('model_digest') == DIGEST
                and body.get('done') is True):
            # Never attach the response/content to an exception. Failure occurs
            # before the caller receives body, so carry only bounded metadata.
            error.local_failure_usage = safe_local_failure_usage(body)
        raise error from None
    if (not isinstance(body, dict) or body.get('model') != MODEL or body.get('model_digest') != DIGEST
            or body.get('done') is not True or body.get('done_reason') != 'stop'
            or not isinstance(body.get('message'), dict) or body['message'].get('tool_calls')
            or body['message'].get('refusal')):
        raise ValueError('invalid_response_structure')
    content = body['message'].get('content')
    if not isinstance(content, str) or len(content.encode()) > 65536:
        raise ValueError('invalid_response_structure')
    value = _strict(content)
    if schema and validate_response:
        jsonschema.validate(value, schema)
    if not isinstance(value, dict):
        raise ValueError('ai_object_required')
    return value, body


def safe_local_failure_usage(value):
    """Revalidate the narrow truncation bridge at capture and persistence."""
    if type(value) is not dict or value.get('done_reason') != 'length':
        return {}
    def counter(name):
        v = value.get(name)
        # Telemetry bound only; never a generation/context setting or estimate.
        return v if type(v) is int and 0 <= v <= 10_000_000 else None
    return {'done_reason': 'length', 'prompt_eval_count': counter('prompt_eval_count'),
            'eval_count': counter('eval_count')}


def local_usage(body):
    """Known zero API spend, not a fabricated OpenRouter billing response."""
    body = body if isinstance(body, dict) else {}
    return {'id': 'ollama:' + uuid.uuid4().hex, 'usage': {
        'cost': 0, 'prompt_tokens': body.get('prompt_eval_count'),
        'completion_tokens': body.get('eval_count')}}


def ledger_model(route):
    return ('ollama/' + MODEL + '@' + DIGEST if route.provider == 'ollama_relay' else route.model)


def native_messages(messages, structured_news=False):
    if not structured_news:
        return messages
    from news_structured_envelope import output_instruction
    return [dict(m, content=m['content'].replace(output_instruction(),
        'Return exactly one JSON object matching the supplied schema. No tools, markdown or extra content.'))
        if m['role'] == 'system' else m for m in messages]
