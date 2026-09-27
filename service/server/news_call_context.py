"""Context-local links to existing usage rows, never a second cost ledger."""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256

CURRENT = ContextVar('news_evidence_call', default=None)


@contextmanager
def article(news_id, version, excerpt):
    token = CURRENT.set(dict(news_id=news_id, content_version=version, stage='source_analysis',
                            source_excerpt_hash=sha256(excerpt.encode()).hexdigest(),
                            source_excerpt_chars=len(excerpt)))
    try:
        yield
    finally:
        CURRENT.reset(token)


def call(stage, function, *args, **kwargs):
    value = CURRENT.get()
    token = CURRENT.set({**value, 'stage': stage} if value else None)
    try:
        return function(*args, **kwargs)
    finally:
        CURRENT.reset(token)
