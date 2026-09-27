"""Run a selected test set with no .env, real DB, HTTP, Telegram or paid AI."""
import os
import socket
import sys
import threading
from pathlib import Path
import dotenv

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'service/server'), str(root / 'service/server/tests')]
for key in list(os.environ):
    if key.startswith(('TELEGRAM_', 'OPENROUTER_', 'STOCK_SCANNER_', 'AI_TRADER_', 'NEWS_', 'OLLAMA_')) or key in ('DATABASE_URL', 'DATABASE_URL_FILE', 'AI_PROVIDER'):
        os.environ.pop(key, None)
original_values = dotenv.dotenv_values
dotenv.load_dotenv = lambda *a, **kw: False


def fixture_values(path=None, *args, **kwargs):
    # Permit the committed non-secret example and temporary test fixtures, but
    # never discover or load a user's real .env from the repository.
    if path is None or Path(path).resolve() in {root / '.env', root / 'service/.env'}:
        return {}
    return original_values(path, *args, **kwargs)


dotenv.dotenv_values = fixture_values


def blocked(*args, **kwargs):
    raise AssertionError('Network forbidden in isolated news tests')


# On Windows asyncio implements socketpair using a loopback connection. Permit
# only that internal socketpair operation, not arbitrary localhost/API traffic.
original_connect, original_pair = socket.socket.connect, socket.socketpair
pair_context = threading.local()


def connect(sock, address):
    if getattr(pair_context, 'active', False) and address[0] in ('127.0.0.1', '::1'):
        return original_connect(sock, address)
    return blocked()


def socketpair(*args, **kwargs):
    pair_context.active = True
    try:
        return original_pair(*args, **kwargs)
    finally:
        pair_context.active = False


socket.socket.connect = connect
socket.socketpair = socketpair
socket.create_connection = blocked
import pytest
paths = sys.argv[1:] or ['service/server/tests/test_news_evidence.py', 'service/server/tests/test_news_quality.py', 'service/server/tests/test_news_pipeline.py']
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', *paths]))
