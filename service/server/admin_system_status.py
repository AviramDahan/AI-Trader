"""Bounded operational projection of retained evidence. No probe or write paths.

Process ownership, completed work, queue state and on-demand readiness are
different observations. This is not Docker/OOM inspection, live trading E2E,
accounting reconciliation, model quality or a successful Telegram readback.
"""
import json
import math
import os
import threading
import time
from datetime import datetime, timezone

from database import get_db_connection, using_postgres
from admin_health_context import snapshot as service_context

_cache_lock = threading.Lock()
_cached = None
_cached_at = 0
SERVICE_LIMITS = {'scan': 7200, 'monitor': 900, 'quotes': 900, 'telegram': 180,
                  'backup': 7500, 'news_feed': 900, 'news_ai': 900, 'sec_intelligence': 900}
SAFE_STATUSES = {'ok', 'no_new', 'not_modified', 'idle', 'waiting', 'market_closed',
                 'error', 'degraded', 'disabled', 'retired', 'requires_configuration', 'backoff', 'rate_limited'}
PROVIDERS = {'ftc', 'doj', 'existing_market', 'yahoo_priority', 'ecb', 'global_voices',
             'eia', 'federal_reserve', 'telegram_channels', 'fda', 'bls', 'sec_edgar',
             'intel_ir', 'benzinga', 'investing', 'prnewswire', 'globenewswire', 'tipranks'}
PROVIDER_ERRORS = {'http_error', 'transport_failure', 'transport_TimeoutError',
                   'source_metadata_invalid', 'press_feed_activation_required', 'license_required'}


def instant(value):
    try:
        if not isinstance(value, str) or len(value) > 40:
            return None
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except ValueError:
        return None


def age(value, now):
    stamp = instant(value)
    elapsed = (now-stamp).total_seconds() if stamp else None
    return max(0, round(elapsed)) if elapsed is not None and elapsed >= -5 else None


def count(value):
    return int(value) if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**9 else None


def document(row):
    try:
        raw = row['value_json']
        if len(raw.encode()) > 65536:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, KeyError):
        return {}


def component(key, rows, now, *, lease=None):
    row = rows.get(key)
    node = {'id': key, 'state': 'unknown', 'reason': 'no_observation', 'observed_at': None,
            'last_success_at': None, 'age_seconds': None, 'lease_holders': lease, 'metrics': {}}
    if row:
        context = service_context(row, now)
        elapsed = age(row['last_attempt_at'], now)
        node.update(observed_at=instant(row['last_attempt_at']).isoformat() if instant(row['last_attempt_at']) else None,
                    last_success_at=context.get('last_success_at'), age_seconds=elapsed,
                    reason_codes=context.get('reason_codes', []))
        status = row['status']
        if status == 'error':
            node.update(state='failed', reason='reported_error')
        elif elapsed is None:
            node['reason'] = 'invalid_or_missing_timestamp'
        elif elapsed > SERVICE_LIMITS[key]:
            node.update(state='stale', reason='observation_stale')
        elif status == 'degraded':
            node.update(state='degraded', reason='reported_degraded')
        elif status in {'idle', 'waiting', 'market_closed', 'no_new', 'not_modified', 'no_signals'}:
            node.update(state='idle', reason=status)
        elif status == 'backoff':
            node.update(state='degraded', reason='retry_backoff')
        elif status in {'disabled', 'retired'}:
            node.update(state='disabled', reason='component_disabled')
        elif status == 'ok':
            node.update(state='healthy', reason='recent_completed_check')
    if lease is not None and lease != 1:
        node.update(state='failed', reason='lease_missing' if lease == 0 else 'duplicate_role_lease')
    return node


def scan_activity(node, runtime, now):
    """Same overdue grace as the existing public_status; does not run a scan."""
    if node['state'] == 'failed':
        return
    due, started = runtime.get('next_scan_at'), runtime.get('last_started_at')
    valid = lambda v: type(v) in (float, int) and math.isfinite(v) and 0 < v < 10**11
    if valid(due) and now.timestamp() > due + 300:
        node.update(state='stale', reason='scan_schedule_overdue')
    elif runtime.get('status') == 'scanning' and valid(started) and -5 <= now.timestamp()-started <= 7200:
        node.update(state='idle', reason='scan_in_progress',
                    observed_at=datetime.fromtimestamp(started, timezone.utc).isoformat(),
                    age_seconds=max(0, round(now.timestamp()-started)))


