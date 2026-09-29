"""Allowlisted diagnostics only. Never forward raw exceptions/URLs to Telegram."""
import re
from datetime import datetime, timezone

REASONS = {'stale_or_missing_bars', 'TimeoutError', 'ReadTimeout', 'ConnectTimeout',
           'ConnectionError', 'HTTPError', 'ValueError', 'RuntimeError',
           'OperationalError', 'invalid_json', 'budget_exhausted', 'news_quality_rejected'}
STATUSES = {'ok','error','idle','market_closed','no_new','no_signals','waiting','degraded'}


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
