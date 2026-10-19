"""Versioned frozen fill guards for NEW independent BUY admissions only.

No STOP orders, invented prices, intrabar inference, AI, sizing or exit changes.
Absent contract keeps the prior audit-only/BASELINE behavior. Stored readers do
not consult flags or the build's creation capability. Independent branches are OR.
"""
from __future__ import annotations

import copy
from datetime import timedelta
import hashlib
import json
import math

from entry_window import build as build_window, instant, eligible_from

VERSION = 'independent_entry_execution_v1'
KEY = 'entry_strategy_execution'
OBSERVATION_KEY = 'last_strategy_entry_block'
PRICE_REASONS = frozenset({'strategy_fill_below_support', 'strategy_fill_above_chase',
                           'strategy_fill_outside_all_frozen_branches'})
INVALID = 'entry_strategy_execution_contract_invalid'
UNSUPPORTED = 'unsupported_entry_strategy_execution'
MAX_BYTES = 8192


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def branches_from_discovery(discovery, admission_ids=None, *, allow_component=False):
    """Pure rule projection, also usable for non-executable interval research.

    This does NOT assert admission or pick a price. Production build additionally
    requires an actual fresh quote and the candidate's original detector trigger.
    """
    from entry_discovery import validate_attribution, BASELINE
    package = validate_attribution(discovery, allow_component=allow_component)
    if BASELINE in package['strategy_ids']:
        return []
    requested = package['strategy_ids'] if admission_ids is None else admission_ids
    if (not isinstance(requested, (list, tuple)) or not requested or
            len(requested) != len(set(requested)) or set(requested) - set(package['strategy_ids'])):
        raise ValueError(INVALID)
    branches = []
    for record in package['detections']:
        strategy_id = record['strategy_id']
        if strategy_id not in requested:
            continue
        trigger = record['trigger']
        pullback = strategy_id == 'TREND_PULLBACK_RECLAIM'
        support = record.get('features', {}).get('ema20') if pullback else trigger.get('level')
        ceiling = trigger.get('max_entry_price')
        ids = record.get('evidence_ids')
        if (not _finite(support) or support <= 0 or not _finite(ceiling) or ceiling <= support or
                not isinstance(ids, list) or not 1 <= len(ids) <= 16 or
                any(not isinstance(value, str) or len(value) != 64 or
                    any(c not in '0123456789abcdef' for c in value) for value in ids)):
            raise ValueError(INVALID)
        branches.append(dict(strategy_id=strategy_id, detector_version=record['version'],
            sourcehash=record['sourcehash'], evidence_ids=copy.deepcopy(ids),
            support=float(support), ceiling=float(ceiling),
            rule='CONFIRMED_RECLAIM_THEN_ABOVE_EMA20' if pullback else 'STRICTLY_ABOVE_CONFIRMED_PIVOT',
            confirmed_at=instant(trigger['confirmed_at']).isoformat()))
    if not branches:
        raise ValueError(INVALID)
    return branches


def _build(discovery, *, created_at, valid_until, limit_price, quote_at,
           admission_ids=None, entry_execution=None):
    from entry_discovery import validate_attribution, BASELINE
    from entry_strategies import validate_trigger
    package = validate_attribution(discovery)
    if BASELINE in package['strategy_ids']:
        return None
    created, expires, quote = instant(created_at), instant(valid_until), instant(quote_at)
    if (not _finite(limit_price) or limit_price <= 0 or
            instant(package['detected_at']) > created):
        raise ValueError(INVALID)
    window = build_window(created, expires)
    if entry_execution is not None and entry_execution != window:
        raise ValueError(INVALID)
    ids = []
    for record in package['detections']:
        if admission_ids is not None and record['strategy_id'] not in admission_ids:
            continue
        try:
            validate_trigger(record, limit_price, quote, created)
        except ValueError:
            continue
        ids.append(record['strategy_id'])
    if not ids:
        raise ValueError('entry_strategy_no_valid_admission_branch')
    saved = dict(version=VERSION, created_at=created.isoformat(), valid_until=expires.isoformat(),
        quote_at=quote.isoformat(), limit_price=float(limit_price),
        audit_digest=_digest(package), admitted_ids=ids,
        branches=branches_from_discovery(package, ids))
    if len(_canonical(saved)) > MAX_BYTES:
        raise ValueError(INVALID)
    return saved