def canonical_providers(conn):
    """Filter before LIMIT: the table also contains thousands of evidence leases.

    The collector's actual fields are last_success/last_attempt, not *_at.
    Project allowlisted scalars in PostgreSQL, not large/free-form state bodies.
    """
    names = sorted(PROVIDERS)
    return conn.execute('''SELECT provider_id,state_json::jsonb->>'status' status,
        COALESCE(state_json::jsonb->>'last_success',state_json::jsonb->>'last_success_at') last_success_at,
        state_json::jsonb->>'last_attempt' last_attempt_at,
        state_json::jsonb->>'next_at' next_check_at,
        state_json::jsonb->>'error' error_code,
        state_json::jsonb->>'http_status' http_status
        FROM ne_provider_state WHERE provider_id IN (''' + ','.join('?' for _ in names) +
        ') ORDER BY provider_id LIMIT 64', tuple(names)).fetchall()


def provider_view(row):
    http = str(row.get('http_status') or '')
    return {'id':row['provider_id'],
            'status':row['status'] if row['status'] in SAFE_STATUSES else 'unknown',
            'last_success_at':instant(row['last_success_at']).isoformat() if instant(row['last_success_at']) else None,
            'last_attempt_at':instant(row.get('last_attempt_at')).isoformat() if instant(row.get('last_attempt_at')) else None,
            'next_check_at':instant(row.get('next_check_at')).isoformat() if instant(row.get('next_check_at')) else None,
            'error_code':row.get('error_code') if row.get('error_code') in PROVIDER_ERRORS else None,
            'http_status':int(http) if http.isdigit() and 100<=int(http)<=599 else None}


