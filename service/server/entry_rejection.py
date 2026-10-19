"""Read-only presentation projection; never exports arbitrary exception text."""
import json

CODES = frozenset({
    'fill_rr_below_2', 'fill_outside_plan', 'fill_stop_distance_invalid',
    'fill_inside_unresolved_zone', 'fill_no_longer_above_completed_high',
    'fill_introduces_forward_resistance', 'fill_changes_nearest_resistance',
    'order_plan_mismatch', 'order_levels_mismatch', 'single_policy_contract_mismatch',
    'breakout_policy_contract_mismatch', 'unsupported_single_policy', 'unsupported_breakout_policy',
    'entry_price_retry_contract_invalid', 'unsupported_entry_price_retry',
    'strategy_fill_below_support', 'strategy_fill_above_chase',
    'strategy_fill_outside_all_frozen_branches',
    'entry_strategy_execution_contract_invalid', 'unsupported_entry_strategy_execution',
})


def reason_code(value):
    return value if isinstance(value, str) and value in CODES else None


def order_reason(order):
    if order.get('purpose') != 'entry' or order.get('status') != 'invalid':
        return None
    try:
        contract = json.loads(order.get('plan_json') or '{}')
        return reason_code(contract.get('entry_rejection_reason')) if isinstance(contract, dict) else None
    except (TypeError, ValueError):
        return None
