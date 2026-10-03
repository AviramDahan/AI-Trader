"""Conservative, versioned BUY/SINGLE contract. Pure: no prices/network/DB."""
import math
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

VERSION = 'single_target_v2'


def is_v2(plan):
    return isinstance(plan, dict) and plan.get('policy_version') == VERSION


def instant(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('source_timestamp_requires_timezone')
    return stamp.astimezone(timezone.utc)


def build(entry, atr, zones, data_as_of, decided_at):
    decision = instant(decided_at)
    # Yahoo daily source dates denote a completed US regular session, with the
    # same finalization buffer used by scanner_targets._completed_daily.
    source = (datetime.combine(datetime.fromisoformat(data_as_of).date(), time(16, 5),
                              ZoneInfo('America/New_York')).astimezone(timezone.utc)
              if len(data_as_of) == 10 else instant(data_as_of))
    if source > decision:
        raise ValueError('uncompleted_source_data')
    if not all(math.isfinite(v) and v > 0 for v in (entry, atr)):
        raise ValueError('invalid_structure_inputs')
    if any(not all(math.isfinite(float(z[k])) and float(z[k]) > 0 for k in ('low', 'high'))
           or z['low'] > z['high'] for z in zones):
        raise ValueError('invalid_price_zone')
    for z in zones:
        if not z.get('pivots'):
            raise ValueError('unconfirmed_price_zone')
        for pivot in z.get('pivots', []):
            confirmed = pivot.get('confirmed_at')
            if not confirmed or instant(confirmed) > source:
                raise ValueError('unconfirmed_price_zone')
    if any(z['low'] <= entry <= z['high'] for z in zones):
        raise ValueError('entry_inside_unresolved_price_zone')
    ahead = sorted((z for z in zones if z['low'] > entry), key=lambda z: z['low'])
    behind = [z for z in zones if z['high'] < entry]
    if not ahead:
        raise ValueError('no_forward_zone')
    if not behind:
        raise ValueError('no_structural_stop_anchor')
    anchor = max(behind, key=lambda z: z['high'])
    risk = max(entry - (anchor['low'] - .25 * atr), 1.5 * atr, .01 * entry)
    if risk > 4 * atr:
        raise ValueError('structural_stop_too_distant')
    stop, target = round(entry - risk, 2), round(ahead[0]['low'] - .15 * atr, 2)
    if not 0 < stop < entry < target or target >= ahead[0]['low']:
        raise ValueError('invalid_rounded_levels')
    # Check both the unrounded proposal and the actual stored levels.
    if (ahead[0]['low'] - .15 * atr - entry) / risk < 2 or (target - entry) / (entry - stop) < 2:
        raise ValueError('nearest_resistance_below_2r')
    plan = dict(policy_version=VERSION, method=VERSION, strategy='single', action='BUY',
                entry=entry, stop=stop, active_target=target, targets=[target], fractions=[1.0],
                rr=[(target-entry)/(entry-stop)], minimum_rr=2.0, atr=atr,
                zones=zones, stop_zone=anchor, resistance_zone=ahead[0],
                source_data_at=source.isoformat(), decided_at=decision.isoformat(),
                target_buffer_atr=.15, stop_buffer_atr=.25,
                shadow_comparison='unavailable_no_staged_contract')
    return plan


def validate(plan, entry=None, stop=None, action='BUY'):
    if not is_v2(plan) or action != 'BUY' or plan.get('strategy') != 'single':
        raise ValueError('unsupported_single_policy')
    rebuilt = build(plan['entry'], plan['atr'], plan['zones'], plan['source_data_at'], plan['decided_at'])
    if plan != rebuilt or (entry is not None and entry != plan['entry']) or (stop is not None and stop != plan['stop']):
        raise ValueError('single_policy_contract_mismatch')
    return rebuilt


def validate_fill(plan, price):
    validate(plan)
    if not math.isfinite(price) or not plan['stop'] < price < plan['active_target']:
        raise ValueError('fill_outside_plan')
    if any(z['low'] <= price <= z['high'] for z in plan['zones']):
        raise ValueError('fill_inside_unresolved_zone')
    # A gap below a previously overhead/intervening zone must not bypass it.
    nearest = min((z['low'] for z in plan['zones'] if z['low'] > price), default=None)
    if nearest != plan['resistance_zone']['low']:
        raise ValueError('fill_changes_nearest_resistance')
    risk = price - plan['stop']
    if risk < max(1.5 * plan['atr'], .01 * price) - .005 or risk > 4 * plan['atr']:
        raise ValueError('fill_stop_distance_invalid')
    if (plan['active_target'] - price) / risk < 2:
        raise ValueError('fill_rr_below_2')
    return (plan['active_target'] - price) / risk
