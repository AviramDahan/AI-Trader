"""Allowlisted diagnostics only. Never forward raw exceptions/URLs to Telegram."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

REASONS = {'stale_or_missing_bars', 'TimeoutError', 'ReadTimeout', 'ConnectTimeout',
           'ConnectionError', 'HTTPError', 'ValueError', 'RuntimeError',
           'OperationalError', 'invalid_json', 'budget_exhausted', 'news_quality_rejected'}
STATUSES = {'ok','error','idle','market_closed','no_new','no_signals','waiting','degraded'}


def component_failed(row, now):
    """An on-demand model call is not a periodically heartbeating worker.

    Explicit errors remain failures. Scanner/monitor worker liveness retains its
    existing age gate; no model request is generated to refresh this status.
    """
    if row['status'] == 'error':
        return True
    if row['component'] == 'ollama':
        return False
    age = ((now-datetime.fromisoformat(row['last_attempt_at'].replace('Z','+00:00'))).total_seconds()
           if row['last_attempt_at'] else 0)
    return age > {'monitor':900,'quotes':900,'backup':7500,'scan':7200,'telegram':180}.get(row['component'],86400)


def snapshot(row, now):
    row=dict(row)
    out={'status':row.get('status') if row.get('status') in STATUSES else 'unknown'}
    for field in ('last_attempt_at','last_success_at'):
        try:
            value=datetime.fromisoformat(row[field].replace('Z','+00:00'))
            if value.tzinfo is None:continue
            out[field]=value.astimezone(timezone.utc).isoformat()
            out[field+'_age_seconds']=max(0,int((now-value).total_seconds()))
        except (TypeError,KeyError,ValueError,AttributeError):pass
    detail=str(row.get('detail') or '')
    out['reason_codes']=sorted(set(re.findall(r'\b[A-Za-z_]+\b',detail)) & REASONS)
    out['stale_tickers']=sorted(set(re.findall(r'\b([A-Z][A-Z0-9.-]{0,9}):stale_or_missing_bars\b',detail)))
    return out


def incident(previous, failed, context, now):
    state=dict(previous or {'active':False,'generation':0})
    change='failure' if failed and not state['active'] else 'recovery' if not failed and state['active'] else None
    if change=='failure':
        state['generation']+=1
        state['last_failure']={'at':now.isoformat(),'context':context}
    if change=='recovery':state['recovered_at']=now.isoformat()
    state['active']=failed
    return state,change


def summary(context):
    parts=[]
    for component, data in context.items():
        parts.append(component+': '+data['status'])
        parts.append('last_success_age_seconds: '+str(data.get('last_success_at_age_seconds','unknown')))
        if data['reason_codes']:parts.append('reason: '+', '.join(data['reason_codes']))
        if data['stale_tickers']:parts.append('stale_tickers: '+', '.join(data['stale_tickers']))
    return '\n'.join(parts)


def health_message(component, change, context, state):
    """Describe a successful backup, not merely an observer becoming healthy."""
    if component == 'ollama' and change == 'recovery':
        try:
            success = datetime.fromisoformat(context[component]['last_success_at'])
            failure = datetime.fromisoformat(state['last_failure']['at'])
            recovered = datetime.fromisoformat(state['recovered_at'])
            new_success = failure <= success <= recovered
        except (KeyError, TypeError, ValueError):
            new_success = False
        if not new_success:
            previous_status = state.get('last_failure', {}).get('context', {}).get(component, {}).get('status')
            explanation = ('התראת חוסר הפעילות של AI לפי דרישה הוסרה.\n'
                           'היעדר מועמד לניתוח אינו תקלה בשירות.\n'
                           if previous_status == 'ok' else
                           'רכיב AI אינו מדווח כשל כעת; הצלחת קריאה חדשה לא אומתה.\n')
            return ('AI-Trader Admin\n' + explanation
                    + 'אין כאן הוכחה לקריאת AI חדשה; לא בוצעה קריאת בדיקה יזומה.\n'
                    + summary(context))
    if component == 'backup' and change == 'recovery':
        data = context.get('backup', {})
        try:
            success = datetime.fromisoformat(data['last_success_at'])
            failure = datetime.fromisoformat(state['last_failure']['at'])
            recovered = datetime.fromisoformat(state['recovered_at'])
            verified = (data.get('status') == 'ok' and success.tzinfo is not None
                        and failure.tzinfo is not None and recovered.tzinfo is not None
                        and failure <= success <= recovered)
        except (KeyError, TypeError, ValueError):
            verified = False
        if verified:
            stamp = success.astimezone(ZoneInfo('Asia/Jerusalem')).strftime('%d/%m/%Y %H:%M:%S')
            return ('AI-Trader Admin\n✅ הגיבוי הצליח לאחר התקלה\n'
                    'רכיב: backup\nהגיבוי המוצפן נוצר ונשמר בהצלחה ביעד הגיבוי המרוחק.\n'
                    'זמן הצלחת הגיבוי: ' + stamp + ' (שעון ישראל)\n'
                    'התקלה הסתיימה; אין צורך בפעולה כרגע.')
        return ('AI-Trader Admin\nרכיב הגיבוי חזר למצב תקין, אך הצלחת גיבוי חדש '
                'לא אומתה מאז התקלה.\n' + summary(context))
    return ('AI-Trader Admin\n' + ('תקלה ברכיב: ' if change == 'failure' else 'השירות התאושש: ')
            + component + '\n' + summary(context)
            + ('\nהתאוששות שירות אינה מפעילה מחדש מסלול חדשות שנעצר בבדיקת בטיחות.'
               if change == 'recovery' else ''))
