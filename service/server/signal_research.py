"""Bounded, read-only views of retained scanner decisions and signal outcomes.

No reconstruction, provider calls, AI or trading writes. Counts describe recorded
observations, not counterfactual opportunities or independent portfolio returns.
"""
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

from database import get_db_connection, using_postgres
from scanner_engine import market_session_state, scanner_agent_id

ROW_LIMIT = 5000
CACHE_SECONDS = 60
_CACHE = {}
_CACHE_LOCK = Lock()


def loads(value):
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (AttributeError, ValueError):
        return None


def reason_stage(reason):
    reason = (reason or '').removeprefix('pre_')
    if reason in ('waiting_regular_session', 'post_waiting_regular_session'):
        return 'session_wait'
    if 'quote' in reason:
        return 'quote'
    if reason in {'insufficient_current_news', 'news_provider_unavailable_fail_closed'}:
        return 'news'
    if 'cooldown' in reason:
        return 'cooldown'
    if reason in {'ai_or_confidence_filter', 'news_sentiment_conflict', 'ai_hold',
                  'ai_confidence_below_threshold', 'ai_news_relevance_below_threshold'}:
        return 'ai_filter'
    if any(word in reason for word in ('zone', 'resistance', 'rounded', 'stop', 'risk_reward', 'target', 'structure', 'pivot')):
        return 'targets'
    return 'other'


def outcome(trade, fills, now=None):
    """Weight partial exits by original quantity, fee-inclusive from real fills.

    Slippage is already in execution prices; never subtract it twice. Open value
    uses a timestamped completed monitor mark, not a fill/entry fallback.
    """
    entry, qty, risk = (number(trade.get(k)) for k in ('entry_price', 'original_quantity', 'original_r'))
    valid = all(v is not None and v > 0 for v in (entry, qty, risk))
    entry_fills = [f for f in fills if f['fill_type'] == 'entry']
    exits = [f for f in fills if f['fill_type'] != 'entry']
    valid_fills = all(number(f.get(k)) is not None for f in fills for k in ('quantity','fee','gross_pnl','price'))
    valid_fills = valid_fills and all(float(f['quantity'])>0 and float(f['fee'])>=0 and float(f['price'])>0 for f in fills)
    exited = sum(float(f['quantity']) for f in exits) if valid_fills else 0
    remaining = number(trade.get('remaining_quantity'))
    coverage = (valid and valid_fills and bool(entry_fills) and remaining is not None and remaining>=0 and
                number(trade.get('fees')) is not None and float(trade['fees'])>=0 and number(trade.get('realized_pnl')) is not None and
                math.isclose(sum(float(f['quantity']) for f in entry_fills), qty, abs_tol=1e-6) and
                math.isclose(exited + remaining, qty, abs_tol=1e-6) and
                math.isclose(sum(float(f['fee']) for f in fills), float(trade['fees']), abs_tol=1e-6) and
                math.isclose(sum(float(f['gross_pnl']) for f in exits), float(trade['realized_pnl']), abs_tol=1e-6))
    legacy = trade.get('legacy_position_id') is not None
    # Legacy history is not inferred from imported quantities or current marks.
    eligible = coverage and not legacy
    net = float(trade['realized_pnl']) - float(trade['fees']) if eligible else None
    closed = trade['status'] == 'closed'
    result = dict(trade_id=trade['id'], signal_id=trade['signal_id'], ticker=trade['ticker'],
        side=trade['side'], strategy=trade['strategy'],
        cohort='Legacy' if legacy else 'Shadow' if trade['is_shadow'] else 'Native',
        status=trade['status'], opened_at=trade['opened_at'], closed_at=trade['closed_at'],
        entry_price=entry, original_stop=trade['original_stop'], current_stop=trade['current_stop'],
        policy_version=(loads(trade['settings_json']).get('target_plan') or {}).get('policy_version'),
        evidence_status='VERIFIED_FILLS' if eligible else 'UNAVAILABLE_INCOMPLETE_HISTORY',
        closed_net_pct=100*net/(entry*qty) if eligible and closed else None,
        closed_net_r=net/(risk*qty) if eligible and closed else None,
        realized_net_pct=100*net/(entry*qty) if eligible else None,
        realized_net_r=net/(risk*qty) if eligible else None,
        fee_pct=100*float(trade['fees'])/(entry*qty) if eligible else None,
        exited_pct=100*exited/qty if valid and valid_fills else None,
        remaining_pct=100*remaining/qty if valid and remaining is not None else None,
        open_gross_pct=None, open_gross_r=None, marked_net_pct=None, marked_net_r=None,
        mark_at=None, mark_status='NOT_AVAILABLE', mark_stale=None,
        mfe_pct=None, mae_pct=None, excursion_status='UNAVAILABLE_NO_RETAINED_INTRABAR_SERIES',
        holding_hours=None, exit_types=dict(Counter(f['fill_type'] for f in exits)),
        exits=[dict(type=f['fill_type'], at=f['bar_at'], price=number(f['price']),
                    position_pct=100*float(f['quantity'])/qty if valid and valid_fills else None) for f in exits])
    opened, ended, mark = time(trade['opened_at']), time(trade['closed_at']), time(trade['last_bar_at'])
    if closed and opened and ended and ended >= opened:
        result['holding_hours'] = (ended-opened).total_seconds()/3600
    boundary = time(trade.get('managed_from')) or opened
    price = number(trade['last_price'])
    now = now or datetime.now(timezone.utc)
    completed = mark+timedelta(minutes=5) if mark else None
    if not closed and eligible and mark and boundary and mark >= boundary and completed <= now and price is not None and price > 0:
        gross = (-1 if trade['side'] == 'short' else 1) * (price-entry)*remaining
        result.update(open_gross_pct=100*gross/(entry*qty), open_gross_r=gross/(risk*qty),
                      marked_net_pct=100*(net+gross)/(entry*qty), marked_net_r=(net+gross)/(risk*qty),
                      mark_at=completed.isoformat(), mark_status='COMPLETED_MONITOR_BAR',
                      mark_stale=(now-completed).total_seconds()>900)
    return result


