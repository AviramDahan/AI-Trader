"""Fail-closed snapshot compatibility for the single-target contract."""
import json
from single_target_policy import is_single, validate_single as validate, validate_single_fill as validate_fill


def plan(row, field):
    return json.loads(row.get(field) or '{}').get('target_plan')


def version(tables):
    from short_policy import in_snapshot
    from single_breakout_policy import is_breakout
    if any(is_breakout(plan(r, field)) or json.loads(r.get(field) or '{}').get('entry_execution')
           for table, field in (('scanner_signals','technical_json'), ('scanner_orders','plan_json'),
                                ('scanner_trades','settings_json')) for r in tables[table]):
        return 5
    if in_snapshot(tables):
        return 4
    return 3 if (any(is_single(plan(r, 'technical_json')) for r in tables['scanner_signals']) or
                 any(is_single(plan(r, 'plan_json')) for r in tables['scanner_orders']) or
                 any(is_single(plan(r, 'settings_json')) for r in tables['scanner_trades'])) else 2


def validate_snapshot(data):
    tables = data['tables']
    if version(tables) == 5 and data['version'] != 5:
        raise ValueError('entry_policy_requires_format5')
    if version(tables) == 3 and data['version'] not in (3,4,5):
        raise ValueError('single_policy_requires_format3')
    from short_policy import is_short
    for table, field in (('scanner_signals','technical_json'), ('scanner_orders','plan_json'),
                         ('scanner_trades','settings_json')):
        for row in tables[table]:
            p = plan(row, field)
            if p and p.get('policy_version') and not (is_single(p) or is_short(p)):
                raise ValueError('unsupported_preserved_policy')
    signals = {s['id']: s for s in tables['scanner_signals']}
    orders = {o['id']: o for o in tables['scanner_orders']}
    for s in signals.values():
        p = plan(s, 'technical_json')
        if is_single(p):
            validate(p, s['planned_entry'], s['original_stop'], s['action'])
            if [s['tp1'], s['tp2'], s['tp3']] != [p['active_target'], None, None]:
                raise ValueError('single_signal_levels_mismatch')
            if [s['tp1_pct'],s['tp2_pct'],s['tp3_pct']] != [1,0,0]:
                raise ValueError('single_signal_fractions_mismatch')
    for o in orders.values():
        from entry_window import eligible_from
        eligible_from(o)  # Validates the immutable window even with creation disabled.
        p = plan(o, 'plan_json')
        sp = plan(signals[o['signal_id']], 'technical_json')
        if json.loads(o.get('plan_json') or '{}').get('entry_execution'):
            from entry_window import instant
            if instant(o['valid_until']) != instant(signals[o['signal_id']]['valid_until']):
                raise ValueError('entry_window_signal_expiry_mismatch')
        if is_single(p) or is_single(sp):
            if p != sp or o['purpose'] != 'entry' or o['limit_price'] != p['entry']:
                raise ValueError('single_order_contract_mismatch')
            validate(p)
            if json.loads(o['plan_json'])['execution_settings']['active_strategy'] != 'single':
                raise ValueError('single_order_strategy_mismatch')
    for t in tables['scanner_trades']:
        p = plan(t, 'settings_json')
        op = plan(orders[t['order_id']], 'plan_json')
        saved_window = json.loads(t.get('settings_json') or '{}').get('entry_execution')
        order_window = json.loads(orders[t['order_id']].get('plan_json') or '{}').get('entry_execution')
        if saved_window != order_window:
            raise ValueError('trade_entry_window_mismatch')
        if saved_window:
            from entry_window import instant
            if instant(t['opened_at']) < instant(saved_window['entry_eligible_from']):
                raise ValueError('trade_before_entry_window')
        if is_single(p) or is_single(op):
            if (p != op or t['strategy'] != 'single' or t['is_shadow'] or t.get('legacy_position_id') or
                    [t['tp1'], t['tp2'], t['tp3']] != [p['active_target'], None, None] or
                    [t['tp1_pct'], t['tp2_pct'], t['tp3_pct']] != [1, 0, 0] or t['original_stop'] != p['stop']):
                raise ValueError('single_trade_contract_mismatch')
            validate_fill(p, t['entry_price'])
