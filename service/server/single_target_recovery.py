"""Fail-closed snapshot compatibility for the single-target contract."""
import json
from single_target_policy import is_v2, validate, validate_fill


def plan(row, field):
    return json.loads(row.get(field) or '{}').get('target_plan')


def version(tables):
    return 3 if (any(is_v2(plan(r, 'technical_json')) for r in tables['scanner_signals']) or
                 any(is_v2(plan(r, 'plan_json')) for r in tables['scanner_orders']) or
                 any(is_v2(plan(r, 'settings_json')) for r in tables['scanner_trades'])) else 2


def validate_snapshot(data):
    tables = data['tables']
    if version(tables) == 3 and data['version'] != 3:
        raise ValueError('single_policy_requires_format3')
    signals = {s['id']: s for s in tables['scanner_signals']}
    orders = {o['id']: o for o in tables['scanner_orders']}
    for s in signals.values():
        p = plan(s, 'technical_json')
        if is_v2(p):
            validate(p, s['planned_entry'], s['original_stop'], s['action'])
            if [s['tp1'], s['tp2'], s['tp3']] != [p['active_target'], None, None]:
                raise ValueError('single_signal_levels_mismatch')
    for o in orders.values():
        p = plan(o, 'plan_json')
        sp = plan(signals[o['signal_id']], 'technical_json')
        if is_v2(p) or is_v2(sp):
            if p != sp or o['purpose'] != 'entry' or o['limit_price'] != p['entry']:
                raise ValueError('single_order_contract_mismatch')
            validate(p)
            if json.loads(o['plan_json'])['execution_settings']['active_strategy'] != 'single':
                raise ValueError('single_order_strategy_mismatch')
    for t in tables['scanner_trades']:
        p = plan(t, 'settings_json')
        op = plan(orders[t['order_id']], 'plan_json')
        if is_v2(p) or is_v2(op):
            if (p != op or t['strategy'] != 'single' or t['is_shadow'] or t.get('legacy_position_id') or
                    [t['tp1'], t['tp2'], t['tp3']] != [p['active_target'], None, None] or
                    [t['tp1_pct'], t['tp2_pct'], t['tp3_pct']] != [1, 0, 0] or t['original_stop'] != p['stop']):
                raise ValueError('single_trade_contract_mismatch')
            validate_fill(p, t['entry_price'])
