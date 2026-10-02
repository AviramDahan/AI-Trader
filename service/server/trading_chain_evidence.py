"""Read-only same-chain evidence. No writes, providers, AI or Telegram calls."""
from datetime import datetime


def _time(value):
    return datetime.fromisoformat(str(value).replace('Z','+00:00'))


def chain_evidence(conn, cloud_started_at):
    """Caller supplies independently verified final cutover boundary, not wall-clock.

    Imported and incomplete chains never prove a new cloud lifecycle. This report
    proves linked persisted records only, not external broker/Telegram delivery.
    """
    cutoff=_time(cloud_started_at)
    rows=conn.execute('''SELECT t.id trade_id,t.signal_id,t.order_id,t.is_shadow,
        t.legacy_position_id,t.status,t.opened_at,t.last_bar_at,
        s.created_at signal_created_at,o.created_at order_created_at,o.status order_status,o.signal_id order_signal_id
        FROM scanner_trades t JOIN scanner_signals s ON s.id=t.signal_id
        LEFT JOIN scanner_orders o ON o.id=t.order_id ORDER BY t.id''').fetchall()
    result=[]
    for raw in rows:
        r=dict(raw)
        fills=[dict(f) for f in conn.execute('''SELECT id,order_id,fill_type,bar_at,created_at
            FROM scanner_fills WHERE trade_id=? ORDER BY bar_at,id''',(r['trade_id'],))]
        entries=[f for f in fills if f['fill_type']=='entry']
        exits=[f for f in fills if f['fill_type']!='entry']
        linked=bool(r['order_id'] and r['order_signal_id']==r['signal_id'] and r['order_status']=='filled'
                    and entries and all(f['order_id']==r['order_id'] for f in entries))
        times=[r['signal_created_at'],r['order_created_at'],r['opened_at']]+[f['created_at'] for f in entries]
        new=bool(linked and not r['legacy_position_id'] and all(v and _time(v)>=cutoff for v in times))
        monitored=bool(r['last_bar_at'] and _time(r['last_bar_at'])>_time(r['opened_at']))
        complete=new and not r['is_shadow'] and monitored and bool(exits) and r['status']=='closed'
        result.append(r|{'fills':fills,'linked_entry':linked,'origin':'NEW_CLOUD' if new else 'IMPORTED_OR_UNVERIFIED',
            'monitor_evidence':monitored,'closed_chain_evidence':complete})
    return {'cutover_boundary':cloud_started_at,'chains':result,
        'new_native_closed_chain':'OBSERVED_LINKED_RECORDS' if any(r['closed_chain_evidence'] for r in result) else 'WAITING_FOR_NATURAL_EVENT',
        'limitation':'Requires independent accounting reconciliation; not Telegram E2E or proof of profitability.'}
