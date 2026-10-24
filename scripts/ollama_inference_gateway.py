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
KEEP_ALIVE = '2m'
KEEP_ALIVE_SECONDS = 120


class ContextCapacity(ValueError):
    """A bounded request does not fit; not an unavailable GPU/tunnel."""


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


class Inference:
    def __init__(self):
        self.slot = threading.Lock()
        self.loaded = False
        self.available = False
        self.at = 0.0
        self.version = None

    def http(self, method, path, payload=None, timeout=2):
        until = time.monotonic() + timeout
        with requests.Session() as session:
            session.trust_env = False
            with session.request(method, 'http://127.0.0.1:11434' + path, json=payload,
                                 timeout=(2, timeout), stream=True, allow_redirects=False) as r:
                raw = bytearray()
                if time.monotonic() > until:
                    raise requests.Timeout('ollama_deadline')
                for part in r.iter_content(4096):
                    raw.extend(part)
                    if len(raw) > MAX_BYTES or time.monotonic() > until:
                        raise ValueError('ollama_response_limit')
                data = json.loads(raw)
                if path == '/api/chat' and context_error(data):
                    raise ContextCapacity('local_context_capacity')
                if r.status_code != 200 or isinstance(data, dict) and data.get('error'):
                    raise ValueError('ollama_unavailable')
                return data

    def _bounded_http(self, deadline, method, path, payload=None, timeout=2):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise requests.Timeout('ollama_deadline')
        result = self.http(method, path, payload, timeout=min(timeout, remaining))
        if time.monotonic() > deadline:
            raise requests.Timeout('ollama_deadline')
        return result

    def _refresh_locked(self, deadline=None):
        """Observe metadata only. A compatible cold runtime can accept work."""
        self.available = False
        try:
            def observe(path):
                return (self.http('GET', path) if deadline is None else
                        self._bounded_http(deadline, 'GET', path))
            self.loaded = False
            tags = observe('/api/tags')
            if not any(m['name'] == MODEL and m['digest'] == DIGEST for m in tags['models']):
                return
            self.version = observe('/api/version')['version']
            if tuple(int(v) for v in self.version.split('.')) < (0,34,4):
                return
            models = observe('/api/ps')['models']
            if not isinstance(models, list):
                return
            # Cold is eligible; an incompatible resident instance is NOT.
            # Health must neither hide nor reload a wrong active context.
            if any(m['name'] == MODEL and (m.get('digest') != DIGEST or
                    m.get('context_length') != CONTEXT) for m in models):
                return
            self.loaded = any(m['name'] == MODEL and m['digest'] == DIGEST
                and m.get('context_length') == CONTEXT for m in models)
            self.available = True
            self.at = time.monotonic()
        except Exception:
            self.loaded = False

    def refresh(self):
        """Read-only periodic health; no preload, unload or generation."""
        if not self.slot.acquire(blocking=False):
            return
        try:
            self._refresh_locked()
        finally:
            self.slot.release()

    def _metadata_ready(self):
        return self.available and 0 <= time.monotonic()-self.at < 65

    def health(self):
        return dict(protocol=1, model=MODEL, digest=DIGEST, ollama_version=self.version,
            ready=self._metadata_ready() and not self.slot.locked(), capacity=1,
            context_policy=CONTEXT_POLICY, context_length=CONTEXT,
            model_loaded=self.loaded if self._metadata_ready() else None,
            load_policy='on_demand', keep_alive_seconds=KEEP_ALIVE_SECONDS)

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
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
            raise ContextCapacity('local_context_capacity')
        if payload['schema'] is not None:
            import jsonschema
            jsonschema.Draft202012Validator.check_schema(payload['schema'])
        if not self.slot.acquire(blocking=False):
            raise ValueError('local_not_ready')
        try:
            deadline = time.monotonic() + 45
            # Direct requests can also bootstrap read-only metadata. Never
            # require resident weights before allowing the request that loads
            # them. No queue: a second caller fails busy without another load.
            if not self._metadata_ready():
                self._refresh_locked(deadline)
            if not self._metadata_ready():
                raise ValueError('local_not_ready')
            tags = self._bounded_http(deadline, 'GET', '/api/tags')
            if not any(m['name'] == MODEL and m['digest'] == DIGEST for m in tags['models']):
                self.loaded = False
                raise ValueError('unapproved_model')
            result = self._bounded_http(deadline, 'POST', '/api/chat', dict(model=MODEL, messages=messages,
                stream=False, think=False, keep_alive=KEEP_ALIVE, format=payload['schema'] or 'json',
                truncate=False, shift=False,
                options={'temperature': 0, 'num_ctx': CONTEXT, 'num_predict': predict}), timeout=45)
            # No response can execute a command. The cloud owns validation/action.
            tags = self._bounded_http(deadline, 'GET', '/api/tags')
            if not any(m['name'] == MODEL and m['digest'] == DIGEST for m in tags['models']):
                self.loaded = False
                raise ValueError('model_changed_during_request')
            result['model_digest'] = DIGEST
            result['ollama_version'] = self.version
            self.loaded = True
            self.at = time.monotonic()
            return result
        except ContextCapacity:
            # Capacity remains a bounded request rejection, not an outage.
            raise
        except Exception:
            self.available = False
            self.loaded = False
            raise
        finally:
            self.slot.release()


def handler(engine):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # No prompts, credentials, private outputs or request paths logged.

        def respond(self, status, body):
            raw = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
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
            except ContextCapacity:
                try:
                    self.respond(413, {'reason': 'local_context_capacity'})
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
    def observe():
        while True:
            engine.refresh()
            time.sleep(30)
    threading.Thread(target=observe, daemon=True).start()
    server = BoundedServer(('127.0.0.1', args.port), handler(engine))
    server.serve_forever()


if __name__ == '__main__':
    main()
