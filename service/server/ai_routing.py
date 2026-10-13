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
_lock = threading.Lock()
_until = 0.0


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
    def abort():
        if conn.sock is not None:
            try:conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
    timer = threading.Timer(timeout, abort)
    timer.daemon = True
    timer.start()
    try:
        conn.request(method, path, body=body, headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if response.status != 200 or len(raw) > MAX_BYTES:
            raise requests.ConnectionError('local_relay_unavailable')
        return _strict(raw)
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        raise requests.ConnectionError('local_relay_unavailable') from None
    finally:
        timer.cancel()
        conn.close()


def ready():
    if not enabled():
        return False
    with _lock:
        if time.monotonic() < _until:
            return False
    try:
        state = relay('GET', '/health')
        return (isinstance(state, dict) and state.get('protocol') == PROTOCOL
                and state.get('ready') is True and state.get('model') == MODEL
                and state.get('digest') == DIGEST and state.get('capacity') == 1)
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
        self.provider = 'ollama_relay' if requested and ready() else provider
        self.model = MODEL if self.provider == 'ollama_relay' else model
        self.cloud_provider, self.cloud_model = provider, model
        self.fallback_reason = 'local_not_ready' if requested and self.provider != 'ollama_relay' else None

    def fallback(self, reason):
        if self.provider == 'ollama_relay':
            failed()
            self.provider, self.model = self.cloud_provider, self.cloud_model
            self.fallback_reason = reason

    def provenance(self):
        return dict(provider=self.provider, model=self.model,
                    model_digest=DIGEST if self.provider == 'ollama_relay' else None,
                    fallback_reason=self.fallback_reason)


def local_completion(messages, schema, predict, *, validate_response=True):
    deadline = time.monotonic() + 50
    body = relay('POST', '/completion', dict(protocol=PROTOCOL, model=MODEL, digest=DIGEST,
        messages=messages, schema=schema, predict=predict, request_id=uuid.uuid4().hex), timeout=50)
    if time.monotonic() > deadline:
        raise requests.Timeout('local_deadline_exceeded')
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