def build(discovery, *, created_at, valid_until, limit_price, quote_at,
          allowed_ids=None, entry_execution=None):
    """Creation only. A bridge binary cannot originate this new execution policy."""
    from entry_discovery import validate_attribution, BASELINE
    package = validate_attribution(discovery)
    if BASELINE in package['strategy_ids']:
        return None
    from entry_discovery_capabilities import creation_allowed
    if not creation_allowed():
        raise ValueError('new_entry_discovery_disabled_in_bridge')
    return _build(package, created_at=created_at, valid_until=valid_until,
        limit_price=limit_price, quote_at=quote_at, admission_ids=allowed_ids,
        entry_execution=entry_execution)


def validate_association(discovery, saved):
    """Bind the executable branches to the exact saved immutable audit package."""
    from entry_discovery import validate_attribution, BASELINE
    try:
        package = validate_attribution(discovery)
        if BASELINE in package['strategy_ids'] or not isinstance(saved, dict):
            raise ValueError(INVALID)
        if saved.get('version') != VERSION:
            raise ValueError(UNSUPPORTED)
        if set(saved) != {'version', 'created_at', 'valid_until', 'quote_at', 'limit_price',
                          'audit_digest', 'admitted_ids', 'branches'}:
            raise ValueError(INVALID)
        expected = _build(package, created_at=saved['created_at'], valid_until=saved['valid_until'],
            limit_price=saved['limit_price'], quote_at=saved['quote_at'], admission_ids=saved['admitted_ids'])
        if saved != expected or len(_canonical(saved)) > MAX_BYTES:
            raise ValueError(INVALID)
        return json.loads(_canonical(saved))
    except (KeyError, TypeError, OverflowError, json.JSONDecodeError):
        raise ValueError(INVALID) from None
    except ValueError as exc:
        if str(exc) == UNSUPPORTED:
            raise
        raise ValueError(INVALID) from None


def validate_order(order, contract=None, *, signal=None):
    """Absent is retained semantics. Present malformed/unknown contracts fail closed."""
    try:
        contract = json.loads(order.get('plan_json') or '{}') if contract is None else contract
        if not isinstance(contract, dict):
            raise ValueError(INVALID)
        if KEY not in contract:
            if OBSERVATION_KEY in contract:
                raise ValueError(INVALID)
            if signal is not None and KEY in json.loads(signal.get('technical_json') or '{}'):
                raise ValueError(INVALID)
            return False
        saved = validate_association(contract.get('entry_discovery'), contract[KEY])
        if (order.get('purpose') != 'entry' or order.get('side') != 'buy' or
                order.get('order_type') != 'limit' or not isinstance(contract.get('target_plan'), dict) or
                not isinstance(contract.get('execution_settings'), dict) or
                contract['execution_settings'].get('active_strategy') not in {'single', 'staged'} or
                saved['limit_price'] != order['limit_price'] or
                saved['created_at'] != instant(order['created_at']).isoformat() or
                saved['valid_until'] != instant(order['valid_until']).isoformat() or
                contract.get('entry_execution') != build_window(order['created_at'], order['valid_until'])):
            raise ValueError(INVALID)
        plan = contract['target_plan']
        settings = contract['execution_settings']
        if (settings.get('entry_order_type') != 'limit' or
                any(not _finite(settings.get(key)) or not 0 <= settings[key] <= maximum
                    for key, maximum in (('slippage_bps', 100), ('commission_per_share', 10), ('minimum_commission', 100)))):
            raise ValueError(INVALID)
        if plan.get('entry') != order['limit_price']:
            raise ValueError(INVALID)
        if signal is not None:
            technical = json.loads(signal.get('technical_json') or '{}')
            if (technical.get('entry_discovery') != contract['entry_discovery'] or
                    technical.get(KEY) != saved or
                    technical.get('target_plan') != plan or signal.get('action') != 'BUY' or
                    signal.get('planned_entry') != order['limit_price'] or
                    instant(signal['created_at']) != instant(order['created_at']) or
                    instant(signal['valid_until']) != instant(order['valid_until']) or
                    signal.get('original_stop') != plan.get('stop')):
                raise ValueError(INVALID)
            from scanner_targets import validate_plan
            validate_plan(plan, signal['planned_entry'], signal['original_stop'], 'BUY')
            if [signal.get(f'tp{i}') for i in (1, 2, 3)] != (plan['targets'] + [None, None])[:3]:
                raise ValueError(INVALID)
            if [signal.get(f'tp{i}_pct') for i in (1, 2, 3)] != (plan['fractions'] + [0, 0])[:3]:
                raise ValueError(INVALID)
        if OBSERVATION_KEY in contract:
            validate_observation(order, contract, contract[OBSERVATION_KEY], checked=True)
        return True
    except (KeyError, TypeError, OverflowError, json.JSONDecodeError):
        raise ValueError(INVALID) from None
    except ValueError as exc:
        if str(exc) == UNSUPPORTED:
            raise
        raise ValueError(INVALID) from None


