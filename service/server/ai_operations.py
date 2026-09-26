"""Deterministic accounting and private operations alerts. Never calls a model.

Missing provider cost stays NULL, never estimated or assigned to a category.
Admin delivery is separate from the public trading outbox, with no fallback chat.
"""
import asyncio
import calendar
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
import requests


def number(v):
    return v if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 else None


def record(task, model, body, started, success, failure=None, retry=False):
    if os.getenv('AI_TRADER_CLOUD')!='true': return
    from database import get_db_connection
    usage=(body or {}).get('usage') or {}
    details=usage.get('completion_tokens_details') or {}
    with get_db_connection() as conn:
        conn.execute('''INSERT INTO ai_call_usage(call_id,task,parent_task,model,input_tokens,output_tokens,
            reasoning_tokens,actual_cost,latency,timestamp,success,failure,generation_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (uuid.uuid4().hex,'retry_repair' if retry else task,task,model,
             number(usage.get('prompt_tokens')),number(usage.get('completion_tokens')),
             number(details.get('reasoning_tokens')),number(usage.get('cost')),
             time.monotonic()-started,datetime.now(timezone.utc).isoformat(),int(success),failure,
             (body or {}).get('id')))
    if not success and failure not in {'ValueError'}:
        stamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
        enqueue('openrouter_failure:'+stamp,'AI-Trader Admin\nקריאת OpenRouter נכשלה או שהתגובה לא עמדה בסכמה.\nניטור הפוזיציות ו־TP/SL ממשיכים בנפרד.')


def calculate(rows, provider, now=None):
    now=now or datetime.now(timezone.utc)
    totals={k:0.0 for k in ('news_analysis','news_translation','final_stock_review','retry_repair')}
    missing=0
    for row in rows:
        cost=number(row['actual_cost'])
        if cost is None: missing+=1
        else: totals[row['task']]+=cost
    local=sum(totals.values())
    usage=number(provider.get('usage_monthly'))
    cap=25.0
    elapsed=(now-now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)).total_seconds()/86400
    burn=usage/max(elapsed,1/24) if usage is not None else None
    remaining=max(0,cap-usage) if usage is not None else None
    days=remaining/burn if burn else None
    if days is not None and days>calendar.monthrange(now.year,now.month)[1]-elapsed:
        days=None  # Monthly reset occurs first; do not forecast a cap years away.
    return dict(local_total=local,total=usage,news=totals['news_analysis']+totals['news_translation'],
                final=totals['final_stock_review'],retry=totals['retry_repair'],missing_cost_calls=missing,
                remaining=remaining,used_percent=usage/cap*100 if usage is not None else None,
                average_daily_burn=burn,projected=burn*calendar.monthrange(now.year,now.month)[1] if burn is not None else None,
                days_until_cap=days,
                discrepancy=usage-local if usage is not None else None,
                provider_limit=provider.get('limit'),provider_limit_remaining=provider.get('limit_remaining'),
                checked_at=now.isoformat(),forecast_basis='calendar_month_elapsed_average_not_guarantee')


def enqueue(key,message):
    from database import get_db_connection
    with get_db_connection() as conn:
        conn.execute('''INSERT INTO admin_alerts(dedupe_key,message,created_at) VALUES(?,?,?)
            ON CONFLICT(dedupe_key) DO NOTHING''',(key,message,datetime.now(timezone.utc).isoformat()))


def notification(s):
    def f(k): return 'לא זמין' if s[k] is None else f'{s[k]:.2f}'
    return ('AI-Trader Admin\nAI budget: $'+f('total')+' / $25\nNews: $'+f('news')+
            '\nFinal stock: $'+f('final')+'\nRetries/repairs: $'+f('retry')+
            '\nRemaining: $'+f('remaining')+'\nProjected month-end: $'+f('projected')+
            '\nEstimated days until cap: '+f('days_until_cap')+
            '\nפער לא משויך מול OpenRouter: $'+f('discrepancy')+
            '\nהתחזית מחושבת לפי ממוצע מתחילת החודש, ואינה התחייבות.')


def reconcile():
    from database import get_db_connection
    now=datetime.now(timezone.utc)
    response=requests.get('https://openrouter.ai/api/v1/key',
        headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY']},timeout=(3,6))
    response.raise_for_status()
    provider=response.json()['data']
    if number(provider.get('usage_monthly')) is None: raise ValueError('usage_unavailable')
    with get_db_connection() as conn:
        rows=conn.execute('SELECT task,actual_cost FROM ai_call_usage WHERE timestamp>=?',
                          (now.strftime('%Y-%m-01T00:00:00+00:00'),)).fetchall()
        s=calculate(rows,provider,now)
        conn.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('ai_cost_reconciliation',?,?)
          ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
          (json.dumps(s),now.isoformat()))
    month=now.strftime('%Y-%m')
    for fraction in (.75,.90,1):
        if s['total']>=25*fraction:
            enqueue('budget:'+month+':'+str(fraction),notification(s))
    if s['projected']>25:
        enqueue('projected:'+month,notification(s))
    if abs(s['discrepancy'])>.01:
        enqueue('discrepancy:'+month,notification(s))
    return s


def send_one():
    from database import get_db_connection
    chat=os.getenv('TELEGRAM_ADMIN_CHAT_ID','').strip()
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    # Never redirect private alerts to public Telegram configuration.
    if not chat or not token or chat==os.getenv('TELEGRAM_CHAT_ID'): return
    now=time.time()
    with get_db_connection() as conn:
        row=conn.execute('''UPDATE admin_alerts SET status='sending', attempts=attempts+1,next_at=?
          WHERE dedupe_key=(SELECT dedupe_key FROM admin_alerts WHERE status!='sent' AND next_at<=?
          ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *''',(now+120,now)).fetchone()
    if not row:return
    try:
        r=requests.post('https://api.telegram.org/bot'+token+'/sendMessage',json={
            'chat_id':chat,'text':row['message'],'disable_web_page_preview':True},timeout=(3,10))
        r.raise_for_status()
        value=r.json()
        if not value.get('ok'):raise ValueError('telegram_rejected')
        with get_db_connection() as conn:
            conn.execute("UPDATE admin_alerts SET status='sent',message_id=? WHERE dedupe_key=?",
                         (value['result']['message_id'],row['dedupe_key']))
    except Exception:
        with get_db_connection() as conn:
            conn.execute("UPDATE admin_alerts SET status='pending',next_at=? WHERE dedupe_key=?",
                         (now+min(3600,30*2**min(row['attempts'],6)),row['dedupe_key']))


def health():
    from database import get_db_connection
    now=datetime.now(timezone.utc)
    with get_db_connection() as conn:
        states=conn.execute('SELECT component,status,last_attempt_at FROM scanner_service_status').fetchall()
    for r in states:
        age=(now-datetime.fromisoformat(r['last_attempt_at'].replace('Z','+00:00'))).total_seconds() if r['last_attempt_at'] else 0
        stale=age>({'monitor':900,'quotes':900,'backup':7500,'scan':7200,'telegram':180}.get(r['component'],86400))
        failed=r['status']=='error' or stale
        key='admin_incident:'+r['component']
        with get_db_connection() as conn:
            old=conn.execute('SELECT value_json FROM scanner_settings WHERE key=?',(key,)).fetchone()
            state=json.loads(old['value_json']) if old else {'active':False,'generation':0}
            newly=failed and not state['active']
            if newly:state['generation']+=1
            state['active']=failed
            conn.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
              ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
              (key,json.dumps(state),now.isoformat()))
        if newly:
            enqueue('health:'+r['component']+':'+str(state['generation']),
                    'AI-Trader Admin\nתקלה ברכיב: '+r['component']+'\nנדרשת בדיקת מצב השירות.')


async def operations_loop():
    while True:
        try:
            from database import get_db_connection
            with get_db_connection() as conn:
                row=conn.execute("SELECT updated_at FROM scanner_settings WHERE key='ai_cost_reconciliation'").fetchone()
            if not row or time.time()-datetime.fromisoformat(row['updated_at']).timestamp()>=3600:
                await asyncio.to_thread(reconcile)
            await asyncio.to_thread(health)
            await asyncio.to_thread(send_one)
        except Exception:
            # Operations failures cannot stop Telegram lifecycle or price monitoring.
            import logging
            logging.getLogger(__name__).warning('Private operations check failed; no public fallback')
        await asyncio.sleep(30)
