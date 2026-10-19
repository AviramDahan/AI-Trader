"""Bounded read-only discovery-strategy outcomes, never an input to trading.

Public API: payload(hours=24|48|168) -> the JSON described below. report(conn,
hours=48, now=None) requires an already READ ONLY repeatable-read PostgreSQL
snapshot (SQLite query_only). summarize(...) is the same pure aggregator used
by isolated fixtures. No initializer, provider, AI, fill, outbox or settings write.

The response has window/as_of/coverage, current effective configuration,
overall and disjoint exact_set_groups, and NON-ADDITIVE strategy_rows. Lifecycle
counts use persisted IDs only; public output never contains those IDs, raw
contracts, prompts, quantities, cash or currency P&L. An old unattributed Native
row is UNATTRIBUTED, not retrospectively declared BASELINE. Native, Shadow and
Legacy are separate; only verified Native closed fills enter net metrics.
"""
from __future__ import annotations

import copy
import json
import math
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

from database import get_db_connection, using_postgres
from entry_discovery import BASELINE, FLAGS, validate_attribution, instant
from signal_research import outcome

VERSION = 1
ROW_LIMIT = 5000
FILL_LIMIT = 20000
JSON_LIMIT = 262144
UNATTRIBUTED = 'UNATTRIBUTED'
IDS = (BASELINE, *FLAGS, UNATTRIBUTED)
WINDOWS = (24, 48, 168)
CACHE_SECONDS = 60
_CACHE = {}
_LOCK = Lock()


