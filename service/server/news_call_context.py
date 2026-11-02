"""Context-local links to existing usage rows, never a second cost ledger."""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256

CURRENT = ContextVar('news_evidence_call', default=None)
CHECKPOINT = ContextVar('news_checkpoint_call', default=None)


@contextmanager
def article(news_id, version, excerpt):
    token = CURRENT.set(dict(news_id=news_id, content_version=version, stage='source_analysis',
                            source_excerpt_hash=sha256(excerpt.encode()).hexdigest(),
                            source_excerpt_chars=len(excerpt)))
    try:
        yield
    finally:
        CURRENT.reset(token)


@contextmanager
def checkpoint_article(event_id, version, excerpt):
    # Canonical calls have their own usage linkage; never enter the legacy
    # news_id context or attempt to write the legacy integer-FK ledger.
    token = CHECKPOINT.set(dict(news_id='canonical:'+event_id, content_version=version,
                                source_excerpt_hash=sha256(excerpt.encode()).hexdigest(),
                                source_excerpt_chars=len(excerpt)))
    try:
        yield
    finally:
        CHECKPOINT.reset(token)


def call(stage, function, *args, **kwargs):
    value = CHECKPOINT.get() or CURRENT.get()
    legacy = CURRENT.get()
    token = CURRENT.set({**legacy, 'stage': stage} if legacy else None)
    try:
        return _checkpointed(stage, function, value, args, kwargs)
    finally:
        CURRENT.reset(token)


def _checkpointed(stage, function, context, args, kwargs):
    import json
    import os
    import jsonschema
    from datetime import datetime, timezone
    from ai_routing import MODEL, DIGEST, enabled, openrouter_fallback_enabled
    schema = kwargs.get('schema')
    stages = {'source_analysis','quality_review','editorial_repair','repair_review','event_deduplication'}
    if not (context and stage in stages and isinstance(schema,dict) and enabled()
            and not openrouter_fallback_enabled()):
        return function(*args, **kwargs)
    # Full prompt/input/schema/output budget, source revision and pinned model.
    # No request body, stale peer set or editorial draft may cross this identity.
    identity = dict(policy='strict-news-stage-v1', article=context, stage=stage,
        args=args, kwargs=kwargs, model=MODEL, digest=DIGEST,
        configured_model=os.getenv('OLLAMA_NEWS_MODEL'),
        cloud_model=os.getenv('OPENROUTER_NEWS_MODEL'))
    raw=json.dumps(identity,sort_keys=True,ensure_ascii=True,allow_nan=False)
    key='news-stage-v1:'+sha256(raw.encode()).hexdigest()
    from database import get_db_connection
    with get_db_connection() as c:
        row=c.execute('SELECT result_json FROM news_review_cache WHERE cache_key=?',(key,)).fetchone()
    if row and row['result_json']:
        result=json.loads(row['result_json'])
        jsonschema.validate(result,schema)  # Never trust a saved invalid draft.
        if isinstance(kwargs.get('usage_sink'),dict):
            kwargs['usage_sink']['checkpoint_hit']=True
        return result
    result=function(*args, **kwargs)
    jsonschema.validate(result,schema)
    serialized=json.dumps(result,ensure_ascii=False,allow_nan=False)
    with get_db_connection() as c:
        c.execute('''INSERT INTO news_review_cache(cache_key,content_version,result_json,created_at)
            VALUES(?,?,?,?) ON CONFLICT(cache_key) DO NOTHING''',
            (key,context['content_version'],serialized,datetime.now(timezone.utc).isoformat()))
    return result
