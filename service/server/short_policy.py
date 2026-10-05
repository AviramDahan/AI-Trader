"""Opt-in paper SHORT using the existing bearish three-zone/TP2 policy.

No broker, borrow availability, borrow fees or margin model is implied. Cash is
collateralized exactly as in the original paper short/cover API. Creation can be
disabled without disabling management of already persisted contracts.
"""
import json
import math
import os

VERSION = 'short_structure_v1'


def enabled():
    return os.getenv('STOCK_SCANNER_SHORT_ENABLED', 'false').lower() == 'true'


def is_short(plan):
    return isinstance(plan, dict) and plan.get('policy_version') == VERSION


def direction(trade):
    return -1 if trade.get('side') == 'short' else 1


def exit_value(trade, price):
    """Return collateral plus gross P/L per unit; never credit short proceeds."""
    return 2 * float(trade['entry_price']) - price if direction(trade) < 0 else price


def fill_cash_flow(trade, fill):
    value = -float(fill['price']) if fill['fill_type'] == 'entry' else exit_value(trade, float(fill['price']))
    return value * float(fill['quantity']) - float(fill['fee'])


def wrap(plan, data_as_of, decided_at):
    from single_target_policy import instant
    from datetime import datetime, time, timezone
    from zoneinfo import ZoneInfo
    source = (datetime.combine(datetime.fromisoformat(data_as_of).date(), time(16, 5), ZoneInfo('America/New_York')).astimezone(timezone.utc)
              if len(data_as_of) == 10 else instant(data_as_of))
    if source > instant(decided_at):
        raise ValueError('short_uncompleted_source_data')
    for zone in [*plan['zones'], plan['stop_zone']]:
        if not zone.get('pivots') or any(not p.get('confirmed_at') or instant(p['confirmed_at']) > source for p in zone['pivots']):
            raise ValueError('short_unconfirmed_zone')
    return dict(plan, policy_version=VERSION, action='SHORT', strategy='single',
                active_target=plan['targets'][1], source_data_at=source.isoformat(), decided_at=instant(decided_at).isoformat(),
                shadow_comparison='unavailable_no_short_staged_execution')


def validate(plan, entry=None, stop=None, action='SHORT'):
    from scanner_targets import structure_plan
    if not is_short(plan) or action != 'SHORT':
        raise ValueError('unsupported_short_contract')
    rebuilt = structure_plan('SELL', plan['entry'], plan['atr'], [*plan['zones'], plan['stop_zone']], plan['minimum_rr'])
    rebuilt = wrap(rebuilt, plan['source_data_at'], plan['decided_at'])
    if rebuilt != plan or (entry is not None and entry != plan['entry']) or (stop is not None and stop != plan['stop']):
        raise ValueError('short_contract_mismatch')
    return rebuilt


def validate_fill(plan, price):
    validate(plan)
    risk = plan['stop'] - price
    if not math.isfinite(price) or not plan['targets'][0] < price < plan['stop']:
        raise ValueError('short_fill_outside_plan')
    if any(z['low'] <= price <= z['high'] for z in [*plan['zones'], plan['stop_zone']]):
        raise ValueError('short_fill_inside_zone')
    if risk < max(1.5 * plan['atr'], .01 * price) - .005 or risk > 4 * plan['atr']:
        raise ValueError('short_fill_stop_distance')
    rr = [(price - target) / risk for target in plan['targets']]
    if rr[0] < 1 or rr[1] < plan['minimum_rr'] or sum(r * f for r, f in zip(rr, plan['fractions'])) < plan['minimum_rr']:
        raise ValueError('short_fill_rr')
    return rr[1]


def scanner_action(action, ticker):
    """SELL still closes an existing Long; never reverse it automatically."""
    if action != 'SELL' or not enabled():
        return action
    from scanner_engine import lifecycle_settings
    from database import get_db_connection
    if lifecycle_settings()['active_strategy'] != 'single':
        return action
    with get_db_connection() as conn:
        long = conn.execute("SELECT 1 FROM scanner_trades WHERE ticker=? AND status='open' AND is_shadow=0 AND side IN ('long','BUY')", (ticker,)).fetchone()
    return action if long else 'SHORT'


def saved(row, field):
    return json.loads(row.get(field) or '{}').get('target_plan')


def in_snapshot(tables):
    return (any(s.get('action') == 'SHORT' or is_short(saved(s, 'technical_json')) for s in tables['scanner_signals']) or
            any(t.get('side') == 'short' or is_short(saved(t, 'settings_json')) for t in tables['scanner_trades']) or
            any((o['purpose'] == 'entry' and o['side'] == 'sell') or is_short(saved(o, 'plan_json')) for o in tables['scanner_orders']))


def validate_snapshot(data):
    tables = data['tables']
    if not in_snapshot(tables):
        return
    if data['version'] != 4:
        raise ValueError('short_requires_format4')
    signals = {s['id']: s for s in tables['scanner_signals']}
    orders = {o['id']: o for o in tables['scanner_orders']}
    for s in signals.values():
        p = saved(s, 'technical_json')
        if s['action'] == 'SHORT' or is_short(p):
            validate(p, s['planned_entry'], s['original_stop'], s['action'])
            if [s[f'tp{i}'] for i in (1, 2, 3)] != p['targets'] or [s[f'tp{i}_pct'] for i in (1, 2, 3)] != p['fractions']:
                raise ValueError('short_signal_levels')
    for o in orders.values():
        s = signals[o['signal_id']]
        p, sp = saved(o, 'plan_json'), saved(s, 'technical_json')
        if s['action'] == 'SHORT' or is_short(p) or (o['purpose'] == 'entry' and o['side'] == 'sell'):
            if p != sp or not is_short(p) or o['purpose'] != 'entry' or o['side'] != 'sell' or o['limit_price'] != p['entry']:
                raise ValueError('short_order_contract')
            validate(p)
            if json.loads(o['plan_json'])['execution_settings']['active_strategy'] != 'single':
                raise ValueError('short_order_strategy')
    for t in tables['scanner_trades']:
        p = saved(t, 'settings_json')
        op = saved(orders[t['order_id']], 'plan_json')
        if t['side'] == 'short' or is_short(p) or is_short(op):
            if (not is_short(p) or p != op or t['side'] != 'short' or t['strategy'] != 'single' or t['is_shadow'] or t.get('legacy_position_id') or
                    t['signal_id'] != orders[t['order_id']]['signal_id'] or
                    [t[f'tp{i}'] for i in (1, 2, 3)] != p['targets'] or
                    [t[f'tp{i}_pct'] for i in (1, 2, 3)] != p['fractions'] or
                    t['original_stop'] != p['stop'] or t['current_stop'] != p['stop'] or
                    not math.isclose(t['original_r'], p['stop'] - t['entry_price'], abs_tol=1e-6)):
                raise ValueError('short_trade_contract')
            validate_fill(p, t['entry_price'])
            for fill in (f for f in tables['scanner_fills'] if f['trade_id'] == t['id']):
                if any(not math.isfinite(fill[k]) or fill[k] <= 0 for k in ('price','quantity')) or not math.isfinite(fill['fee']) or fill['fee'] < 0:
                    raise ValueError('invalid_short_fill_numbers')
                expected = 0 if fill['fill_type'] == 'entry' else (t['entry_price'] - fill['price']) * fill['quantity']
                if fill['fill_type'] not in {'entry','tp','stop'} or not math.isclose(fill['gross_pnl'],expected,abs_tol=1e-5):
                    raise ValueError('short_fill_pnl_mismatch')
