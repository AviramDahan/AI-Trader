"""Leave recovery time between local news generations in the scanner process."""
from contextlib import contextmanager
import os
import threading
import time


class NewsPacer:
    def __init__(self):
        self._lock = threading.Lock()
        self._next_at = 0.0

    @contextmanager
    def slot(self):
        with self._lock:
            delay = self._next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            started = time.monotonic()
            try:
                yield
            finally:
                finished = time.monotonic()
                # Short calls still get a break. Cap longer rests well below
                # Ollama's idle unload window to avoid repeated cold loads.
                self._next_at = finished + min(12.0, max(3.0, finished - started))


_pacer = NewsPacer()


@contextmanager
def slot():
    if os.getenv('AI_TRADER_CLOUD') == 'true':
        with _pacer.slot():
            yield
    else:
        yield
