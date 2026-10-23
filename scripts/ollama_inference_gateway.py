"""PC inference-only gateway. Loopback, pinned model, single slot, no app imports.

No DB/broker/Telegram/cloud API key, no shell execution, no unbounded Ollama
queue. Publish solely through a restricted outbound SSH Unix-socket tunnel.
"""
import argparse
import http.server
import json
import re
import threading
import time

import requests

MODEL = 'gemma4:12b'
DIGEST = '6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b'
MAX_BYTES = 131072
CONTEXT = 8192
CONTEXT_POLICY = 'no_truncate_no_shift_v1'
CAPACITY_HEADER = 'X-AI-Local-Capacity'


class ContextCapacity(ValueError):
    """A bounded request does not fit; not an unavailable GPU/tunnel."""

    def __init__(self, reason='local_context_capacity', evidence=None):
        super().__init__(reason)
        self.local_capacity = safe_local_capacity(evidence)


def safe_local_capacity(value):
    """Standalone copy of the cloud's optional, fixed capacity-evidence v1."""
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


def context_error(data):
    error = data.get('error') if isinstance(data, dict) else None
    # Native Gemma in the pinned runtime embeds the runner's structured 400
    # error as a JSON string. Recognize only this validated capacity envelope;
    # never classify arbitrary provider text/auth failures as a healthy GPU.
    if isinstance(error, str) and error.startswith('{') and len(error) <= 2048:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate_error_key')
                result[key] = value
            return result
        try:
            wrapped = json.loads(error, object_pairs_hook=unique)
            if not isinstance(wrapped, dict) or set(wrapped) != {'error'}:
                return False
            detail = wrapped['error']
            if not isinstance(detail, dict) or set(detail) != {
                    'code','message','type','n_prompt_tokens','n_ctx'}:
                return False
            if (type(detail['code']) is not int or detail['code'] != 400
                    or detail['type'] != 'exceed_context_size_error'
                    or type(detail['n_prompt_tokens']) is not int
                    or type(detail['n_ctx']) is not int
                    or detail['n_ctx'] != CONTEXT
                    or detail['n_prompt_tokens'] <= detail['n_ctx']):
                return False
            match = re.fullmatch(r'request \((\d+) tokens\) exceeds the available context size '
                                 r'\((\d+) tokens\), try increasing it', detail['message'])
            return bool(match and (int(match[1]), int(match[2])) ==
                        (detail['n_prompt_tokens'], detail['n_ctx']))
        except (ValueError, TypeError, KeyError):
            return False
    return isinstance(error, str) and bool(re.fullmatch(
        r'(?:the prompt is longer than the context length currently available to the model; '
        r'shorten the prompt, adjust the context length in settings, or use a model with a longer context length'
        r'|the input length exceeds the context length'
        r'|request \(\d+ tokens\) exceeds the available context size \(\d+ tokens\), try increasing it)', error))


def context_capacity_evidence(data):
    """Recognize exactly the existing refusal; never retain its error text."""
    if not context_error(data):
        return {}
    evidence = dict(version=1, source='native_capacity_unspecified', context_tokens=CONTEXT)
    error = data['error']
    # context_error already proved the exact keys, duplicate-key exclusion,
    # type/count/message agreement and configured context on this branch.
    if error.startswith('{'):
        detail = json.loads(error)['error']
        measured = safe_local_capacity(dict(version=1, source='native_token_limit',
            context_tokens=detail['n_ctx'], prompt_tokens=detail['n_prompt_tokens']))
        return measured or evidence
    match = re.fullmatch(r'request \((\d+) tokens\) exceeds the available context size '
                         r'\((\d+) tokens\), try increasing it', error)
    if match:
        measured = safe_local_capacity(dict(version=1, source='native_token_limit',
            context_tokens=int(match[2]), prompt_tokens=int(match[1])))
        if measured:
            return measured
    return evidence


