"""Deterministic operational brakes/private reporting, not an AI evaluator."""
import json
from datetime import datetime,timezone,timedelta
from .control import state
from .runtime import connect
from .model import timestamp
from .queue_health import queue_rows, summarize


def coverage_summary(providers, provider_health):
    """Pipeline integrity and provider availability are separate health signals."""
    healthy = {'ok', 'no_new', 'not_modified'}
    inactive = {'disabled', 'retired'}
    states = {r['provider']: r['status'] for r in providers}
    states.update({k: v.get('status', 'unknown') for k, v in provider_health.items()
                   if not k.startswith('evidence:')})
    affected = sorted(k for k, status in states.items() if status not in healthy | inactive)
    if affected:
        return 'חדשות קנוניות: הצינור תקין; כיסוי מקורות חלקי\nמקורות דורשים טיפול: ' + ', '.join(affected)
    return 'חדשות קנוניות: הצינור תקין; המקורות הפעילים תקינים'


def fail_back(reason,current):
    """Fence first, then let the singleton scanner resume Phase 1 next cycle.

    The analysis lock is shared by both modes. In-flight canonical analysis can
    finish saving evidence but cannot enqueue after this transaction commits.
    No trading, old DB restore, checkpoint reset or local restart occurs.
    """
    with connect() as c:
        c.execute('SELECT id FROM ne_control WHERE id=1 FOR UPDATE')
        c.execute("""UPDATE ne_control SET mode='phase1',epoch=epoch+1,not_before=?,changed_at=?,reason=?
            WHERE id=1 AND mode='canonical'""",(timestamp(current),timestamp(current),reason))
        c.execute("""UPDATE scanner_telegram_outbox SET status='cancelled',last_error='canonical_safety_rollback'
            WHERE dedupe_key LIKE 'canonical:%' AND status IN ('pending','retry')""")
    from ai_operations import enqueue
    enqueue('canonical_rollback:'+timestamp(current),
        'AI-Trader Admin\nמסלול החדשות חזר ל־Phase 1 בעקבות בדיקת בטיחות: '+reason+
        '\nאין שחזור מסד או שינוי במסחר. נדרשת בדיקה לפני חידוש Phase 2.')


def check(at=None):
    current=at or datetime.now(timezone.utc)
    control=state()
    if control['mode']!='canonical':return
    from .store import Store
    from .reporting import health_report
    data=health_report(Store(connect,production=True),current)
    with connect() as c:
        monitor=c.execute("SELECT status,last_success_at,last_attempt_at,detail FROM scanner_service_status WHERE component='monitor'").fetchone()
        prices=c.execute("SELECT status,last_success_at,last_attempt_at,detail FROM scanner_service_status WHERE component='prices'").fetchone()
        calls=[dict(r) for r in c.execute('''SELECT l.event_id,coalesce(sum(u.actual_cost),0) actual_cost FROM ne_ai_call_links l
            JOIN ai_call_usage u ON u.call_id=l.call_id WHERE u.timestamp>=? GROUP BY l.event_id''',(timestamp(current-timedelta(hours=1)),))]
        bad_route=c.execute('''SELECT 1 FROM ne_outbox n JOIN scanner_telegram_outbox o ON o.dedupe_key=n.dedupe_key
            WHERE (n.topic='market_news' AND o.event_type!='market_news') OR
                  (n.topic='portfolio_watchlist' AND o.event_type!='position_news') OR
                  (n.topic='important_stock_news' AND o.event_type!='stock_news') LIMIT 1''').fetchone()
        bad_link=c.execute('''SELECT 1 FROM ne_outbox o LEFT JOIN ne_analysis a
            ON a.event_id=o.event_id AND a.version=o.version WHERE a.status IS NULL OR a.status!='done' LIMIT 1''').fetchone()
        providers=[dict(r) for r in c.execute('SELECT provider,status,last_success_at,next_check_at,error FROM scanner_news_providers')]
        due=queue_rows(c)
    data.update(summarize(due,current))
    costs={}
    for r in calls:costs[r['event_id']]=costs.get(r['event_id'],0)+(r['actual_cost'] or 0)
    alarms=[]
    if bad_route:alarms.append('topic_integrity')
    if bad_link:alarms.append('outbox_analysis_integrity')
    # Operational stop limits are independent of news quality/trading thresholds.
    if any(value>.05 for value in costs.values()):alarms.append('event_cost_over_0_05_usd')
    if sum(costs.values())>.25:alarms.append('hourly_news_cost_over_0_25_usd')
    if data['queue_size']>300 or data['oldest_queue_seconds']>3600:alarms.append('queue_growth')
    if monitor and monitor['last_success_at']:
        age=(current-datetime.fromisoformat(timestamp(monitor['last_success_at']))).total_seconds()
        if age>900 or monitor['status']=='error':alarms.append('monitor_degraded')
    data['checked_at']=timestamp(current);data['alarms']=alarms;data['existing_provider_health']=providers
    from admin_health_context import snapshot
    data['monitor_context']={name:snapshot(row,current) for name,row in (('monitor',monitor),('prices',prices)) if row}
    with connect() as c:
        c.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('news_canonical_health',?,?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
            (json.dumps(data),timestamp(current)))
    from ai_operations import enqueue
    if alarms:
        fail_back(','.join(alarms),current)
    else:
        enqueue('canonical_health:'+current.strftime('%Y-%m-%dT%H'),
            'AI-Trader Admin\n'+coverage_summary(providers,data['provider_health'])+'\nאירועים: '+str(data['canonical_events'])+
            '; גרסאות מקורות: '+str(data['source_versions'])+'; תור: '+str(data['queue_size'])+
            '\nעלות חדשות מתועדת מאז ההפעלה: $'+str(round(data['known_cost'],6))+
            '\nספקים: '+', '.join(r['provider']+'='+r['status'] for r in providers)+
            '\nספקים חדשים: '+', '.join(k+'='+v.get('status','unknown') for k,v in data['provider_health'].items() if not k.startswith('evidence:')))
    return data
