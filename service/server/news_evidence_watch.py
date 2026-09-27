"""Deterministic 72-hour observation in the existing private operations loop.

No provider/LLM calls, source fetching, trading writes or public notifications.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from database import get_db_connection


def save(c, key, value, at):
    c.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
        (key, json.dumps(value), at))


def check(now=None):
    now = now or datetime.now(timezone.utc)
    at = now.isoformat()
    with get_db_connection() as c:
        row = c.execute("SELECT value_json FROM scanner_settings WHERE key='news_evidence_observation_window'").fetchone()
        if not row:
            return
        window = json.loads(row['value_json'])
        start = window['started_at']
        latest = c.execute("SELECT updated_at FROM scanner_settings WHERE key='news_evidence_metrics'").fetchone()
        if latest and (now-datetime.fromisoformat(latest['updated_at'])).total_seconds() < 60:
            return
        observations = [dict(r) for r in c.execute('SELECT * FROM news_evidence_observations WHERE first_seen_at>=?', (start,))]
        audit = [dict(r) for r in c.execute('SELECT * FROM news_publication_audit WHERE updated_at>=?', (start,))]
        calls = [dict(r) for r in c.execute('''SELECT l.news_id,l.stage,u.actual_cost,u.latency,u.success
            FROM news_ai_call_links l JOIN ai_call_usage u ON u.call_id=l.call_id WHERE u.timestamp>=?''', (start,))]
        jobs = [dict(r) for r in c.execute('''SELECT j.status,j.created_at,j.updated_at FROM scanner_news_jobs j
            WHERE j.news_id IN (SELECT news_id FROM news_evidence_observations WHERE first_seen_at>=? AND eligible=1)''', (start,))]
        monitor = c.execute("SELECT status,last_success_at FROM scanner_service_status WHERE component='monitor'").fetchone()
        outbox = [dict(r) for r in c.execute('''SELECT status,count(*) n FROM scanner_telegram_outbox
            WHERE created_at>=? AND event_type IN ('position_news','watchlist_news','stock_news','market_news') GROUP BY status''', (start,))]
        attempts = [dict(r) for r in c.execute('''SELECT reason,status,count(*) n FROM news_evidence_attempts
            WHERE updated_at>=? GROUP BY reason,status''', (start,))]
        quality = [dict(r) for r in c.execute('SELECT reason_codes_json FROM news_quality_checks WHERE checked_at>=?',(start,))]
        sent = [dict(r) for r in c.execute('''SELECT dedupe_key FROM scanner_telegram_outbox
            WHERE created_at>=? AND status='sent' AND event_type IN ('position_news','watchlist_news')''',(start,))]
    reasons = Counter(r['reason'] for r in observations)
    publication = Counter(reason for r in audit for reason in json.loads(r['reasons_json']))
    by_item, by_stage = {}, {}
    for r in calls:
        for mapping, key in ((by_item,str(r['news_id'])), (by_stage,r['stage'])):
            v = mapping.setdefault(key, dict(calls=0,cost=0.0,missing_cost=0,seconds=0.0,failures=0))
            v['calls'] += 1
            v['cost'] += r['actual_cost'] or 0
            v['missing_cost'] += int(r['actual_cost'] is None)
            v['seconds'] += r['latency']
            v['failures'] += int(not r['success'])
    pending = [j for j in jobs if j['status'] in ('pending','processing','retry')]
    age = max([(now-datetime.fromisoformat(j['created_at'].replace('Z','+00:00'))).total_seconds() for j in pending], default=0)
    monitor_age = ((now-datetime.fromisoformat(monitor['last_success_at'].replace('Z','+00:00'))).total_seconds()
                   if monitor and monitor['last_success_at'] else None)
    metrics = dict(started_at=start,checked_at=at,eligible_versions=sum(r['eligible'] for r in observations),
        enriched_versions=reasons['enriched'],unique_news=len({r['news_id'] for r in observations}),
        reasons=dict(reasons),publication_reasons=dict(publication),fetch_attempts=attempts,
        queue=len(pending),oldest_pending_seconds=age,by_news=by_item,by_stage=by_stage,
        monitor_age_seconds=monitor_age,monitor_status=monitor['status'] if monitor else 'missing',
        delivery_status=outbox,elapsed_hours=(now-datetime.fromisoformat(start)).total_seconds()/3600,
        quality_reason_codes=dict(Counter(code for r in quality for code in json.loads(r['reason_codes_json']))),
        limitations=['No message-count target; no causal improvement inferred from a small sample.',
                     'Provider source checks are deterministic; semantic association needs review.',
                     'Outbox counts cover news overall; queued is not delivered.'])
    # Conservative operational brakes, not changes to news/trading thresholds.
    alarms = []
    seen, duplicate_deliveries = set(), 0
    for r in sent:
        parts = r['dedupe_key'].split(':')
        if len(parts) != 4 or parts[0] not in ('news','watchlist-news'):
            continue
        for ticker in parts[3].split(','):
            key = (parts[1],parts[2],ticker)
            duplicate_deliveries += int(key in seen)
            seen.add(key)
    metrics['duplicate_personal_deliveries'] = duplicate_deliveries
    if duplicate_deliveries:
        alarms.append('duplicate_personal_delivery')
    if reasons['issuer_mismatch'] or reasons['event_mismatch']:
        alarms.append('association_mismatch')
    if monitor_age is None or monitor_age > 900 or (monitor and monitor['status']=='error'):
        alarms.append('monitor_unhealthy')
    eligible_ids = {str(r['news_id']) for r in observations if r['eligible']}
    if any(v['cost'] > .05 for k,v in by_item.items() if k in eligible_ids):
        alarms.append('enriched_item_cost_over_0_05_usd')
    if age > 3600:
        alarms.append('eligible_queue_over_1_hour')
    if publication['routing_failure']:
        alarms.append('routing_failure')
    # Duplicate *suppression* is expected, not evidence of duplicate delivery.
    with get_db_connection() as c:
        save(c,'news_evidence_metrics',metrics,at)
        save(c,'news_evidence_metrics:'+start+':'+now.strftime('%Y-%m-%dT%H'),metrics,at)
        if alarms:
            save(c,'news_evidence_stop',dict(disabled=True,reasons=alarms,at=at),at)
    from ai_operations import enqueue
    if alarms:
        enqueue('news_evidence_stop:'+start, 'AI-Trader Admin\nהעשרת SEC הושבתה בלבד: '+', '.join(alarms)+
                '\nאין שינוי במסחר, במסד או בניטור הפוזיציות. נדרשת בדיקה לפני חידוש.')
    for hours in (48,72):
        if metrics['elapsed_hours'] >= hours:
            enqueue('news_evidence_report:'+start+':'+str(hours),
                    'AI-Trader Admin\nSEC Phase 1 — '+str(hours)+' שעות\n'+
                    'זכאות: '+str(metrics['eligible_versions'])+'; הועשרו: '+str(metrics['enriched_versions'])+
                    '\nתור: '+str(len(pending))+'; עלות AI מתועדת: $'+str(round(sum(v['cost'] for v in by_item.values()),6))+
                    '\nהמדדים נשמרו לבדיקה; אין הסקת שיפור או שיוך עלות חסרה אוטומטיים.')
    return metrics
