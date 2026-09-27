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
from admin_messages import timestamped


def number(v):
    return v if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 else None


def record(task, model, body, started, success, failure=None, retry=False, notify_failure=True):
    if os.getenv('AI_TRADER_CLOUD')!='true': return
    from database import get_db_connection
    usage=(body or {}).get('usage') or {}
    details=usage.get('completion_tokens_details') or {}
    call_id = uuid.uuid4().hex
    with get_db_connection() as conn:
        conn.execute('''INSERT INTO ai_call_usage(call_id,task,parent_task,model,input_tokens,output_tokens,
            reasoning_tokens,actual_cost,latency,timestamp,success,failure,generation_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (call_id,'retry_repair' if retry else task,task,model,
             number(usage.get('prompt_tokens')),number(usage.get('completion_tokens')),
             number(details.get('reasoning_tokens')),number(usage.get('cost')),
             time.monotonic()-started,datetime.now(timezone.utc).isoformat(),int(success),failure,
             (body or {}).get('id')))
        from news_call_context import CURRENT
        context = CURRENT.get()
        if context:
            conn.execute('''INSERT INTO news_ai_call_links(call_id,news_id,content_version,stage,
                source_excerpt_hash,source_excerpt_chars) VALUES(?,?,?,?,?,?)''',
                (call_id, context['news_id'], context['content_version'], context['stage'],
                 context['source_excerpt_hash'], context['source_excerpt_chars']))
    if not success and notify_failure and failure not in {'ValueError'}:
        stamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
        # Only allowlisted operational metadata can enter a private notification.
        from retry_policy import alert_failure_detail
        summary=alert_failure_detail(failure)
        enqueue('openrouter_failure:'+stamp+':'+task+':'+summary,
                'AI-Trader Admin\nעיבוד AI לא הושלם בקריאה הנוכחית; נדרשת בדיקת הסיבה.\n'
                'משימה: '+task+'\nסיבה: '+summary+
                '\nכשל זמני עשוי להמתין ל-backoff; אין כאן דיווח על repair שכבר הצליח.'
                '\nניטור הפוזיציות ו־TP/SL ממשיכים בנפרד.')


def credits():
    response=requests.get('https://openrouter.ai/api/v1/credits',
        headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY']},timeout=(3,6))
    response.raise_for_status()
    data=response.json()['data']
    purchased=number(data.get('total_credits'))
    used=number(data.get('total_usage'))
    if purchased is None or used is None: raise ValueError('credit_balance_unavailable')
    return dict(credit_balance=purchased-used,total_credits=purchased)


def credit_alerts(data):
    # A manual purchase starts a new credit cycle; restarts/balance jitter do not.
    for threshold in (2,1):
        if data['credit_balance'] < threshold:
            enqueue(f"credits:{data['total_credits']:.8f}:{threshold}",
                f"AI-Trader Admin\nיתרת הקרדיטים נמוכה מ-${threshold}: ${data['credit_balance']:.2f}\n"
                'זו יתרת החשבון, לא יתרת התקציב החודשי. טעינה אוטומטית כבויה.')


def calculate(rows, provider, now=None, samples=None, credit_data=None):
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
    samples=samples or []
    # Restart the observation window after a collection gap or counter reset.
    for i in range(len(samples)-1,0,-1):
        gap=(datetime.fromisoformat(samples[i]['timestamp'])-datetime.fromisoformat(samples[i-1]['timestamp'])).total_seconds()
        if gap>10800 or gap<=0 or samples[i]['usage']<samples[i-1]['usage']:
            samples=samples[i:]
            break
    span=0
    burn=None
    if len(samples)>=2 and usage is not None:
        times=[datetime.fromisoformat(s['timestamp']) for s in samples]
        span=(times[-1]-times[0]).total_seconds()/86400
        valid=all(0 < (b-a).total_seconds() <= 10800 for a,b in zip(times,times[1:]))
        valid=valid and all(b['usage']>=a['usage'] for a,b in zip(samples,samples[1:]))
        if span>=7 and valid and (now-times[-1]).total_seconds()<=10800:
            burn=(samples[-1]['usage']-samples[0]['usage'])/span
    remaining=max(0,cap-usage) if usage is not None else None
    days=remaining/burn if burn else None
    if days is not None and days>calendar.monthrange(now.year,now.month)[1]-elapsed:
        days=None  # Monthly reset occurs first; do not forecast a cap years away.
    return dict(local_total=local,total=usage,news=totals['news_analysis']+totals['news_translation'],
                final=totals['final_stock_review'],retry=totals['retry_repair'],missing_cost_calls=missing,
                remaining=remaining,used_percent=usage/cap*100 if usage is not None else None,
                average_daily_burn=burn,projected=usage+burn*(calendar.monthrange(now.year,now.month)[1]-elapsed) if burn is not None else None,
                days_until_cap=days,
                discrepancy=usage-local if usage is not None else None,
                provider_limit=provider.get('limit'),provider_limit_remaining=provider.get('limit_remaining'),
                credit_balance=(credit_data or {}).get('credit_balance'),
                measured_days=span,checked_at=now.isoformat(),
                forecast_basis='observed_provider_delta_minimum_7_days' if burn is not None else 'insufficient_data')


def enqueue(key,message):
    from database import get_db_connection
    created_at=datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute('''INSERT INTO admin_alerts(dedupe_key,message,created_at) VALUES(?,?,?)
            ON CONFLICT(dedupe_key) DO NOTHING''',(key,timestamped(message,created_at),created_at))


def notification(s):
    def f(k): return 'לא זמין' if s[k] is None else f'{s[k]:.2f}'
    return ('AI-Trader Admin\nAI budget: $'+f('total')+' / $25\nNews: $'+f('news')+
            '\nFinal stock: $'+f('final')+'\nRetries/repairs: $'+f('retry')+
            '\nMonthly budget remaining: $'+f('remaining')+
            '\nAccount credit balance: $'+f('credit_balance')+
            '\nProjected month-end: '+('$'+f('projected') if s['projected'] is not None else 'אין מספיק נתונים')+
            '\nEstimated days until cap: '+f('days_until_cap')+
            '\nפער לא משויך מול OpenRouter: $'+f('discrepancy')+
            '\nתחזית דורשת לפחות 7 ימי מדידה רציפה; אינה התחייבות. עלות repair נספרת רק בקטגוריית retries.')


def reconcile():
    from database import get_db_connection
    now=datetime.now(timezone.utc)
    response=requests.get('https://openrouter.ai/api/v1/key',
        headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY']},timeout=(3,6))
    response.raise_for_status()
    provider=response.json()['data']
    if number(provider.get('usage_monthly')) is None: raise ValueError('usage_unavailable')
    credit_data=credits()
    with get_db_connection() as conn:
        rows=conn.execute('SELECT task,actual_cost FROM ai_call_usage WHERE timestamp>=?',
                          (now.strftime('%Y-%m-01T00:00:00+00:00'),)).fetchall()
        key='ai_cost_samples:'+now.strftime('%Y-%m')
        old=conn.execute('SELECT value_json FROM scanner_settings WHERE key=?',(key,)).fetchone()
        samples=json.loads(old['value_json']) if old else []
        if not samples or (now-datetime.fromisoformat(samples[-1]['timestamp'])).total_seconds()>=3500:
            samples.append(dict(timestamp=now.isoformat(),usage=provider['usage_monthly']))
        conn.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
          ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
          (key,json.dumps(samples),now.isoformat()))
        s=calculate(rows,provider,now,samples,credit_data)
        conn.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('ai_cost_reconciliation',?,?)
          ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
          (json.dumps(s),now.isoformat()))
    month=now.strftime('%Y-%m')
    for fraction in (.75,.90,1):
        if s['total']>=25*fraction:
            enqueue('budget:'+month+':'+str(fraction),notification(s))
    credit_alerts(credit_data)
    if s['projected'] is not None and s['projected']>25:
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
          WHERE dedupe_key=(SELECT dedupe_key FROM admin_alerts WHERE status IN ('pending','sending') AND next_at<=?
          ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *''',(now+120,now)).fetchone()
    if not row:return
    try:
        r=requests.post('https://api.telegram.org/bot'+token+'/sendMessage',json={
            'chat_id':chat,'text':timestamped(row['message'],row['created_at']),'disable_web_page_preview':True},timeout=(3,10))
        r.raise_for_status()
        value=r.json()
        if not value.get('ok'):raise ValueError('telegram_rejected')
        with get_db_connection() as conn:
            conn.execute("UPDATE admin_alerts SET status='sent',message_id=? WHERE dedupe_key=?",
                         (value['result']['message_id'],row['dedupe_key']))
    except Exception as exc:
        from retry_policy import retry_after
        response=getattr(exc,'response',None)
        status=getattr(response,'status_code',None)
        delay=retry_after(response.headers.get('Retry-After')) if response is not None else 0
        try:delay=max(delay,float(response.json().get('parameters',{}).get('retry_after',0)))
        except (ValueError,TypeError,AttributeError):pass
        ambiguous=isinstance(exc,(requests.ReadTimeout,requests.ConnectionError)) and not isinstance(exc,requests.ConnectTimeout)
        terminal=row['attempts']>=6 or status in {400,401,403,404} or ambiguous
        with get_db_connection() as conn:
            conn.execute("UPDATE admin_alerts SET status=?,next_at=? WHERE dedupe_key=?",
                         ('delivery_unknown' if ambiguous else 'failed' if terminal else 'pending',
                          now+max(delay,min(3600,30*2**min(row['attempts'],6))),row['dedupe_key']))


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
        except Exception:
            try:
                enqueue('reconciliation_failure:'+datetime.now(timezone.utc).strftime('%Y-%m-%dT%H'),
                        'AI-Trader Admin\nהתאמת החיוב מול OpenRouter נכשלה. אין חישוב משוער במקום נתוני הספק.')
            except Exception:
                pass  # External watchdog handles a wholly unavailable database/server.
            import logging
            logging.getLogger(__name__).warning('Private operations check failed; no public fallback')
        # A failed provider reconciliation must not block existing admin messages.
        from budget_reports import schedule_reports, poll_commands
        for operation in (schedule_reports,poll_commands,health,send_one):
            try:
                await asyncio.to_thread(operation)
            except Exception:
                pass
        await asyncio.sleep(30)
