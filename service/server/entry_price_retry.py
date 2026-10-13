"""Frozen, opt-in BUY/SINGLE price retry. Never relaxes a fill gate or level."""
import json
import math
import os

from entry_window import build as window_build, instant, eligible_from
from single_target_policy import is_single, validate_single, validate_single_fill

VERSION = 'single_entry_price_retry_v1'
PRICE_REASONS = frozenset({
    'fill_rr_below_2', 'fill_outside_plan', 'fill_stop_distance_invalid',
    'fill_inside_unresolved_zone', 'fill_no_longer_above_completed_high',
    'fill_introduces_forward_resistance', 'fill_changes_nearest_resistance',
})


def enabled():
    return os.getenv('STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED', 'false').lower() == 'true'


def build(created_at, valid_until, plan, window):
    if not is_single(plan) or plan.get('action') != 'BUY':
        raise ValueError('entry_price_retry_contract_invalid')
    validate_single(plan)
    if window != window_build(created_at, valid_until):
        raise ValueError('entry_price_retry_contract_invalid')
    return dict(version=VERSION, created_at=instant(created_at).isoformat(),
                valid_until=instant(valid_until).isoformat(), target_policy=plan['policy_version'])


def validate_order(order, contract=None):
    """Stored contracts work with creation OFF; absence retains legacy behavior."""
    try:
        contract = json.loads(order.get('plan_json') or '{}') if contract is None else contract
        if not isinstance(contract, dict):
            raise ValueError('entry_price_retry_contract_invalid')
        if 'entry_price_retry' not in contract:
            if 'last_entry_price_block' in contract:
                raise ValueError('entry_price_retry_contract_invalid')
            return False
        saved = contract['entry_price_retry']
        if not isinstance(saved, dict) or saved.get('version') != VERSION:
            raise ValueError('unsupported_entry_price_retry')
        plan = contract.get('target_plan')
        settings = contract.get('execution_settings')
        if (order.get('purpose') != 'entry' or order.get('side') != 'buy' or
                order.get('order_type') != 'limit' or
                not isinstance(settings, dict) or settings.get('active_strategy') != 'single' or
                saved != build(order['created_at'], order['valid_until'], plan, contract.get('entry_execution')) or
                order['limit_price'] != plan['entry']):
            raise ValueError('entry_price_retry_contract_invalid')
        observation = contract.get('last_entry_price_block')
        if observation is not None:
            validate_observation(order, contract, observation)
        return True
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('entry_price_retry_contract_invalid') from None


def validate_observation(order, contract, observation):
    """Evidence of one actual rejected-price attempt, not a fill or instruction."""
    from datetime import timedelta
    if (not isinstance(observation, dict) or
            set(observation) != {'reason', 'price', 'bar_at', 'observed_at'} or
            observation['reason'] not in PRICE_REASONS or
            isinstance(observation['price'], bool) or
            not isinstance(observation['price'], (int, float)) or
            not math.isfinite(observation['price']) or observation['price'] <= 0 or
            observation['price'] > order['limit_price']):
        raise ValueError('entry_price_retry_contract_invalid')
    bar, observed = instant(observation['bar_at']), instant(observation['observed_at'])
    if (bar.second or bar.microsecond or bar.minute % 5 or bar < eligible_from(order) or
            bar + timedelta(minutes=5) > instant(order['valid_until']) or
            observed < bar + timedelta(minutes=5) or observed > instant(order['updated_at'])):
        raise ValueError('entry_price_retry_contract_invalid')
    try:
        validate_single_fill(contract['target_plan'], observation['price'])
    except ValueError as exc:
        if str(exc) == observation['reason']:
            return
    raise ValueError('entry_price_retry_contract_invalid')


def observe(order, contract, price, bar_at, observed_at, reason):
    if not validate_order(order, contract):
        raise ValueError('entry_price_retry_contract_invalid')
    observation = dict(reason=reason, price=price, bar_at=instant(bar_at).isoformat(),
                       observed_at=instant(observed_at).isoformat())
    validate_observation(dict(order, updated_at=observed_at), contract, observation)
    prior = contract.get('last_entry_price_block')
    if prior and instant(prior['bar_at']) >= instant(observation['bar_at']):
        raise ValueError('entry_price_retry_contract_invalid')
    return dict(contract, last_entry_price_block=observation)


def public_wait(order):
    """Allowlist a current wait only; filled/terminal/legacy records are not waits."""
    if order.get('status') != 'pending':
        return None
    try:
        contract = json.loads(order.get('plan_json') or '{}')
        if not validate_order(order, contract):
            return None
        observation = contract.get('last_entry_price_block')
        return dict(observation, version=VERSION) if observation else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
