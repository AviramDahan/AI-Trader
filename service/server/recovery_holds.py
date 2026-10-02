"""Snapshot contract for blocked orders, not an order-resolution mechanism."""
import math
from datetime import datetime


def coverage(orders):
    held=[o for o in orders if o['status']=='recovery_uncertain']
    # Same predicate and formula as scanner_engine.record_signal reservations.
    return {'scope':'recovery_uncertain_only','order_ids':sorted(o['id'] for o in held),
            'entry_reserved_notional':sum(o['limit_price']*o['quantity'] for o in held if o['purpose']=='entry')}


def validate(data):
    tables=data['tables']
    orders=tables['scanner_orders']
    signals={s['id']:s for s in tables['scanner_signals']}
    agents={a['id'] for a in tables['agents']}
    accounts={a['agent_id'] for a in tables['scanner_accounts']}
    held=[o for o in orders if o['status']=='recovery_uncertain']
    if data.get('version')==1:
        if held: raise ValueError('legacy_snapshot_cannot_cover_holds')
        return  # Legacy coverage UNKNOWN, never proof that source had no holds.
    for table in ('scanner_orders','scanner_signals','agents','scanner_accounts'):
        ids=[r['id'] for r in tables[table]]
        if len(ids)!=len(set(ids)): raise ValueError('duplicate_recovery_identity')
    for o in orders:
        if o['status'] not in {'filled','expired','cancelled','canceled','invalid','risk_rejected','recovery_uncertain'}:
            raise ValueError('unsupported_recovery_order_status')
        s=signals.get(o['signal_id'])
        if not s or s['agent_id'] not in agents or s['agent_id'] not in accounts:
            raise ValueError('missing_recovery_order_parent')
        if o['status']!='recovery_uncertain': continue
        if s['agent_id']!=data['primary_agent_id'] or s['status']!='RECOVERY_UNCERTAIN':
            raise ValueError('invalid_recovery_hold_identity')
        if s.get('external_signal_id') is not None and not any(r['id']==s['external_signal_id'] for r in tables['signals']):
            raise ValueError('missing_recovery_external_signal_parent')
        if (o['purpose'],o['side']) not in {('entry','buy'),('close_long','sell')} or o['order_type']!='limit':
            raise ValueError('unsupported_recovery_hold_type')
        if s['action']!=('BUY' if o['purpose']=='entry' else 'SELL'):
            raise ValueError('recovery_hold_action_mismatch')
        if any(not isinstance(o[k],(int,float)) or not math.isfinite(o[k]) or o[k]<=0 for k in ('limit_price','quantity')):
            raise ValueError('invalid_recovery_hold_numbers')
        if o['filled_quantity']!=0 or o.get('average_fill_price') not in (None,0):
            raise ValueError('recovery_hold_has_execution')
        if any(f.get('order_id')==o['id'] for f in tables['scanner_fills']):
            raise ValueError('recovery_hold_has_fill')
        if o['purpose']=='entry' and any(t.get('order_id')==o['id'] for t in tables['scanner_trades']):
            raise ValueError('recovery_entry_hold_has_trade')
        # A blocked close may outlive its position (natural protective stop/TP).
        # Keep the hold for manual resolution; never recreate the closed position.
        times=[datetime.fromisoformat(str(o[k]).replace('Z','+00:00')) for k in ('created_at','valid_until','updated_at')]
        if any(t.tzinfo is None for t in times) or times[1]<=times[0]:
            raise ValueError('invalid_recovery_hold_times')
    expected=coverage(orders)
    actual=data.get('hold_coverage')
    if not actual or actual.get('scope')!=expected['scope'] or actual.get('order_ids')!=expected['order_ids']:
        raise ValueError('recovery_hold_coverage_mismatch')
    amount=actual.get('entry_reserved_notional')
    if not isinstance(amount,(int,float)) or not math.isfinite(amount) or not math.isclose(amount,expected['entry_reserved_notional'],rel_tol=1e-12,abs_tol=1e-8):
        raise ValueError('recovery_hold_reservation_mismatch')