class Inference:
    def __init__(self):
        self.slot = threading.Lock()
        self.loaded = False
        self.at = 0.0
        self.version = None
        self.guard_warmed = False

    def http(self, method, path, payload=None, timeout=2):
        with requests.Session() as session:
            session.trust_env = False
            with session.request(method, 'http://127.0.0.1:11434' + path, json=payload,
                                 timeout=(2, timeout), stream=True, allow_redirects=False) as r:
                raw = bytearray()
                until = time.monotonic() + timeout
                for part in r.iter_content(4096):
                    raw.extend(part)
                    if len(raw) > MAX_BYTES or time.monotonic() > until:
                        raise ValueError('ollama_response_limit')
                data = json.loads(raw)
                if path == '/api/chat' and context_error(data):
                    raise ContextCapacity(evidence=context_capacity_evidence(data))
                if r.status_code != 200 or isinstance(data, dict) and data.get('error'):
                    raise ValueError('ollama_unavailable')
                return data

    def refresh(self):
        """Metadata + bounded model preload; never warms while generating."""
        if not self.slot.acquire(blocking=False):
            return
        try:
            self.loaded = False
            tags = self.http('GET', '/api/tags')
            if not any(m['name'] == MODEL and m['digest'] == DIGEST for m in tags['models']):
                return
            self.version = self.http('GET', '/api/version')['version']
            if tuple(int(v) for v in self.version.split('.')) < (0,34,4):
                return
            models = self.http('GET', '/api/ps')['models']
            if not self.guard_warmed or not any(m['name'] == MODEL and m['digest'] == DIGEST and m.get('context_length') == CONTEXT for m in models):
                self.http('POST', '/api/chat', dict(model=MODEL, messages=[], stream=False,
                          keep_alive='20m', truncate=False, shift=False, options={'num_ctx': CONTEXT}), timeout=90)
            models = self.http('GET', '/api/ps')['models']
            self.loaded = any(m['name'] == MODEL and m['digest'] == DIGEST
                and m.get('context_length') == CONTEXT for m in models)
            self.guard_warmed = self.loaded
            self.at = time.monotonic()
        except Exception:
            self.loaded = False
        finally:
            self.slot.release()

    def health(self):
        return dict(protocol=1, model=MODEL, digest=DIGEST, ollama_version=self.version,
            ready=self.loaded and time.monotonic()-self.at < 65 and not self.slot.locked(), capacity=1,
            context_policy=CONTEXT_POLICY, context_length=CONTEXT)

    def complete(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'protocol','model','digest','messages','schema','predict','request_id'}:
            raise ValueError('invalid_request')
        if type(payload['protocol']) is not int or payload['protocol'] != 1 or payload['model'] != MODEL or payload['digest'] != DIGEST:
            raise ValueError('unapproved_model')
        messages, predict = payload['messages'], payload['predict']
        if not isinstance(predict, int) or isinstance(predict, bool) or not 1 <= predict <= 2048:
            raise ValueError('invalid_predict')
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 16
                or any(not isinstance(m, dict) or set(m) != {'role','content'}
                    or m['role'] not in {'system','user','assistant'} or not isinstance(m['content'], str) for m in messages)):
            raise ValueError('invalid_messages')
        # Bytes are a transport limit, not a token count. The pinned runtime
        # applies its actual tokenizer/template; BOTH history truncation and
        # generation context shifting must be disabled. Oversize never drops
        # facts, and a context-length/unfinished result is not a valid decision.
        request_bytes = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
        if request_bytes > MAX_BYTES:
            raise ContextCapacity(evidence=dict(version=1, source='gateway_request_bytes',
                request_bytes=request_bytes, request_byte_limit=MAX_BYTES, requested_output_tokens=predict))
        if payload['schema'] is not None:
            import jsonschema
            jsonschema.Draft202012Validator.check_schema(payload['schema'])
        if not self.health()['ready'] or not self.slot.acquire(blocking=False):
            raise ValueError('local_not_ready')
        try:
            tags = self.http('GET', '/api/tags')
            if not any(m['name'] == MODEL and m['digest'] == DIGEST for m in tags['models']):
                self.loaded = False
                raise ValueError('unapproved_model')
            try:
                result = self.http('POST', '/api/chat', dict(model=MODEL, messages=messages,
                    stream=False, think=False, keep_alive='20m', format=payload['schema'] or 'json',
                    truncate=False, shift=False,
                    options={'temperature': 0, 'num_ctx': CONTEXT, 'num_predict': predict}), timeout=45)
            except ContextCapacity as exc:
                evidence = safe_local_capacity(getattr(exc, 'local_capacity', None))
                if evidence:
                    evidence['requested_output_tokens'] = predict
                    exc.local_capacity = safe_local_capacity(evidence)
                raise
            # No response can execute a command. The cloud owns validation/action.
            tags = self.http('GET', '/api/tags')
            if not any(m['name'] == MODEL and m['digest'] == DIGEST for m in tags['models']):
                self.loaded = False
                raise ValueError('model_changed_during_request')
            result['model_digest'] = DIGEST
            result['ollama_version'] = self.version
            self.at = time.monotonic()
            return result
        finally:
            self.slot.release()


def handler(engine):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # No prompts, credentials, private outputs or request paths logged.

        def respond(self, status, body, capacity=None):
            raw = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            evidence = safe_local_capacity(capacity)
            if status == 413 and evidence:
                # Body is unchanged for old strict protocol-1 cloud readers.
                self.send_header(CAPACITY_HEADER, json.dumps(evidence, separators=(',', ':')))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.respond(200, engine.health()) if self.path == '/health' else self.respond(404, {})

        def do_POST(self):
            try:
                if self.path != '/completion' or self.headers.get('Transfer-Encoding'):
                    raise ValueError()
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BYTES:
                    raise ValueError()
                self.connection.settimeout(3)
                payload = json.loads(self.rfile.read(length))
                self.respond(200, engine.complete(payload))
            except ContextCapacity as exc:
                try:
                    self.respond(413, {'reason': 'local_context_capacity'},
                                 capacity=getattr(exc, 'local_capacity', None))
                except OSError:
                    pass
            except Exception:
                try:
                    self.respond(503, {'reason': 'local_inference_unavailable'})
                except OSError:
                    pass
    return Handler


class BoundedServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args):
        self.handlers = threading.BoundedSemaphore(8)
        super().__init__(*args)

    def process_request(self, request, client_address):
        if not self.handlers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.handlers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.handlers.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=11435)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('invalid_port')
    engine = Inference()
    def warm():
        while True:
            engine.refresh()
            time.sleep(30)
    threading.Thread(target=warm, daemon=True).start()
    server = BoundedServer(('127.0.0.1', args.port), handler(engine))
    server.serve_forever()


if __name__ == '__main__':
    main()
