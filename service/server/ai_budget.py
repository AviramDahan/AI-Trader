"""Cloud-only spend guard. No monitor imports; no transaction spans network IO.

The provider's monthly Guardrail is authoritative for concurrent requests. The
local check fails closed on unavailable usage and records durable internal alerts.
It is not a substitute for the provider hard cap.
"""
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
import requests


class BudgetUnavailable(RuntimeError):
    pass


def acquire_request_slot():
    """Shared request pacing for provider RPM quotas; never locks a price monitor.

    Reserve a slot in a short PostgreSQL transaction, then wait AFTER commit.
    Crashed callers only waste their reserved slot; they cannot cause a burst.
    """
    if os.getenv('AI_TRADER_CLOUD') != 'true':
        return
    from database import get_db_connection
    try:
        interval=float(os.getenv('OPENROUTER_MIN_REQUEST_INTERVAL_SECONDS','3.2'))
        if not math.isfinite(interval) or not 3.2 <= interval <= 60:
            raise ValueError()
        with get_db_connection() as conn:
            cur=conn.cursor()
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute('SELECT pg_advisory_xact_lock(719324,1)')
            now=float(cur.execute('SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS stamp').fetchone()['stamp'])
            row=cur.execute("SELECT value_json FROM scanner_settings WHERE key='ai_request_slot'").fetchone()
            slot=max(now,float(json.loads(row['value_json'])['next_at'])) if row else now
            delay=slot-now
            if delay > 30:
                raise BudgetUnavailable('ai_request_queue_busy')
            cur.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('ai_request_slot',?,?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
                (json.dumps({'next_at':slot+interval}),datetime.now(timezone.utc).isoformat()))
            conn.commit()
    except BudgetUnavailable:
        raise
    except Exception:
        raise BudgetUnavailable('ai_rate_limit_state_unavailable') from None
    if delay > 0:
        time.sleep(delay)


def persist(usage, limit, stamp):
    from database import get_db_connection
    state = dict(month=stamp[:7], usage_usd=usage, limit_usd=limit,
                 exhausted=usage >= limit, checked_at=stamp)
    warnings = []
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute('''INSERT INTO scanner_settings(key,value_json,updated_at)
            VALUES('ai_budget',?,?) ON CONFLICT(key) DO UPDATE SET
            value_json=excluded.value_json,updated_at=excluded.updated_at''', (json.dumps(state), stamp))
        for fraction in (.75, .90, 1):
            if usage < limit*fraction:
                continue
            key = 'ai_budget_alert:' + stamp[:7] + ':' + str(int(fraction*100))
            cur.execute('''INSERT INTO scanner_settings(key,value_json,updated_at)
                VALUES(?,?,?) ON CONFLICT(key) DO NOTHING''', (key,json.dumps(state),stamp))
            if cur.rowcount:
                warnings.append(int(fraction*100))
        status = 'error' if usage >= limit else 'warning' if usage >= limit*.75 else 'ok'
        cur.execute('''INSERT INTO scanner_service_status(component,status,last_attempt_at,last_success_at,detail)
            VALUES('ai_budget',?,?,?,?) ON CONFLICT(component) DO UPDATE SET
            status=excluded.status,last_attempt_at=excluded.last_attempt_at,
            last_success_at=excluded.last_success_at,detail=excluded.detail''',
            (status,stamp,stamp,json.dumps(state)))
        conn.commit()
    for percent in warnings:
        logging.getLogger(__name__).warning('AI monthly budget threshold: %s%%; monitoring unaffected',percent)


def check():
    if os.getenv('AI_TRADER_CLOUD') != 'true':
        return
    try:
        limit=float(os.getenv('AI_MONTHLY_BUDGET_USD','20'))
        if not math.isfinite(limit) or not 0 < limit <= 20:
            raise ValueError()
        response=requests.get('https://openrouter.ai/api/v1/key',
            headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY']},timeout=(3,6))
        response.raise_for_status()
        usage=response.json()['data']['usage_monthly']
        if isinstance(usage,bool) or not isinstance(usage,(int,float)) or not math.isfinite(usage) or usage < 0:
            raise ValueError()
        persist(usage,limit,datetime.now(timezone.utc).isoformat())
    except Exception:
        raise BudgetUnavailable('ai_budget_verification_failed_closed') from None
    if usage >= limit:
        raise BudgetUnavailable('ai_monthly_budget_exhausted')