def build(conn, now):
    """One already read-only/repeatable snapshot. No init, reports, network or AI."""
    from scanner_engine import market_session_state, _regular_session_bar_stale
    states = {r['component']: dict(r) for r in conn.execute(
        'SELECT component,status,last_attempt_at,last_success_at,detail FROM scanner_service_status LIMIT 32')}
    settings = {r['key']: document(r) for r in conn.execute(
        '''SELECT key,value_json FROM scanner_settings WHERE key IN
        ('ollama_connectivity_watch_v1','ai_cost_reconciliation','scanner_runtime')''')}
    # Production health includes cumulative breakdowns that can exceed 1 MiB.
    # Project ONLY four scalar/allowlisted fields inside PG, never load the report.
    if using_postgres():
        canonical_row = conn.execute('''SELECT jsonb_build_object(
            'checked_at',value_json::jsonb->'checked_at',
            'queue_size',value_json::jsonb->'queue_size',
            'oldest_queue_seconds',value_json::jsonb->'oldest_queue_seconds',
            'alarms',value_json::jsonb->'alarms')::text AS value_json
            FROM scanner_settings WHERE key='news_canonical_health' ''').fetchone()
    else:
        canonical_row = conn.execute("SELECT value_json FROM scanner_settings WHERE key='news_canonical_health'").fetchone()
    settings['news_canonical_health'] = document(canonical_row) if canonical_row else {}
    leases = None
    if using_postgres():
        leases = {int(r['role_key']): int(r['holders']) for r in conn.execute('''
            SELECT objid AS role_key,COUNT(*) holders FROM pg_locks
            WHERE locktype='advisory' AND granted AND classid=719322 AND objsubid=2
            AND objid IN (11,12,13) AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
            GROUP BY objid''')}
    get_lease = lambda key: leases.get(key, 0) if leases is not None else None
    market = market_session_state(now)
    nodes = [component(key, states, now, lease=get_lease(role) if role else None) for key, role in (
        ('news_feed', 11), ('sec_intelligence', 11), ('scan', 11), ('quotes', 12),
        ('news_ai', 11), ('monitor', 12), ('telegram', 13), ('backup', None))]
    by_id = {n['id']: n for n in nodes}
    providers = []
    for row in conn.execute('SELECT provider,status,last_success_at,next_check_at FROM scanner_news_providers LIMIT 64'):
        if row['provider'] in PROVIDERS:
            providers.append({'id': row['provider'], 'status': row['status'] if row['status'] in SAFE_STATUSES else 'unknown',
                              'last_success_at': instant(row['last_success_at']).isoformat() if instant(row['last_success_at']) else None})
    if using_postgres():
        control = conn.execute('SELECT mode FROM ne_control WHERE id=1').fetchone()
        if control and control['mode'] == 'canonical':
            merged = {p['id']:p for p in providers}
            for row in canonical_providers(conn):
                merged[row['provider_id']] = provider_view(dict(row))
            providers = list(merged.values())
    canonical = settings.get('news_canonical_health', {})
    canonical_age = age(canonical.get('checked_at'), now)
    canonical_recent = canonical_age is not None and canonical_age <= 180
    by_id['news_feed']['metrics'] = {
        'queue': count(canonical.get('queue_size')) if canonical_recent else None,
        'oldest_queue_seconds': count(canonical.get('oldest_queue_seconds')) if canonical_recent else None,
        'provider_issues': sum(p['status'] not in {'ok','no_new','not_modified','disabled','retired'} for p in providers)}
    by_id['news_feed']['providers'] = providers
    if by_id['news_feed']['state'] != 'failed' and canonical_recent and canonical.get('alarms'):
        by_id['news_feed'].update(state='degraded', reason='canonical_alarm')
    elif by_id['news_feed']['state'] in {'healthy','idle'} and by_id['news_feed']['metrics']['provider_issues']:
        by_id['news_feed'].update(state='degraded', reason='partial_provider_coverage')
    sec = conn.execute('''SELECT COUNT(*) issuers,
        SUM(CASE WHEN last_checked_at IS NOT NULL AND catchup_active=0 THEN 1 ELSE 0 END) completed,
        SUM(CASE WHEN error_code IS NOT NULL THEN 1 ELSE 0 END) errors FROM si_checkpoints''').fetchone()
    by_id['sec_intelligence']['metrics'] = {k: count(sec[k]) for k in ('issuers','completed','errors')}
    runtime = settings.get('scanner_runtime', {})
    scan_activity(by_id['scan'], runtime, now)
    for field in ('next_scan_at', 'last_completed_at'):
        stamp = runtime.get(field)
        if type(stamp) in (int, float) and math.isfinite(stamp) and 0 < stamp < 10**11:
            by_id['scan']['metrics'][field] = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    for field in ('universe_count','technical_candidates_count','ai_selected_count','signals_published'):
        by_id['scan']['metrics'][field] = count(runtime.get(field))
    # Orders have no ticker column. An unqualified subquery ticker would bind
    # to the outer cursor and include every historical cursor when any order
    # is pending. Start with the active linked cohort; keep missing cursors
    # visible rather than silently certifying an unobserved active symbol.
    cursor_rows = conn.execute('''SELECT active.ticker,cursor.last_bar_at FROM (
        SELECT ticker FROM scanner_trades WHERE status='open'
        UNION SELECT signal.ticker FROM scanner_orders orders
            JOIN scanner_signals signal ON signal.id=orders.signal_id
            WHERE orders.status IN ('pending','recovery_uncertain')) active
        LEFT JOIN scanner_price_cursors cursor ON cursor.ticker=active.ticker
        ORDER BY active.ticker LIMIT 32''').fetchall()
    marks = []
    for row in cursor_rows:
        stamp = instant(row['last_bar_at'])
        valid = stamp is not None and age(row['last_bar_at'], now) is not None and (now-stamp).total_seconds() >= 300
        recent = valid and market['is_open'] and not _regular_session_bar_stale(stamp, now)
        marks.append({'ticker': row['ticker'] if isinstance(row['ticker'], str) and len(row['ticker']) <= 10 else '?',
                      'bar_started_at': stamp.isoformat() if valid else None,
                      'fresh_regular_session': bool(recent) if market['is_open'] else None})
    by_id['monitor']['bars'] = marks
    by_id['monitor']['metrics'] = {'sampled_cursors': len(marks), 'regular_session_open': market['is_open']}
    if (by_id['monitor']['state'] != 'failed' and market['is_open'] and marks
            and any(m['fresh_regular_session'] is False for m in marks)):
        by_id['monitor'].update(state='degraded', reason='completed_bars_not_fresh')
    orders = conn.execute('''SELECT COUNT(*) pending,
        SUM(CASE WHEN status='recovery_uncertain' THEN 1 ELSE 0 END) holds
        FROM scanner_orders WHERE status IN ('pending','recovery_uncertain')''').fetchone()
    trades = conn.execute("SELECT COUNT(*) n FROM scanner_trades WHERE status='open' AND is_shadow=0").fetchone()['n']
    nodes.append({'id':'paper', 'state':'degraded' if orders['holds'] else 'idle',
                  'reason':'recovery_review_required' if orders['holds'] else 'retained_paper_state',
                  'observed_at':now.isoformat(), 'metrics':{'open_positions':count(trades),
                    'pending_orders':count(orders['pending'] - (orders['holds'] or 0)), 'holds':count(orders['holds'] or 0)}})
    local = settings.get('ollama_connectivity_watch_v1', {})
    local_age = age(local.get('last_check_at'), now)
    local_state, local_reason = 'unknown', 'no_observation'
    if local.get('enabled') is False:
        local_state, local_reason = 'disabled', 'local_route_disabled'
    elif local_age is not None and local_age <= 180:
        local_state, local_reason = {'ready':('healthy','model_ready_not_inference_proof'),
            'failed':('failed','private_relay_unavailable'),
            'reachable_not_ready':('idle','gpu_busy_or_loading')}.get(local.get('status'), ('unknown','invalid_observation'))
        if local.get('active') and local.get('status') == 'ready':
            local_state, local_reason = 'degraded', 'recovery_verification_pending'
    elif local_age is not None:
        local_state, local_reason = 'stale', 'observation_stale'
    nodes.append({'id':'ai_local', 'state':local_state, 'reason':local_reason,
                  'observed_at':instant(local.get('last_check_at')).isoformat() if instant(local.get('last_check_at')) else None,
                  'age_seconds':local_age, 'metrics':{}})
    budget = settings.get('ai_cost_reconciliation', {})
    budget_age = age(budget.get('checked_at'), now)
    remaining, balance = budget.get('remaining'), budget.get('credit_balance')
    numbers_valid = all(type(v) in (float,int) and math.isfinite(v) and v >= 0 for v in (remaining, balance))
    current_budget = budget_age is not None and budget_age <= 7500 and numbers_valid
    available = current_budget and remaining > 0 and balance > 0
    nodes.append({'id':'ai_cloud', 'state':'idle' if available else 'degraded' if current_budget else 'unknown',
                  'reason':'paid_fallback_budget_available_not_connection_proof' if available else
                    'paid_fallback_budget_or_credits_blocked' if current_budget else 'budget_observation_unavailable',
                  'observed_at':instant(budget.get('checked_at')).isoformat() if instant(budget.get('checked_at')) else None,
                  'age_seconds':budget_age, 'metrics':{'budget_available':bool(available) if current_budget else None}})
    for table, key in (('scanner_telegram_outbox','public_delivery'), ('admin_alerts','admin_delivery')):
        result = conn.execute(f'''SELECT COUNT(*) queued,MIN(created_at) oldest FROM {table}
            WHERE status IN ('pending','retry','sending')''').fetchone()
        by_id['telegram']['metrics'][key+'_queued'] = count(result['queued'])
        by_id['telegram']['metrics'][key+'_oldest_seconds'] = age(result['oldest'], now) if result['queued'] else 0
        oldest = by_id['telegram']['metrics'][key+'_oldest_seconds']
        if by_id['telegram']['state'] != 'failed' and result['queued'] and oldest is not None and oldest > 300:
            by_id['telegram'].update(state='degraded', reason='delivery_backlog')
    version = conn.execute('SELECT MAX(version) version FROM schema_migrations').fetchone()['version'] if using_postgres() else None
    nodes.extend([{'id':'database','state':'healthy','reason':'read_only_snapshot_succeeded',
                   'observed_at':now.isoformat(),'metrics':{'schema':version}},
                  {'id':'api','state':'healthy','reason':'authenticated_api_response',
                   'observed_at':now.isoformat(),'metrics':{}}])
    critical = any(n['state'] == 'failed' for n in nodes)
    incomplete = any(n['state'] in {'unknown','stale','degraded'} for n in nodes)
    sha = os.getenv('BUILD_SHA', '')
    return {'version':1, 'observed_at':now.isoformat(), 'refresh_seconds':15,
            'build_sha':sha if len(sha)==40 and all(c in '0123456789abcdef' for c in sha) else None,
            'overall':'failed' if critical else 'attention' if incomplete else 'observed_operational',
            'market':market, 'nodes':nodes, 'read_only':True,
            'limits':['retained_observations_not_docker_health_or_oom','no_natural_trading_e2e_claim',
                      'on_demand_ai_not_continuous_work','outbox_not_telegram_readback']}


def payload():
    global _cached, _cached_at
    with _cache_lock:
        if _cached is not None and time.monotonic()-_cached_at < 5:
            return _cached
        with get_db_connection() as conn:
            if using_postgres():
                conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                conn.execute("SET LOCAL statement_timeout='3000ms'")
                if conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on':
                    raise RuntimeError('read_only_required')
            else:
                conn.execute('PRAGMA query_only=ON')
                conn.execute('BEGIN')
            result = build(conn, datetime.now(timezone.utc))
        _cached, _cached_at = result, time.monotonic()
        return result