def validate_fill(saved, price):
    """Actual price vs frozen OR rules only; the original target plan still gates."""
    if not isinstance(saved, dict) or saved.get('version') != VERSION:
        raise ValueError(UNSUPPORTED)
    if not _finite(price) or price <= 0 or not isinstance(saved.get('branches'), list) or not saved['branches']:
        raise ValueError(INVALID)
    matched, below, above = [], [], []
    for branch in saved['branches']:
        if (not isinstance(branch, dict) or not all(_finite(branch.get(k)) and branch[k] > 0
                for k in ('support', 'ceiling')) or branch['ceiling'] <= branch['support']):
            raise ValueError(INVALID)
        below.append(price <= branch['support'])
        above.append(price > branch['ceiling'])
        if not below[-1] and not above[-1]:
            matched.append(branch['strategy_id'])
    if matched:
        return matched
    if all(below):
        raise ValueError('strategy_fill_below_support')
    if all(above):
        raise ValueError('strategy_fill_above_chase')
    raise ValueError('strategy_fill_outside_all_frozen_branches')


def validate_observation(order, contract, observation, *, checked=False):
    if not checked and not validate_order(order, {k: v for k, v in contract.items() if k != OBSERVATION_KEY}):
        raise ValueError(INVALID)
    if (not isinstance(observation, dict) or set(observation) != {'reason', 'price', 'bar_at', 'observed_at'} or
            observation['reason'] not in PRICE_REASONS or not _finite(observation['price']) or
            observation['price'] <= 0 or observation['price'] > order['limit_price']):
        raise ValueError(INVALID)
    bar, observed = instant(observation['bar_at']), instant(observation['observed_at'])
    if (bar.second or bar.microsecond or bar.minute % 5 or bar < eligible_from(order) or
            bar + timedelta(minutes=5) > instant(order['valid_until']) or
            observed < bar + timedelta(minutes=5) or observed > instant(order['updated_at'])):
        raise ValueError(INVALID)
    try:
        validate_fill(contract[KEY], observation['price'])
    except ValueError as exc:
        if str(exc) == observation['reason']:
            return
    raise ValueError(INVALID)


def observe(order, contract, price, bar_at, observed_at, reason):
    if not validate_order(order, contract):
        raise ValueError(INVALID)
    observation = dict(reason=reason, price=price, bar_at=instant(bar_at).isoformat(),
                       observed_at=instant(observed_at).isoformat())
    validate_observation(dict(order, updated_at=observed_at), contract, observation, checked=True)
    prior = contract.get(OBSERVATION_KEY)
    if prior and instant(prior['bar_at']) >= instant(observation['bar_at']):
        raise ValueError(INVALID)
    return dict(contract, **{OBSERVATION_KEY: observation})


def public_wait(order):
    if order.get('status') != 'pending':
        return None
    try:
        contract = json.loads(order.get('plan_json') or '{}')
        if validate_order(order, contract) and contract.get(OBSERVATION_KEY):
            return dict(contract[OBSERVATION_KEY], version=VERSION)
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return None
