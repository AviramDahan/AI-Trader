"""Bounded BUY/SINGLE fallback. Pure, point-in-time, never a resistance bypass."""
import copy
import math
import os
from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_CEILING
from zoneinfo import ZoneInfo
import single_target_policy as v2

VERSION = 'single_breakout_v1'


def is_breakout(plan):
    return isinstance(plan, dict) and plan.get('policy_version') == VERSION


def enabled():
    from entry_window import enabled as window_enabled
    from single_target_activation import enabled as v2_enabled
    return (v2_enabled() and window_enabled() and
            os.getenv('STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED', 'false').lower() == 'true')


def build(entry, atr, zones, data_as_of, decided_at, completed_high):
    # Reuse the exact existing source/pivot/inside-zone checks. Only the precise
    # no-forward-zone failure can enter this path; no known resistance is skipped.
    try:
        v2.build(entry, atr, zones, data_as_of, decided_at)
    except ValueError as exc:
        if str(exc) != 'no_forward_zone':
            raise
    else:
        raise ValueError('breakout_requires_no_forward_zone')
    if not isinstance(completed_high, (int, float)) or not math.isfinite(completed_high) or completed_high <= 0:
        raise ValueError('completed_high_unavailable')
    if entry <= completed_high:
        raise ValueError('entry_not_above_completed_high')
    behind = [z for z in zones if z['high'] < entry]
    if not behind:
        raise ValueError('no_structural_stop_anchor')
    anchor = max(behind, key=lambda z: z['high'])
    risk = max(entry - (anchor['low'] - .25 * atr), 1.5 * atr, .01 * entry)
    if risk > 4 * atr:
        raise ValueError('structural_stop_too_distant')
    stop = round(entry - risk, 2)
    if not 0 < stop < entry:
        raise ValueError('invalid_rounded_levels')
    # Decimal ceiling ensures the stored cent target is not below 2R.
    price, saved_stop = Decimal(str(entry)), Decimal(str(stop))
    target = float((price + 2 * (price - saved_stop)).quantize(Decimal('.01'), rounding=ROUND_CEILING))
    source = (datetime.combine(datetime.fromisoformat(data_as_of).date(), time(16, 5),
                              ZoneInfo('America/New_York')).astimezone(timezone.utc)
              if len(data_as_of) == 10 else v2.instant(data_as_of))
    return dict(policy_version=VERSION, method=VERSION, strategy='single', action='BUY',
                entry=entry, stop=stop, active_target=target, targets=[target], fractions=[1.0],
                rr=[(target-entry)/(entry-stop)], minimum_rr=2.0, atr=atr,
                zones=copy.deepcopy(zones), stop_zone=copy.deepcopy(anchor),
                source_data_at=source.isoformat(), decided_at=v2.instant(decided_at).isoformat(),
                completed_high=completed_high, completed_high_sessions=20,
                target_kind='projected_2r_not_confirmed_resistance', stop_buffer_atr=.25,
                shadow_comparison='unavailable_no_staged_contract')


def validate(plan, entry=None, stop=None, action='BUY'):
    if not is_breakout(plan) or action != 'BUY' or plan.get('strategy') != 'single':
        raise ValueError('unsupported_breakout_policy')
    rebuilt = build(plan['entry'], plan['atr'], plan['zones'], plan['source_data_at'],
                    plan['decided_at'], plan['completed_high'])
    if plan != rebuilt or (entry is not None and entry != plan['entry']) or (stop is not None and stop != plan['stop']):
        raise ValueError('breakout_policy_contract_mismatch')
    return rebuilt


def validate_fill(plan, price):
    validate(plan)
    if not math.isfinite(price) or not plan['stop'] < price < plan['active_target']:
        raise ValueError('fill_outside_plan')
    if price <= plan['completed_high']:
        raise ValueError('fill_no_longer_above_completed_high')
    if any(z['low'] <= price <= z['high'] for z in plan['zones']):
        raise ValueError('fill_inside_unresolved_zone')
    if any(z['low'] > price for z in plan['zones']):
        raise ValueError('fill_introduces_forward_resistance')
    risk = price - plan['stop']
    if risk < max(1.5 * plan['atr'], .01 * price) - .005 or risk > 4 * plan['atr']:
        raise ValueError('fill_stop_distance_invalid')
    if Decimal(str(plan['active_target'])) - Decimal(str(price)) < 2 * (Decimal(str(price)) - Decimal(str(plan['stop']))):
        raise ValueError('fill_rr_below_2')
    return (plan['active_target'] - price) / risk
