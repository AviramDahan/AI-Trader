"""Fail-closed snapshot compatibility for the single-target contract."""
import json
from single_target_policy import is_single, validate_single as validate, validate_single_fill as validate_fill


def plan(row, field):
    return json.loads(row.get(field) or '{}').get('target_plan')


def validate_settings(settings):
    """Bounded operational settings are part of the recovery contract, not prose.

    In particular a persisted emergency history must never be downgraded to a
    pre-control format or silently dropped by a sanitizer/older reader.
    """
    if not isinstance(settings, list) or len(settings) > 2:
        raise ValueError('unsupported_recovery_settings')
    seen = set()
    for row in settings:
        if (not isinstance(row, dict) or set(row) != {'key', 'value_json', 'updated_at'}
                or row['key'] not in {'active_exit_strategy', 'paper_entry_emergency_v1'}
                or row['key'] in seen):
            raise ValueError('unsupported_recovery_settings')
        seen.add(row['key'])
        if row['key'] == 'paper_entry_emergency_v1':
            from entry_emergency import validate, MAX_BYTES
            def pairs(items):
                result = {}
                for key, item in items:
                    if key in result:
                        raise ValueError('duplicate_emergency_snapshot_key')
                    result[key] = item
                return result
            raw = row['value_json']
            if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
                raise ValueError('invalid_emergency_snapshot_payload')
            payload = validate(json.loads(raw, object_pairs_hook=pairs))
            if (payload['revision'] == 0 or payload['updated_at'] is None or
                    row['updated_at'] != payload['updated_at']):
                raise ValueError('emergency_snapshot_clock_mismatch')
    return 'paper_entry_emergency_v1' in seen


def version(tables, settings=None):
    if settings is not None and validate_settings(settings):
        return 9
    from short_policy import in_snapshot
    from single_breakout_policy import is_breakout
    fields = (('scanner_signals','technical_json'), ('scanner_orders','plan_json'),
              ('scanner_trades','settings_json'))
    if any('entry_strategy_execution' in json.loads(r.get(field) or '{}') or
           'last_strategy_entry_block' in json.loads(r.get(field) or '{}')
           for table, field in fields for r in tables[table]):
        return 8
    if any('entry_discovery' in json.loads(r.get(field) or '{}')
           for table, field in fields for r in tables[table]):
        return 7
    if any('entry_price_retry' in json.loads(r.get(field) or '{}') or
           'last_entry_price_block' in json.loads(r.get(field) or '{}')
           for table, field in (('scanner_orders','plan_json'), ('scanner_trades','settings_json'))
           for r in tables[table]):
        return 6
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
    required = version(tables, data.get('settings', []))
    if required >= 7 or data['version'] >= 7:
        if data['version'] != required:
            raise ValueError('discovery_snapshot_format_content_mismatch')
    if required == 9:
        from datetime import datetime
        control = next(row for row in data['settings'] if row['key'] == 'paper_entry_emergency_v1')
        updated = json.loads(control['value_json'])['updated_at']
        if updated is not None and datetime.fromisoformat(updated.replace('Z', '+00:00')) > datetime.fromisoformat(data['created_at'].replace('Z', '+00:00')):
            raise ValueError('future_emergency_snapshot_control')
    if version(tables) == 6 and data['version'] not in (6, 9):
        raise ValueError('entry_price_retry_requires_format6')
    if version(tables) == 5 and data['version'] not in (5,6,9):
        raise ValueError('entry_policy_requires_format5')
    if version(tables) == 3 and data['version'] not in (3,4,5,6,9):
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
    for table, field in (('scanner_signals', 'technical_json'), ('scanner_orders', 'plan_json'),
                         ('scanner_trades', 'settings_json')):
        for row in tables[table]:
            discovery = json.loads(row.get(field) or '{}').get('entry_discovery')
            if discovery is not None:
                from entry_discovery import validate_attribution
                validate_attribution(discovery)
    for s in signals.values():
        technical = json.loads(s.get('technical_json') or '{}')
        discovery = technical.get('entry_discovery')
        if 'entry_strategy_execution' in technical:
            from entry_strategy_execution import validate_association
            validate_association(discovery, technical['entry_strategy_execution'])
        if discovery is not None:
            from entry_discovery import instant
            if instant(discovery['detected_at']) > instant(s['created_at']):
                raise ValueError('future_discovery_attribution')
        p = plan(s, 'technical_json')
        if is_single(p):
            validate(p, s['planned_entry'], s['original_stop'], s['action'])
            if [s['tp1'], s['tp2'], s['tp3']] != [p['active_target'], None, None]:
                raise ValueError('single_signal_levels_mismatch')
            if [s['tp1_pct'],s['tp2_pct'],s['tp3_pct']] != [1,0,0]:
                raise ValueError('single_signal_fractions_mismatch')
    for o in orders.values():
        import entry_strategy_execution
        entry_strategy_execution.validate_order(o, signal=signals[o['signal_id']])
        order_discovery = json.loads(o.get('plan_json') or '{}').get('entry_discovery')
        signal_discovery = json.loads(signals[o['signal_id']].get('technical_json') or '{}').get('entry_discovery')
        if order_discovery != signal_discovery:
            raise ValueError('order_discovery_attribution_mismatch')
        from entry_price_retry import validate_order
        validate_order(o)
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
        trade_execution = json.loads(t.get('settings_json') or '{}').get('entry_strategy_execution')
        order_execution = json.loads(orders[t['order_id']].get('plan_json') or '{}').get('entry_strategy_execution')
        if trade_execution != order_execution:
            raise ValueError('trade_strategy_execution_mismatch')
        if trade_execution is not None:
            from entry_strategy_execution import validate_fill as validate_strategy_fill
            validate_strategy_fill(trade_execution, t['entry_price'])
        saved_discovery = json.loads(t.get('settings_json') or '{}').get('entry_discovery')
        order_discovery = json.loads(orders[t['order_id']].get('plan_json') or '{}').get('entry_discovery')
        if saved_discovery != order_discovery:
            raise ValueError('trade_discovery_attribution_mismatch')
        p = plan(t, 'settings_json')
        op = plan(orders[t['order_id']], 'plan_json')
        saved_window = json.loads(t.get('settings_json') or '{}').get('entry_execution')
        order_window = json.loads(orders[t['order_id']].get('plan_json') or '{}').get('entry_execution')
        if saved_window != order_window:
            raise ValueError('trade_entry_window_mismatch')
        saved_retry = json.loads(t.get('settings_json') or '{}').get('entry_price_retry')
        order_retry = json.loads(orders[t['order_id']].get('plan_json') or '{}').get('entry_price_retry')
        if saved_retry != order_retry:
            raise ValueError('trade_entry_price_retry_mismatch')
        if saved_retry and (t['side'] not in ('long','BUY') or t['signal_id'] != orders[t['order_id']]['signal_id']):
            raise ValueError('trade_entry_price_retry_mismatch')
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
