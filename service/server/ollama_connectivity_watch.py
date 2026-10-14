"""Durable private connectivity episodes. GET health only, never inference.

Runs in the existing cloud Telegram operations loop. A powered-off PC cannot
notify anyone; the cloud therefore owns this observer and the private outbox.
Reachable-but-busy/cold is not diagnosed as a lost connection.
"""
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

KEY = 'ollama_connectivity_watch_v1'
POLL_SECONDS = 60
FAILURE_SECONDS = 120
RECOVERY_SECONDS = 60
MAX_GAP_SECONDS = 180
REASONS = {'private_relay_unreachable', 'invalid_health_response', 'model_identity_mismatch'}


def _instant(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('connectivity_timestamp_requires_timezone')
    return result.astimezone(timezone.utc)


def _due(previous, now):
    last = _instant(previous.get('last_check_at'))
    return last is None or (now-last).total_seconds() < 0 or (now-last).total_seconds() >= POLL_SECONDS


def probe():
    """Does not call ready()/failed(), alter routing cooldown, or POST a model."""
    import ai_routing as routing
    try:
        value = routing.relay('GET', '/health', timeout=2)
    except requests.RequestException:
        return {'status': 'failed', 'reason': 'private_relay_unreachable'}
    except ValueError:
        return {'status': 'failed', 'reason': 'invalid_health_response'}
    if (not isinstance(value, dict) or type(value.get('protocol')) is not int or
            type(value.get('ready')) is not bool or type(value.get('capacity')) is not int):
        return {'status': 'failed', 'reason': 'invalid_health_response'}
    if (value['protocol'] != routing.PROTOCOL or value.get('model') != routing.MODEL or
            value.get('digest') != routing.DIGEST or value['capacity'] != 1):
        return {'status': 'failed', 'reason': 'model_identity_mismatch'}
    return {'status': 'ready' if value['ready'] else 'reachable_not_ready', 'reason': None}


def advance(previous, observation, now, enabled=True):
    """Pure UTC state machine; failure and recovery each have a persisted debounce."""
    state = dict(previous or {'active': False, 'generation': 0})
    state['enabled'] = enabled
    if not enabled:
        # A deliberate cloud-only mode is not a verified local recovery.
        state.update(failed_checks=0, failed_since=None, ready_checks=0, ready_since=None)
        return state, None
    status = observation['status']
    if status not in {'failed', 'ready', 'reachable_not_ready'} or (
            status == 'failed' and observation.get('reason') not in REASONS):
        raise ValueError('invalid_connectivity_observation')
    last = _instant(state.get('last_check_at'))
    gap = (now-last).total_seconds() if last else None
    if not previous or not previous.get('enabled', True) or gap is None or gap < 0 or gap > MAX_GAP_SECONDS:
        state.update(failed_checks=0, failed_since=None, ready_checks=0, ready_since=None)
    state.update(last_check_at=now.isoformat(), status=status, reason=observation.get('reason'))
    change = None
    if status == 'failed':
        state.update(ready_checks=0, ready_since=None)
        state['failed_checks'] = state.get('failed_checks', 0) + 1
        state['failed_since'] = state.get('failed_since') or now.isoformat()
        if (not state['active'] and state['failed_checks'] >= 3 and
                (now-_instant(state['failed_since'])).total_seconds() >= FAILURE_SECONDS):
            state.update(active=True, generation=state['generation']+1,
                         outage_started_at=state['failed_since'], failure_reason=observation['reason'])
            change = 'failure'
    elif status == 'ready':
        state.update(failed_checks=0, failed_since=None)
        state['ready_checks'] = state.get('ready_checks', 0) + 1
        state['ready_since'] = state.get('ready_since') or now.isoformat()
        if (state['active'] and state['ready_checks'] >= 2 and
                (now-_instant(state['ready_since'])).total_seconds() >= RECOVERY_SECONDS):
            state.update(active=False, recovered_at=now.isoformat())
            change = 'recovery'
    else:
        # An occupied GPU or preload must not become a false disconnection or
        # a premature recovery; wait for two actual ready observations.
        state.update(failed_checks=0, failed_since=None, ready_checks=0, ready_since=None)
    return state, change


def message(change, state):
    if change == 'recovery':
        return ('AI-Trader Admin\n✅ החיבור הפרטי ל־Ollama התאושש\n'
                'השער זמין והמודל המאושר מוכן בשתי בדיקות בריאות רצופות.\n'
                'בקשות חדשות יכולות להשתמש ב־AI המקומי כאשר הקיבולת מאפשרת זאת.\n'
                'זו בדיקת חיבור ומוכנות, לא הוכחה להצלחת ניתוח AI חדש.')
    explanations = {
        'private_relay_unreachable': 'אין חיבור תקין לשער הפרטי במחשב.',
        'invalid_health_response': 'השער הפרטי לא החזיר תשובת בריאות תקינה.',
        'model_identity_mismatch': 'המודל או חוזה החיבור אינם תואמים לגרסה המאושרת.',
    }
    since = _instant(state['outage_started_at']).astimezone(ZoneInfo('Asia/Jerusalem')).strftime('%d/%m/%Y %H:%M')
    return ('AI-Trader Admin\n⚠️ מסלול ה־AI המקומי אינו זמין\n'
            + explanations[state['failure_reason']] + '\nנצפה ברציפות מאז: ' + since + ' (שעון ישראל)\n'
            'ייתכן שהמחשב כובה או שהשער/החיבור נעצרו; סיבת המחשב לא אומתה.\n'
            'OpenRouter ישמש כגיבוי רק כאשר הקרדיטים, התקציב והבקרות הקיימות מאפשרים זאת.\n'
            'ניטור הפוזיציות ו־TP/SL בענן אינם תלויים בחיבור הזה.\n'
            'בדקו שהמחשב, Ollama והשער הפרטי פעילים. תישלח הודעת התאוששות לאחר אימות.')


def check(now=None):
    """One bounded network probe outside a transaction, then atomic state/outbox."""
    if os.getenv('AI_TRADER_CLOUD') != 'true' or os.getenv('AI_TRADER_ROLE') != 'telegram':
        return None
    import ai_routing
    from database import get_db_connection, using_postgres
    from admin_messages import timestamped
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('connectivity_timestamp_requires_timezone')
    now = now.astimezone(timezone.utc)
    enabled = ai_routing.enabled()
    with get_db_connection() as conn:
        row = conn.execute('SELECT value_json FROM scanner_settings WHERE key=?', (KEY,)).fetchone()
        previous = json.loads(row['value_json']) if row else {}
    if not enabled and (not previous or previous.get('enabled') is False):
        return previous
    if enabled and not _due(previous, now):
        return previous
    observation = probe() if enabled else None
    # No network, model or Telegram transport occurs inside this transaction.
    with get_db_connection() as conn:
        if not using_postgres():
            conn.execute('BEGIN IMMEDIATE')
        conn.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO NOTHING''', (KEY, '{}', now.isoformat()))
        row = conn.execute('SELECT value_json FROM scanner_settings WHERE key=?' +
                           (' FOR UPDATE' if using_postgres() else ''), (KEY,)).fetchone()
        previous = json.loads(row['value_json'])
        # A concurrent observer may have completed while this one probed.
        if enabled and not _due(previous, now):
            return previous
        state, change = advance(previous, observation, now, enabled)
        conn.execute('UPDATE scanner_settings SET value_json=?,updated_at=? WHERE key=?',
                     (json.dumps(state), now.isoformat(), KEY))
        if change:
            key = 'ollama-connectivity:'+str(state['generation'])+':'+change
            conn.execute('''INSERT INTO admin_alerts(dedupe_key,message,created_at) VALUES(?,?,?)
                ON CONFLICT(dedupe_key) DO NOTHING''',
                         (key, timestamped(message(change, state), now), now.isoformat()))
    return state