def _at(value):
    try:
        return instant(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _document(value):
    if not isinstance(value, str) or len(value.encode()) > JSON_LIMIT:
        return None
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _configuration():
    from entry_discovery_capabilities import creation_allowed
    try:
        allowed = creation_allowed()
    except ValueError:
        allowed = None
    scanner_on = os.getenv('STOCK_SCANNER_ENABLED', 'false').lower() == 'true'
    flags = {key: os.getenv(flag, 'false').lower() == 'true' for key, flag in FLAGS.items()}
    return dict(source='EFFECTIVE_SERVER_CONFIGURATION_NOT_LIVENESS',
                independent_creation_capable=allowed, scanner_configured=scanner_on,
                enabled={BASELINE: scanner_on, **{key: (flag and allowed) if allowed is not None else None
                                                for key, flag in flags.items()}, UNATTRIBUTED: None},
                configured_flags=flags)


def _dedupe(rows, gaps, label):
    found = {}
    for row in rows:
        key = row.get('id')
        if key is None:
            gaps[label + '_missing_id'] += 1
            continue
        if key in found and found[key] != row:
            gaps[label + '_conflicting_duplicate_id'] += 1
        else:
            found[key] = row
    return list(found.values())


def _package(raw):
    value = _document(raw)
    if not value or 'entry_discovery' not in value:
        return None
    try:
        return validate_attribution(value['entry_discovery'])
    except ValueError:
        return None


def _key(package):
    return tuple(sorted(package['strategy_ids'])) if package else (UNATTRIBUTED,)


def _inside(value, since, now):
    value = _at(value)
    return value is not None and since <= value < now


def _verified_fills(trade, fills, now):
    """Augment the shared outcome check with causal clocks and price arithmetic."""
    entry, quantity = _number(trade.get('entry_price')), _number(trade.get('original_quantity'))
    original_stop, original_r = _number(trade.get('original_stop')), _number(trade.get('original_r'))
    opened = _at(trade.get('opened_at'))
    if (not entry or not quantity or quantity <= 0 or original_stop is None or not original_r or
            (original_stop-entry if trade.get('side') == 'short' else entry-original_stop) <= 0 or
            not math.isclose(abs(entry-original_stop), original_r, abs_tol=1e-6) or
            not opened or opened >= now):
        return False
    keys, entry_value = set(), 0.0
    for fill in fills:
        created, bar = _at(fill.get('created_at')), _at(fill.get('bar_at'))
        if not created or not bar or bar > created or created >= now or bar >= now or bar < opened:
            return False
        event = fill.get('event_key')
        if not isinstance(event, str) or not event or event in keys:
            return False
        keys.add(event)
        if fill.get('trade_id') != trade['id']:
            return False
        price, qty, gross = (_number(fill.get(key)) for key in ('price', 'quantity', 'gross_pnl'))
        if price is None or qty is None or gross is None or price <= 0 or qty <= 0:
            return False
        if fill.get('fill_type') == 'entry':
            if (fill.get('order_id') != trade.get('order_id') or bar != opened or
                    not math.isclose(gross, 0, abs_tol=1e-6)):
                return False
            entry_value += price * qty
        elif fill.get('fill_type') in {'tp', 'stop', 'sell'}:
            if trade.get('status') == 'closed' and (not _at(trade.get('closed_at')) or bar > _at(trade['closed_at'])):
                return False
            expected = (-1 if trade.get('side') == 'short' else 1) * (price-entry) * qty
            if not math.isclose(expected, gross, abs_tol=1e-5):
                return False
        else:
            return False
    return math.isclose(entry_value, entry*quantity, abs_tol=1e-5)


def _metrics(items, partial):
    closed = [item for item in items if item['closed_in_window']]
    verified = [item for item in closed if item['verified']]
    opened = [item for item in items if item['trade']['status'] == 'open' and item['verified']]
    complete = not partial and all(item['verified'] for item in closed)
    count = len(verified)
    wins = sum(item['net'] > 1e-8 for item in verified)
    losses = sum(item['net'] < -1e-8 for item in verified)
    zeros = count-wins-losses
    positive = sum(max(0, item['net']) for item in verified)
    negative = -sum(min(0, item['net']) for item in verified)
    ready = complete and count > 0
    return dict(status='VERIFIED_CLOSED_SAMPLE' if ready else 'PARTIAL_EVIDENCE' if not complete else 'DATA_INSUFFICIENT',
        verified_closed=count, wins=wins, losses=losses, breakeven=zeros,
        closed_win_rate=wins/count if ready else None,
        mean_closed_net_pct=sum(item['outcome']['closed_net_pct'] for item in verified)/count if ready else None,
        expectancy_net_r=sum(item['outcome']['closed_net_r'] for item in verified)/count if ready else None,
        profit_factor=positive/negative if ready and negative > 1e-8 else None,
        profit_factor_status=('PARTIAL_EVIDENCE' if not complete else 'DATA_INSUFFICIENT' if not count else
                              'UNDEFINED_NO_LOSSES' if negative <= 1e-8 else 'VERIFIED_CLOSED_NET_RATIO'),
        open_realized_mean_net_pct=(sum(item['outcome']['realized_net_pct'] for item in opened)/len(opened)
                                    if opened and not partial else None),
        open_realized_mean_net_r=(sum(item['outcome']['realized_net_r'] for item in opened)/len(opened)
                                  if opened and not partial else None),
        drawdown=None, drawdown_status='UNAVAILABLE_NO_STRATEGY_EQUITY_HISTORY')


def summarize(data, *, since, now, hours, clipped=None):
    """Pure aggregation of retained, bounded rows. Does not mutate its arguments."""
    if hours not in WINDOWS:
        raise ValueError('Supported windows:24,48,168 hours')
    since, now = instant(since), instant(now)
    if since >= now:
        raise ValueError('invalid_performance_window')
    clipped = sorted(set(clipped or []))
    gaps = Counter()
    signals = _dedupe(data.get('signals', []), gaps, 'signal')
    orders = _dedupe(data.get('orders', []), gaps, 'order')
    trades = _dedupe(data.get('trades', []), gaps, 'trade')
    fills = _dedupe(data.get('fills', []), gaps, 'fill')
    signals_by_id, signal_packages = {row['id']: row for row in signals}, {}
    for signal in signals:
        if signal.get('action') not in {'BUY', 'SHORT'}:
            continue
        package = _package(signal.get('technical_json'))
        created = _at(signal.get('created_at'))
        expected_direction = 'BUY' if signal['action'] == 'BUY' else 'SELL'
        if package and (not created or created >= now or instant(package['detected_at']) > created or
                        any(record['direction'] != expected_direction for record in package['detections'])):
            package = None
        signal_packages[signal['id']] = package
        if not package:
            gaps['signal_attribution_unavailable'] += 1
    order_packages, orders_by_id = {}, {row['id']: row for row in orders}
    for order in orders:
        if order.get('purpose') != 'entry':
            continue
        package = _package(order.get('plan_json'))
        if not package or package != signal_packages.get(order.get('signal_id')):
            package = None
            gaps['entry_order_attribution_unavailable_or_mismatch'] += 1
        order_packages[order['id']] = package
    fills_by_trade = {}
    for fill in fills:
        fills_by_trade.setdefault(fill.get('trade_id'), []).append(fill)
    specs, excluded = [], {'Shadow': {'trades': 0}, 'Legacy': {'trades': 0}}
    for trade in trades:
        if trade.get('legacy_position_id') is not None:
            excluded['Legacy']['trades'] += 1
            continue
        if trade.get('is_shadow'):
            excluded['Shadow']['trades'] += 1
            continue
        signal, order = signals_by_id.get(trade.get('signal_id')), orders_by_id.get(trade.get('order_id'))
        package = _package(trade.get('settings_json'))
        linked = bool(signal and order and order.get('signal_id') == trade.get('signal_id') and
                      order.get('purpose') == 'entry' and order.get('status') == 'filled' and
                      signal.get('action') in {'BUY', 'SHORT'} and not signal.get('legacy_unverified') and
                      order.get('side') == ('sell' if signal['action'] == 'SHORT' else 'buy') and
                      signal.get('agent_id') == trade.get('agent_id') and
                      _at(signal.get('created_at')) and _at(order.get('created_at')) and
                      _at(signal['created_at']) <= _at(order['created_at']) <= (_at(trade.get('opened_at')) or since) and
                      trade.get('side') == ('short' if signal['action'] == 'SHORT' else 'long'))
        if not linked or not package or package != signal_packages.get(trade.get('signal_id')) or package != order_packages.get(trade.get('order_id')):
            package = None
            gaps['trade_entry_attribution_unavailable_or_mismatch'] += 1
        actual_fills = fills_by_trade.get(trade['id'], [])
        try:
            result = outcome(trade, actual_fills, now)
            execution_verified = bool(linked and result['evidence_status'] == 'VERIFIED_FILLS' and
                            _verified_fills(trade, actual_fills, now) and
                            all(value is None or _number(value) is not None for key, value in result.items()
                                if key.endswith(('_pct', '_r'))) and
                            (trade['status'] != 'closed' or (_number(trade.get('remaining_quantity')) == 0 and
                                                           result['closed_net_r'] is not None)))
            verified = bool(package and execution_verified)
        except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError):
            result, verified, execution_verified = {}, False, False
        if not verified:
            gaps['trade_fill_history_unverified'] += 1
        net = (_number(trade.get('realized_pnl')) or 0) - (_number(trade.get('fees')) or 0)
        specs.append(dict(trade=trade, package=package, key=_key(package), verified=verified,
            execution_verified=execution_verified,
            outcome=result, net=0.0 if abs(net) < 1e-8 else net,
            actual_fills=actual_fills, closed_in_window=trade.get('status') == 'closed' and
                _inside(trade.get('closed_at'), since, now)))
    lifecycle_partial = bool(set(clipped) & {'signals', 'orders', 'trades', 'fills', 'linked_signals', 'linked_orders'} or
                             any('conflicting_duplicate_id' in key or 'missing_id' in key for key in gaps))
    keys = {_key(value) for value in signal_packages.values()} | {_key(value) for value in order_packages.values()} | {item['key'] for item in specs}

    def group(keys_for_group, *, contributor=False):
        chosen_signals = [row for row in signals if row.get('action') in {'BUY', 'SHORT'} and
                          not row.get('legacy_unverified') and
                          _key(signal_packages.get(row['id'])) in keys_for_group and
                          _inside(row.get('created_at'), since, now)]
        chosen_orders = [row for row in orders if row.get('purpose') == 'entry' and
                         not (signals_by_id.get(row.get('signal_id')) or {}).get('legacy_unverified') and
                         _key(order_packages.get(row['id'])) in keys_for_group]
        items = [item for item in specs if item['key'] in keys_for_group]
        verified = [item for item in items if item['execution_verified']]
        counts = dict(signals=len(chosen_signals),
            entry_orders=sum(_inside(row.get('created_at'), since, now) for row in chosen_orders),
            pending_entry_orders=sum(row.get('status') == 'pending' for row in chosen_orders),
            uncertain_entry_orders=sum(row.get('status') == 'recovery_uncertain' for row in chosen_orders),
            actual_entries=sum(_inside(item['trade'].get('opened_at'), since, now) for item in verified),
            open_trades=sum(item['trade'].get('status') == 'open' for item in items),
            fully_closed_trades=sum(item['closed_in_window'] for item in items),
            exit_trades=sum(any(fill.get('fill_type') != 'entry' and _inside(fill.get('bar_at'), since, now)
                                for fill in item['actual_fills']) for item in verified),
            exit_fills=sum(sum(fill.get('fill_type') != 'entry' and _inside(fill.get('bar_at'), since, now)
                               for fill in item['actual_fills']) for item in verified),
            partial_exit_trades=sum(item['trade'].get('status') == 'open' and
                                   0 < (item['outcome'].get('exited_pct') or 0) < 100 for item in verified))
        public_counts = {key: None for key in counts} if lifecycle_partial else dict(counts)
        if any(not item['execution_verified'] for item in items):
            for name in ('actual_entries', 'exit_trades', 'exit_fills', 'partial_exit_trades'):
                public_counts[name] = None
        return dict(counts=public_counts,
                    observed_counts=counts, metrics=_metrics(items, lifecycle_partial),
                    recorded_unverified_trades=sum(not item['verified'] for item in items),
                    non_additive=contributor)

    exact = [dict(strategy_ids=list(key), **group({key})) for key in sorted(keys)]
    configuration = _configuration()
    rows = [dict(strategy_id=key, enabled=configuration['enabled'][key],
                 **group({value for value in keys if key in value}, contributor=True)) for key in IDS]
    overall = group(keys)
    # A missing source cannot be silently assigned to any one contributor.
    ambiguous = any(item['key'] == (UNATTRIBUTED,) for item in specs)
    if ambiguous:
        for row in rows:
            if row['strategy_id'] != UNATTRIBUTED:
                row['counts'] = {key: None for key in row['counts']}
                row['metrics'].update(closed_win_rate=None, mean_closed_net_pct=None, expectancy_net_r=None,
                                      profit_factor=None, profit_factor_status='PARTIAL_ATTRIBUTION', status='PARTIAL_ATTRIBUTION')
    detector_states = {key: Counter() for key in FLAGS}
    for row in data.get('discovery', []):
        observation = _document(row.get('metrics_json'))
        if not observation or observation.get('evidence_gap'):
            gaps['discovery_observation_unavailable'] += 1
            continue
        for key, record in (observation.get('strategy_results') or {}).items():
            if key in FLAGS and isinstance(record, dict) and record.get('state') in {'DETECTED', 'FORMING', 'UNKNOWN', 'REJECTED'}:
                detector_states[key][record['state']] += 1
    for row in rows:
        row['detector_states'] = dict(detector_states[row['strategy_id']]) if row['strategy_id'] in FLAGS else None
    return dict(version=VERSION, as_of=now.isoformat(), window_since=since.isoformat(), window_hours=hours,
        coverage=dict(status='PARTIAL' if clipped or gaps else 'COMPLETE_RETAINED_COHORT', clipped=clipped,
            evidence_gaps=dict(gaps), discovery_journal='OBSERVED' if data.get('discovery') else 'NOT_RECORDED',
            historical_shortlist_membership='UNAVAILABLE_NOT_RECONSTRUCTED'),
        configuration=configuration, overall=overall, exact_set_groups=exact, strategy_rows=rows,
        excluded_cohorts=excluded,
        scope=dict(returns_are_portfolio_return=False, source='ACTUAL_RETAINED_PAPER_RECORDS_ONLY',
            contributors='NON_ADDITIVE_OVERLAPPING_MEMBERSHIP', exact_sets='DISJOINT_ADDITIVE_NATIVE_GROUPS',
            signal_window='Created in window; BUY and SHORT only, closing SELL excluded',
            pending_window='Current retained entry orders; may have been created before window',
            entry_window='Actual verified Native trade opened in window, never number of fills',
            outcome_window='Native trades fully closed in window; earlier entries included separately from conversion',
            open_window='Currently open retained Native positions; partial exits are not closed trades',
            net_definition='Actual exit gross less all paid entry/exit fees; slippage already in fill prices',
            profit_factor_definition='Sum positive closed net / absolute sum negative closed net; no losses is undefined',
            expectancy_definition='Equal-weight mean closed net R; net % is equal-weight mean trade return, not a sum',
            unrealized_in_closed_metrics=False, strategy_capital_accounts=False))


