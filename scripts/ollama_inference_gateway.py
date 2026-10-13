"""PC inference-only gateway. Loopback, pinned model, single slot, no app imports.

No DB/broker/Telegram/cloud API key, no shell execution, no unbounded Ollama
queue. Publish solely through a restricted outbound SSH Unix-socket tunnel.
"""
import argparse
import http.server
import json
import threading
import time

import requests

MODEL = 'gemma4:12b'
DIGEST = '6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b'
MAX_BYTES = 131072
CONTEXT = 8192


class Inference:
    def __init__(self):
        self.slot = threading.Lock()
        self.loaded = False
        self.at = 0.0
        self.version = None

    def http(self, method, path, payload=None, timeout=2):
        with requests.Session() as session:
            session.trust_env = False
            with session.request(method, 'http://127.0.0.1:11434' + path, json=payload,
                                 timeout=(2, timeout), stream=True, allow_redirects=False) as r:
                if r.status_code != 200:
                    raise ValueError('ollama_unavailable')
                raw = bytearray()
                until = time.monotonic() + timeout
                for part in r.iter_content(4096):
                    raw.extend(part)
                    if len(raw) > MAX_BYTES or time.monotonic() > until:
                        raise ValueError('ollama_response_limit')
                return json.loads(raw)

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
            if not any(m['name'] == MODEL and m['digest'] == DIGEST and m.get('context_length') == CONTEXT for m in models):
                self.http('POST', '/api/chat', dict(model=MODEL, messages=[], stream=False,
                          keep_alive='20m', options={'num_ctx': CONTEXT}), timeout=90)
            models = self.http('GET', '/api/ps')['models']
            self.loaded = any(m['name'] == MODEL and m['digest'] == DIGEST
                and m.get('context_length') == CONTEXT for m in models)
            self.at = time.monotonic()
        except Exception:
            self.loaded = False
        finally:
            self.slot.release()

    def health(self):
        return dict(protocol=1, model=MODEL, digest=DIGEST, ollama_version=self.version,
            ready=self.loaded and time.monotonic()-self.at < 65 and not self.slot.locked(), capacity=1)

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
        # Conservative byte-token upper bound + template headroom. Never silently
        # truncate verified evidence into an apparently successful local decision.
        if sum(len(m['content'].encode())+128 for m in messages)+predict+512 > CONTEXT:
            raise ValueError('local_context_capacity')
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
            result = self.http('POST', '/api/chat', dict(model=MODEL, messages=messages,
                stream=False, think=False, keep_alive='20m', format=payload['schema'] or 'json',
                options={'temperature': 0, 'num_ctx': CONTEXT, 'num_predict': predict}), timeout=45)
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
