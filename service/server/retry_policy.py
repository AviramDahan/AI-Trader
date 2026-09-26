"""Safe operational error metadata; never include response bodies or credentials."""
import json
import time
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

def retry_after(value, now=None):
    if not isinstance(value,(str,int,float)):return 0
    try:
        numeric=float(value)
        return max(0,numeric) if math.isfinite(numeric) else 0
    except (ValueError, TypeError):
        try:
            return max(0, (parsedate_to_datetime(value)-(now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0

def detail(exc):
    response=getattr(exc,'response',None)
    return json.dumps({'exception':type(exc).__name__,
        'http_status':getattr(response,'status_code',None),
        'retry_after_seconds':retry_after(response.headers.get('Retry-After')) if response is not None else 0})

class DeferredProviderError(RuntimeError):
    def __init__(self, status, delay):
        self.retry_after_seconds=delay
        self.status=status
        super().__init__(f'provider_http_{status};retry_after_seconds={delay}')

def defer_openrouter(response):
    """Persist cooldown; do not hold the scanner thread for a provider's long delay."""
    if response.status_code not in {429,500,502,503,504}:return
    delay=retry_after(response.headers.get('Retry-After'))
    if response.status_code==429: delay=max(60,delay)
    if delay<=0:return
    import os
    if os.getenv('AI_TRADER_CLOUD')=='true':
        from database import get_db_connection
        until=time.time()+delay
        with get_db_connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(719324,2)')
            old=c.execute("SELECT value_json FROM scanner_settings WHERE key='ai_provider_retry_after'").fetchone()
            if old:until=max(until,json.loads(old['value_json'])['until'])
            c.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('ai_provider_retry_after',?,?)
              ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
              (json.dumps({'until':until}),datetime.now(timezone.utc).isoformat()))
    raise DeferredProviderError(response.status_code,delay)