def _bounded(conn, sql, params, clipped, label, limit=ROW_LIMIT):
    rows = [dict(row) for row in conn.execute(sql+' LIMIT ?', (*params, limit+1)).fetchall()]
    if len(rows) > limit:
        clipped.append(label)
    return rows[:limit]


def _linked(conn, table, ids, columns, clipped, label, budget=ROW_LIMIT):
    result = []
    for start in range(0, len(ids), 256):
        batch = ids[start:start+256]
        if not batch:
            continue
        remaining = budget-len(result)
        result.extend(_bounded(conn, f'SELECT {columns} FROM {table} WHERE id IN ('+
            ','.join('?' for _ in batch)+') ORDER BY id DESC', tuple(batch), clipped, label, max(0, remaining)))
        if len(result) >= budget:
            if start+256 < len(ids):
                clipped.append(label)
            break
    return result


def report(conn, hours=48, now=None):
    """Same-snapshot SELECTs only; caller must provide explicit read-only guards."""
    if hours not in WINDOWS:
        raise ValueError('Supported windows:24,48,168 hours')
    if using_postgres():
        if (conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on' or
                conn.execute('SHOW transaction_isolation').fetchone()[0] != 'repeatable read'):
            raise RuntimeError('read_only_snapshot_required')
    elif conn.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise RuntimeError('read_only_snapshot_required')
    from scanner_engine import scanner_agent_id
    agent = scanner_agent_id(conn.cursor())
    now = instant(now or datetime.now(timezone.utc))
    since = now-timedelta(hours=hours)
    args = (since.isoformat(), now.isoformat())
    window = lambda col: f'julianday({col})>=julianday(?) AND julianday({col})<julianday(?)'
    clipped, data = [], {}
    signal_fields = 'id,agent_id,scan_id,ticker,action,status,created_at,legacy_unverified,technical_json'
    order_fields = 'id,signal_id,purpose,side,status,created_at,valid_until,plan_json'
    data['signals'] = _bounded(conn, f'SELECT {signal_fields} FROM scanner_signals WHERE agent_id=? AND '+
        window('created_at')+' ORDER BY id DESC', (agent, *args), clipped, 'signals')
    data['orders'] = _bounded(conn, 'SELECT '+','.join('o.'+field for field in order_fields.split(','))+
        ' FROM scanner_orders o JOIN scanner_signals s ON s.id=o.signal_id WHERE s.agent_id=? AND '+
        "o.purpose='entry' AND (("+window('o.created_at')+
        ") OR o.status IN ('pending','recovery_uncertain')) ORDER BY o.id DESC", (agent, *args), clipped, 'orders')
    data['trades'] = _bounded(conn, 'SELECT * FROM scanner_trades WHERE agent_id=? AND (('+window('opened_at')+
        ') OR ('+window('closed_at')+") OR (status='open' AND julianday(opened_at)<julianday(?))) ORDER BY id DESC",
        (agent, *args, *args, now.isoformat()), clipped, 'trades')
    required_signals = {row['signal_id'] for row in data['orders']+data['trades']}
    required_orders = {row['order_id'] for row in data['trades']}
    data['signals'] += _linked(conn, 'scanner_signals', sorted(required_signals-{row['id'] for row in data['signals']}),
                               signal_fields, clipped, 'linked_signals', ROW_LIMIT-len(data['signals']))
    data['orders'] += _linked(conn, 'scanner_orders', sorted(required_orders-{row['id'] for row in data['orders']}),
                              order_fields, clipped, 'linked_orders', ROW_LIMIT-len(data['orders']))
    data['fills'] = []
    trade_ids = sorted({row['id'] for row in data['trades']})
    for start in range(0, len(trade_ids), 256):
        batch = trade_ids[start:start+256]
        remaining = FILL_LIMIT-len(data['fills'])
        data['fills'] += _bounded(conn, 'SELECT * FROM scanner_fills WHERE trade_id IN ('+
            ','.join('?' for _ in batch)+') ORDER BY id', tuple(batch), clipped, 'fills', max(0, remaining))
        if len(data['fills']) >= FILL_LIMIT:
            if start+256 < len(trade_ids):
                clipped.append('fills')
            break
    data['discovery'] = _bounded(conn, "SELECT id,scan_id,ticker,metrics_json,created_at FROM scanner_candidates WHERE stage='entry_discovery' AND "+
        window('created_at')+' ORDER BY id DESC', args, clipped, 'discovery')
    return summarize(data, since=since, now=now, hours=hours, clipped=clipped)


def payload(hours=48):
    if hours not in WINDOWS:
        raise ValueError('Supported windows:24,48,168 hours')
    with _LOCK:
        cached = _CACHE.get(hours)
        if cached and monotonic()-cached[0] < CACHE_SECONDS:
            return copy.deepcopy(cached[1])
        conn = get_db_connection()
        try:
            if using_postgres():
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                conn.execute("SET LOCAL statement_timeout='5s'")
                conn.execute("SET LOCAL lock_timeout='2s'")
                conn.execute("SET LOCAL idle_in_transaction_session_timeout='20s'")
            else:
                conn.execute('PRAGMA query_only=ON')
                conn.execute('BEGIN')
            result = report(conn, hours)
            _CACHE[hours] = (monotonic(), result)
            return copy.deepcopy(result)
        finally:
            conn.close()
