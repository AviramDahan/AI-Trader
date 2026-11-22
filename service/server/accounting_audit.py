"""Pure, amount-free evidence summaries for retained paper accounting.

An active-only import preserves cumulative account totals while omitting closed
trades. Its cash-only opening baseline cannot prove cumulative fees or P&L.
This module never derives an opening adjustment from a current discrepancy.
"""
import hashlib
import json
import math

from short_policy import fill_cash_flow


def _number(value):
    if isinstance(value, bool):
        raise ValueError('invalid_accounting_number')
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('invalid_accounting_number')
    return number


def _result(status, reason=None):
    return dict(status=status, **({'reason': reason} if reason else {}))


def _compare(actual, expected):
    try:
        matched = math.isclose(_number(actual), _number(expected), rel_tol=0., abs_tol=1e-6)
    except (TypeError, ValueError, OverflowError):
        return _result('FAIL', 'NONFINITE_OR_INVALID_ACCOUNTING_DATA')
    return _result('PASS') if matched else _result('FAIL', 'RETAINED_ACCOUNTING_MISMATCH')


def _combined(results):
    states = {r['status'] for r in results}
    return 'FAIL' if 'FAIL' in states else 'NOT_VERIFIED' if 'NOT_VERIFIED' in states else 'PASS'


def _snapshot_opening(snapshot, baseline, account):
    """Authenticate original input against the pinned import, derive in memory."""
    if snapshot is None:
        return None, 'OPENING_HISTORY_GAP'
    try:
        if not isinstance(snapshot, dict) or not isinstance(baseline, dict):
            raise ValueError()
        snapshot_id = snapshot['snapshot_id']
        raw = json.dumps({k: v for k, v in snapshot.items() if k != 'snapshot_id'},
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if not isinstance(snapshot_id, str) or hashlib.sha256(raw).hexdigest() != snapshot_id:
            return None, 'OPENING_SNAPSHOT_CHECKSUM_INVALID'
        if snapshot_id != baseline.get('snapshot_id'):
            return None, 'OPENING_SNAPSHOT_ID_MISMATCH'
        if type(snapshot.get('version')) is not int or snapshot['version'] not in range(1, 11):
            raise ValueError()
        tables = snapshot['tables']
        original_accounts = tables['scanner_accounts']
        if (len(original_accounts) != 1 or snapshot['primary_agent_id'] != account['agent_id']
                or original_accounts[0]['agent_id'] != account['agent_id']):
            return None, 'OPENING_SNAPSHOT_ACCOUNT_MISMATCH'
        original = original_accounts[0]
        native = [t for t in tables['scanner_trades'] if not t.get('is_shadow')
                  and not t.get('legacy_position_id') and t['agent_id'] == account['agent_id']]
        by_id = {t['id']: t for t in native}
        if len(by_id) != len(native):
            raise ValueError()
        flow = sum(fill_cash_flow(by_id[f['trade_id']], f) for f in tables['scanner_fills']
                   if f['trade_id'] in by_id and f['fill_type'] in {'entry', 'tp', 'stop', 'sell'})
        cash = _number(original['cash']) - _number(original['initial_cash']) - flow
        if not math.isclose(cash, _number(baseline['cash_adjustment']), rel_tol=0., abs_tol=1e-6):
            return None, 'OPENING_SNAPSHOT_CASH_BASELINE_MISMATCH'
        return dict(cash_adjustment=cash,
                    fees_paid_adjustment=_number(original['fees_paid']) - sum(_number(t['fees']) for t in native),
                    realized_pnl_adjustment=_number(original['realized_pnl'])
                    - sum(_number(t['realized_pnl']) for t in native)), None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, 'OPENING_SNAPSHOT_INVALID'


def _opening(baseline, field, proven=None, proof_reason=None):
    """No claimed fields or current residual may stand in for original proof."""
    if baseline is None:
        return 0., None
    if not isinstance(baseline, dict):
        return None, 'OPENING_BASELINE_INVALID'
    if field == 'cash_adjustment':
        try:
            return _number(baseline[field]), None
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, 'OPENING_BASELINE_INVALID'
    if proven is not None:
        return proven[field], None
    return None, proof_reason or 'OPENING_HISTORY_GAP'


def reconcile(accounts, trades, fills_by_trade, *, baseline=None, complete=True, opening_snapshot=None):
    """Summarize caller-supplied consistent, bounded records without mutating them.

    ``complete`` means the input was not clipped. Database snapshot/isolation
    verification belongs to the caller. Shadow and legacy wallets are separate
    from scanner_accounts and are excluded explicitly, never silently added.
    """
    out = dict(status='NOT_VERIFIED', scope='NATIVE_PRIMARY_RETAINED_ACCOUNTING',
               accounts=[], native_fills=dict(status='NOT_VERIFIED', checked=0),
               excluded=dict(shadow_trades=sum(bool(t.get('is_shadow')) for t in trades),
                             legacy_trades=sum(bool(t.get('legacy_position_id')) and not t.get('is_shadow')
                                               for t in trades)),
               historical_performance='NOT_ASSESSED', natural_trading_e2e='NOT_VERIFIED')
    if not complete:
        out['reason'] = 'INPUT_SCOPE_TRUNCATED'
        return out
    trade_ids = [t['id'] for t in trades]
    account_ids = [a['agent_id'] for a in accounts]
    if (len(set(trade_ids)) != len(trade_ids) or len(set(account_ids)) != len(account_ids)
            or any(trade_id not in set(trade_ids) for trade_id in fills_by_trade)):
        out.update(status='FAIL', reason='DUPLICATE_OR_UNOWNED_INPUT_RECORDS')
        return out
    native = [t for t in trades if not t.get('is_shadow') and not t.get('legacy_position_id')]
    trade_checks = []
    for trade in native:
        fills = fills_by_trade.get(trade['id'], [])
        try:
            entries = [f for f in fills if f['fill_type'] == 'entry']
            exits = [f for f in fills if f['fill_type'] in {'tp', 'stop', 'sell'}]
            if len(entries) + len(exits) != len(fills) or not entries:
                raise ValueError('missing_or_unsupported_fill')
            if trade.get('side') not in {'long', 'BUY', 'short'}:
                raise ValueError('unsupported_side')
            # Validate every value used for cash/quantity reconciliation, even
            # fields which happen to cancel numerically in an aggregate.
            for fill in fills:
                if _number(fill['quantity']) <= 0 or _number(fill['price']) <= 0 or _number(fill['fee']) < 0:
                    raise ValueError('invalid_fill')
                _number(fill['gross_pnl'])
            if _number(trade['original_quantity']) <= 0 or _number(trade['remaining_quantity']) < 0:
                raise ValueError('invalid_trade')
            entry_quantity = sum(_number(f['quantity']) for f in entries)
            exit_quantity = sum(_number(f['quantity']) for f in exits)
            checks = [_compare(trade['original_quantity'], entry_quantity),
                      _compare(trade['remaining_quantity'], entry_quantity - exit_quantity),
                      _compare(trade['fees'], sum(_number(f['fee']) for f in fills)),
                      _compare(trade['realized_pnl'], sum(_number(f['gross_pnl']) for f in exits))]
            trade_checks.append(_result(_combined(checks)))
        except (KeyError, TypeError, ValueError, OverflowError):
            trade_checks.append(_result('FAIL', 'INVALID_OR_INCOMPLETE_NATIVE_FILLS'))
    out['native_fills'] = dict(status=_combined(trade_checks), checked=len(native),
                               failed=sum(r['status'] == 'FAIL' for r in trade_checks))
    account_checks = []
    for account in accounts:
        own = [t for t in native if t['agent_id'] == account['agent_id']]
        summary = dict(native_trades=len(own))
        proven, proof_reason = _snapshot_opening(opening_snapshot, baseline, account)
        summary['opening_evidence'] = ('CHECKSUM_AND_IMPORT_ID_VERIFIED' if proven is not None
                                       else 'NOT_VERIFIED' if baseline is not None else 'NO_IMPORT_BASELINE')
        for key, field, retained in (
                ('cash', 'cash_adjustment', None),
                ('fees', 'fees_paid_adjustment', 'fees'),
                ('realized', 'realized_pnl_adjustment', 'realized_pnl')):
            opening, reason = _opening(baseline, field, proven, proof_reason)
            if baseline is not None and len(accounts) != 1:
                reason = 'OPENING_BASELINE_ACCOUNT_AMBIGUOUS'
            if reason:
                summary[key] = _result('NOT_VERIFIED', reason)
                continue
            try:
                if key == 'cash':
                    flow = sum(fill_cash_flow(t, f) for t in own for f in fills_by_trade.get(t['id'], []))
                    expected = _number(account['initial_cash']) + opening + flow
                    actual = account['cash']
                else:
                    expected = opening + sum(_number(t[retained]) for t in own)
                    actual = account['fees_paid' if key == 'fees' else 'realized_pnl']
                summary[key] = _compare(actual, expected)
            except (KeyError, TypeError, ValueError, OverflowError):
                summary[key] = _result('FAIL', 'NONFINITE_OR_INVALID_ACCOUNTING_DATA')
        out['accounts'].append(summary)
        account_checks.extend(summary[k] for k in ('cash', 'fees', 'realized'))
    owned = {a['agent_id'] for a in accounts}
    orphan_count = sum(t['agent_id'] not in owned for t in native)
    if orphan_count:
        out['unowned_native_trades'] = orphan_count
        account_checks.append(_result('FAIL', 'NATIVE_ACCOUNT_MISSING'))
    if not accounts:
        account_checks.append(_result('NOT_VERIFIED', 'NO_ACCOUNT_RECORDS'))
    out['status'] = _combined([out['native_fills'], *account_checks])
    return out
