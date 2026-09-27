"""Private /budget command and durable Israel-time reports; never calls an AI.

Runs only in the singleton cloud Telegram role. Telegram update acknowledgement,
command dedupe and report creation commit together. No public-chat fallback.
"""
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from admin_messages import timestamped

ISRAEL = ZoneInfo('Asia/Jerusalem')
HOURS = (8, 12, 20, 23)
POLL_KEY = 'admin_budget_poll'


def destination():
    chat = os.getenv('TELEGRAM_ADMIN_CHAT_ID', '').strip()
    public = os.getenv('TELEGRAM_CHAT_ID', '').strip()
    return chat if chat and chat != public and os.getenv('TELEGRAM_BOT_TOKEN') else None


def read_setting(conn, key, default=None):
    row = conn.execute('SELECT value_json FROM scanner_settings WHERE key=?', (key,)).fetchone()
    return json.loads(row['value_json']) if row else default


def write_setting(conn, key, value, now):
    conn.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
        (key, json.dumps(value), now.isoformat()))


def report(conn, now):
    """Use the same hourly reconciliation snapshot for all categories and totals."""
    from ai_operations import notification
    state = read_setting(conn, 'ai_cost_reconciliation')
    if not state:
        return 'AI-Trader Admin\nסיכום תקציב AI\nנתוני העלות עדיין לא זמינים. אין להסיק שההוצאה היא אפס.'
    body = notification(state)
    checked = datetime.fromisoformat(state['checked_at'].replace('Z', '+00:00'))
    age = max(0, int((now - checked).total_seconds() / 60))
    body += '\n\nנתוני עלות עודכנו: ' + checked.astimezone(ISRAEL).strftime('%d/%m/%Y %H:%M') + ' (Israel)'
    if age > 75:
        body += f'\n⚠ הנתונים אינם עדכניים (לפני {age} דקות); ההתאמה לספק מתעכבת.'
    else:
        body += '\nהנתונים מסונכרנים מול OpenRouter פעם בשעה.'
    return body


def insert_report(conn, key, now):
    conn.execute('''INSERT INTO admin_alerts(dedupe_key,message,created_at) VALUES(?,?,?)
        ON CONFLICT(dedupe_key) DO NOTHING''',
        (key, timestamped(report(conn, now), now), now.isoformat()))


def scheduled_slot(now):
    local = now.astimezone(ISRAEL)
    # At most one hour of catch-up. Never replay yesterday's four reports.
    return local.strftime('%Y-%m-%d:') + str(local.hour) if local.hour in HOURS else None


def schedule_reports(now=None):
    if not destination():
        return
    from database import get_db_connection
    now = now or datetime.now(timezone.utc)
    slot = scheduled_slot(now)
    if slot:
        with get_db_connection() as conn:
            insert_report(conn, 'budget_schedule:' + slot, now)


def is_budget_command(update, chat, username, now):
    message = update.get('message') or {}
    if str((message.get('chat') or {}).get('id')) != chat:
        return False
    if (message.get('from') or {}).get('is_bot') or not message.get('date'):
        return False
    # Do not replay old messages when command handling is first enabled.
    if not 0 <= now.timestamp() - message['date'] <= 3600:
        return False
    text = message.get('text', '').strip().lower()
    return text == '/budget' or bool(username and text == '/budget@' + username.lower())


def handle_updates(updates, chat, username, now):
    from database import get_db_connection
    with get_db_connection() as conn:
        state = read_setting(conn, POLL_KEY, {})
        offset = state.get('offset', 0)
        for update in sorted(updates, key=lambda item: item['update_id']):
            ident = update['update_id']
            if ident < offset:
                continue
            if is_budget_command(update, chat, username, now):
                insert_report(conn, 'budget_command:' + str(ident), now)
            offset = ident + 1
        write_setting(conn, POLL_KEY, dict(offset=offset, username=username,
                      failures=0, next_at=0, last_success=now.isoformat()), now)


def poll_commands(now=None):
    chat = destination()
    if not chat:
        return
    from database import get_db_connection
    from retry_policy import retry_after
    now = now or datetime.now(timezone.utc)
    with get_db_connection() as conn:
        state = read_setting(conn, POLL_KEY, {})
    if state.get('next_at', 0) > now.timestamp():
        return
    url = 'https://api.telegram.org/bot' + os.environ['TELEGRAM_BOT_TOKEN'] + '/'
    try:
        username = state.get('username')
        if not username:
            response = requests.get(url + 'getMe', timeout=(3, 6))
            response.raise_for_status()
            username = response.json()['result']['username']
        response = requests.get(url + 'getUpdates', params={
            'offset': state.get('offset', 0), 'limit': 100, 'timeout': 0,
            'allowed_updates': json.dumps(['message'])}, timeout=(3, 6))
        response.raise_for_status()
        body = response.json()
        if not body.get('ok'):
            raise ValueError('telegram_updates_rejected')
        handle_updates(body['result'], chat, username, now)
    except Exception as exc:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
        delay = retry_after(response.headers.get('Retry-After')) if response is not None else 0
        if response is not None:
            try:
                delay = max(delay, float(response.json().get('parameters', {}).get('retry_after', 0)))
            except (ValueError, TypeError, AttributeError):
                pass
        count = state.get('failures', 0) + 1
        # Slow re-probe for permissions/webhook conflicts; never remove a webhook.
        delay = max(delay, 3600 if status in {400, 401, 403, 409} else min(1800, 30 * 2 ** min(count, 6)))
        state.update(failures=count, next_at=now.timestamp() + delay,
                     error='http_' + str(status) if status else type(exc).__name__)
        with get_db_connection() as conn:
            write_setting(conn, POLL_KEY, state, now)
        # Only an allowlisted error label, never an exception URL containing token.
        import logging
        logging.getLogger(__name__).warning('Admin command polling unavailable: %s', state['error'])
