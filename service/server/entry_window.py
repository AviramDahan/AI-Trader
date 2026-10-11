"""Immutable future order eligibility. Creation switch is NOT a reader switch."""
import os
from datetime import timedelta
from single_target_policy import instant

VERSION = 'next_complete_5m_v1'


def enabled():
    return os.getenv('STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED', 'false').lower() == 'true'


def build(created_at, valid_until):
    created, expires = instant(created_at), instant(valid_until)
    start = created.replace(second=0, microsecond=0)
    start -= timedelta(minutes=start.minute % 5)
    if start < created:
        start += timedelta(minutes=5)
    if start >= expires:
        raise ValueError('entry_window_empty')
    return dict(version=VERSION, created_at=created.isoformat(),
                entry_eligible_from=start.isoformat(), valid_until=expires.isoformat())


def eligible_from(order):
    import json
    contract = json.loads(order.get('plan_json') or '{}')
    window = contract.get('entry_execution')
    from single_breakout_policy import is_breakout
    from single_target_policy import is_single
    from short_policy import is_short
    p = contract.get('target_plan')
    if p and p.get('policy_version') and not (is_single(p) or is_short(p)):
        raise ValueError('unsupported_preserved_policy')
    if is_breakout(contract.get('target_plan')) and window is None:
        raise ValueError('breakout_entry_window_missing')
    if window is None:
        return instant(order['created_at'])  # Retained contracts keep old semantics.
    if order.get('purpose','entry') != 'entry' or order.get('side','buy') != 'buy':
        raise ValueError('unsupported_entry_window_order')
    if window != build(order['created_at'], order['valid_until']):
        raise ValueError('entry_window_contract_mismatch')
    return instant(window['entry_eligible_from'])