def _bounded(conn, sql, params, clipped, name):
    rows = [dict(r) for r in conn.execute(sql + ' LIMIT ?', (*params, ROW_LIMIT+1)).fetchall()]
    if len(rows) > ROW_LIMIT:
        clipped.append(name)
    return rows[:ROW_LIMIT]


def report(conn, hours=48, now=None):
    if hours not in (24, 48, 168):
        raise ValueError('Supported windows: 24, 48, 168 hours')
    now = now or datetime.now(timezone.utc)
    since, until = (now-timedelta(hours=hours)).isoformat(), now.isoformat()
    agent = scanner_agent_id(conn.cursor())
    clipped = []
    # Independent caps keep a large technical universe from evicting all target
    # and final-review evidence. Technical JSON can contain sizable news payloads;
    # only keys are needed here. Do not load those payloads on a dashboard refresh.
    technical = _bounded(conn, '''SELECT id,scan_id,ticker,company,created_at
        FROM scanner_candidates WHERE stage='technical' AND created_at>=? AND created_at<=? ORDER BY id DESC''',
        (since, until), clipped, 'technical_details')
    journal = []
    for stage in ('target_check','final','ai_decision'):
        journal.extend(_bounded(conn, '''SELECT id,scan_id,ticker,company,stage,status,reason,metrics_json,created_at
            FROM scanner_candidates WHERE stage=? AND created_at>=? AND created_at<=? ORDER BY id DESC''',
            (stage, since, until), clipped, stage))
    universe_counts = dict(conn.execute('''SELECT COUNT(*) observations, COUNT(DISTINCT ticker) tickers FROM
        (SELECT scan_id,ticker FROM scanner_candidates WHERE created_at>=? AND created_at<=?
         GROUP BY scan_id,ticker) recorded''', (since,until)).fetchone())
    technical_count = conn.execute('''SELECT COUNT(*) n FROM (SELECT scan_id,ticker FROM scanner_candidates
        WHERE stage='technical' AND created_at>=? AND created_at<=? GROUP BY scan_id,ticker) recorded''',
        (since,until)).fetchone()['n']
    reviews = _bounded(conn, '''SELECT review_id,scan_id,ticker,result,reject_reason,attempts_json,updated_at
        FROM scanner_final_ai_telemetry WHERE updated_at>=? AND updated_at<=? ORDER BY id DESC''',
        (since, until), clipped, 'reviews')
    signals = _bounded(conn, '''SELECT id,scan_id,ticker,action,status,actual_entry,created_at,valid_until,legacy_unverified
        FROM scanner_signals WHERE agent_id=? AND created_at>=? AND created_at<=? ORDER BY id DESC''',
        (agent, since, until), clipped, 'signals')
    orders = _bounded(conn, '''SELECT o.id,o.signal_id,o.purpose,o.status,o.created_at,o.valid_until
        FROM scanner_orders o JOIN scanner_signals s ON s.id=o.signal_id
        WHERE s.agent_id=? AND s.created_at>=? AND s.created_at<=? ORDER BY o.id DESC''',
        (agent, since, until), clipped, 'orders')
    # Include positions opened earlier and exited in the window; never count fills as trades.
    trades = _bounded(conn, '''SELECT * FROM scanner_trades WHERE agent_id=? AND
        (opened_at>=? OR closed_at>=? OR status='open') ORDER BY id DESC''',
        (agent, since, since), clipped, 'trades')
    fills = _bounded(conn, '''SELECT f.* FROM scanner_fills f JOIN scanner_trades t ON t.id=f.trade_id
        WHERE t.agent_id=? AND (t.opened_at>=? OR t.closed_at>=? OR t.status='open') ORDER BY f.id''',
        (agent, since, since), clipped, 'fills')
    cases = {}
    for row in journal:
        key = (row['scan_id'], row['ticker'])
        c = cases.setdefault(key, dict(scan_id=key[0], ticker=key[1], company=row['company'],
            at=row['created_at'], direction=None, technical_recorded=False, rejection=None,
            target_checks=[], reviews=[], signals=[], orders=[]))
        if row['company']:
            c['company'] = row['company']
        data = loads(row['metrics_json'])
        if row['stage'] == 'technical':
            c.update(technical_recorded=True, direction=data.get('technical_direction'))
        elif row['stage'] == 'final' and c['rejection'] is None:
            c['rejection'] = row['reason']
        elif row['stage'] == 'ai_decision':
            c['ai_decision'] = {k:data.get(k) for k in ('action','confidence','news_sentiment','news_relevance',
                'filter_failures','confidence_threshold','relevance_threshold','quote','daily_reference_close','daily_reference_as_of')}
        elif row['stage'] == 'target_check':
            # Allowlist only: no prompts, news content, source-input hashes or model output.
            check = {k: data.get(k) for k in ('phase', 'policy_version', 'strategy', 'action',
                'observed_at', 'decided_at', 'outcome', 'rejection_reason', 'rejection_detail',
                'quote', 'geometry', 'accepted_levels', 'evidence_gap', 'source_inputs', 'source_observed_at')}
            if check['source_inputs']:
                check['source_inputs'] = {k: check['source_inputs'].get(k) for k in ('atr', 'data_as_of', 'zones')}
            c['target_checks'].append(check)
            c['direction'] = c['direction'] or data.get('action')
    for row in technical:
        key=(row['scan_id'],row['ticker'])
        c=cases.setdefault(key, dict(scan_id=key[0],ticker=key[1],company=row['company'],at=row['created_at'],
            direction=None,technical_recorded=True,rejection=None,target_checks=[],reviews=[],signals=[],orders=[]))
        c['technical_recorded']=True
        c['company']=c['company'] or row['company']
    for row in reviews:
        c = cases.get((row['scan_id'], row['ticker']))
        if c is not None:
            attempts = loads('{"items":'+(row['attempts_json'] or '[]')+'}').get('items') or []
            c['reviews'].append(dict(result=row['result'], rejection=row['reject_reason'],
                                     attempts=len(attempts), validated=any(a.get('result')=='validated' for a in attempts if isinstance(a,dict)),
                                     at=row['updated_at']))
    orders_by_signal = {}
    for order in orders:
        orders_by_signal.setdefault(order['signal_id'], []).append(order)
    for s in signals:
        c = cases.get((s['scan_id'], s['ticker']))
        if c is not None:
            c['signals'].append({k:s[k] for k in ('id','status','actual_entry','valid_until')})
            c['orders'].extend({k:o[k] for k in ('id','status','purpose')} for o in orders_by_signal.get(s['id'], []))
    reasons, stages, quote_context, waits = Counter(), Counter(), Counter(), Counter()
    shapes = set()
    for c in cases.values():
        c['target_checks'].sort(key=lambda r: r.get('observed_at') or '')
        c['rejection_stage'] = reason_stage(c['rejection']) if c['rejection'] else None
        if c['rejection_stage'] == 'session_wait':
            waits[c['rejection']] += 1
        elif c['rejection']:
            reasons[c['rejection']] += 1
            stages[c['rejection_stage']] += 1
        check_time = next((time(r['observed_at']) for r in c['target_checks'] if time(r['observed_at'])), time(c['at']))
        c['session'] = market_session_state(check_time) if check_time else None
        if c['rejection_stage']=='quote':
            quote_context['regular_session' if c['session'] and c['session']['is_open'] else 'outside_regular_session' if c['session'] else 'unknown'] += 1
        c['ai_attempts'] = sum(r['attempts'] for r in c['reviews'])
        c['target_pass'] = any(r['phase']=='pre_ai' and r['outcome']=='PASS' for r in c['target_checks'])
        # Exact geometry at a reference price, NOT an asserted unique opportunity.
        for r in c['target_checks']:
            if r.get('source_inputs') and (r.get('quote') or {}).get('price') is not None:
                shapes.add(json.dumps([c['ticker'],r['policy_version'],r['action'],r['quote']['price'],r['source_inputs']],sort_keys=True))
    fills_by_trade = {}
    for fill in fills:
        fills_by_trade.setdefault(fill['trade_id'], []).append(fill)
    outcomes = [outcome(t, fills_by_trade.get(t['id'], []), now) for t in trades]
    groups = []
    for key in sorted({(o['cohort'],o['side'],o['strategy']) for o in outcomes}):
        items = [o for o in outcomes if (o['cohort'],o['side'],o['strategy'])==key]
        complete = [o for o in items if o['closed_net_r'] is not None]
        groups.append(dict(cohort=key[0], side=key[1], strategy=key[2], trades=len(items),
            open=sum(o['status']=='open' for o in items), closed=sum(o['status']=='closed' for o in items),
            verified_closed=len(complete),
            mean_net_pct=sum(o['closed_net_pct'] for o in complete)/len(complete) if complete else None,
            expectancy_net_r=sum(o['closed_net_r'] for o in complete)/len(complete) if complete else None,
            win_rate=sum(o['closed_net_r']>0 for o in complete)/len(complete) if complete else None))
    entry_orders = [o for o in orders if o['purpose']=='entry']
    accepted = [s for s in signals if not s['legacy_unverified'] and s['action'] in ('BUY','SHORT')]
    oldest = conn.execute("SELECT MIN(created_at) at FROM scanner_candidates WHERE stage='target_check'").fetchone()['at']
    records = sorted(cases.values(),key=lambda c:(bool(c['target_checks'] or c['reviews'] or c['signals'] or c['rejection']),c['at']),reverse=True)
    return dict(generated_at=until, window_since=since, window_hours=hours, available_since=oldest,
        clipped=clipped, record_limit=200, records_clipped=len(records)>200,
        scope='Retained scanner observations only; unavailable stages are not reconstructed',
        counts=dict(candidate_observations=universe_counts['observations'], unique_tickers=universe_counts['tickers'],
            detailed_observations=len(records), exact_reference_configurations=len(shapes), technical_recorded=technical_count,
            target_checked=sum(any(r['outcome'] in ('PASS','REJECT') for r in c['target_checks']) for c in records), target_pass=sum(c['target_pass'] for c in records),
            ai_attempted=sum(c['ai_attempts']>0 for c in records), ai_attempt_records=sum(c['ai_attempts'] for c in records),
            ai_validated=sum(any(r['validated'] for r in c['reviews']) for c in records),
            signals_qualified=len(accepted), entries=sum(s['actual_entry'] is not None for s in accepted)),
        rejection_reasons=dict(reasons), rejection_stages=dict(stages), quote_context=dict(quote_context),
        session_waits=dict(waits),
        execution=dict(entry_orders=len(entry_orders), statuses=dict(Counter(o['status'] for o in entry_orders)),
            allocation_blocked=sum(s['status']=='RISK_BLOCKED' for s in accepted),
            fill_rate=sum(o['status']=='filled' for o in entry_orders)/len(entry_orders) if entry_orders else None),
        records=records[:200], outcome_groups=groups, outcomes=outcomes,
        outcome_note='Equal-weight closed signal outcomes, not account return. Open marks may have different timestamps. Shadow has no independent capital. Legacy excluded from verified metrics.')


def payload(hours=48):
    if hours not in (24,48,168):
        raise ValueError('Supported windows: 24, 48, 168 hours')
    # Coalesce concurrent readers: one bounded snapshot per window per minute,
    # with no background workers. Failed reads never overwrite a good cache.
    with _CACHE_LOCK:
        cached = _CACHE.get(hours)
        if cached and monotonic()-cached[0] < CACHE_SECONDS:
            return cached[1]
        conn = get_db_connection()
        try:
            if using_postgres():
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                conn.execute("SET LOCAL statement_timeout='8s'")
            else:
                conn.execute('PRAGMA query_only=ON')
            result=report(conn, hours)
            _CACHE[hours]=(monotonic(), result)
            return result
        finally:
            conn.close()
