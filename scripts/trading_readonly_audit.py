"""Run inside API container via stdin. Read-only, bounded, no network or initialization."""
import config,json,os,math
from short_policy import fill_cash_flow
from trading_chain_evidence import chain_evidence
from datetime import datetime,timezone
from database import get_db_connection
from scanner_engine import lifecycle_settings

with get_db_connection() as c:
    c.execute('SET TRANSACTION READ ONLY')
    c.execute("SET LOCAL statement_timeout='15s'")
    baseline=c.execute("SELECT value_json FROM scanner_settings WHERE key='active_snapshot_baseline'").fetchone()
    baseline=json.loads(baseline['value_json']) if baseline else None
    out={'at':datetime.now(timezone.utc).isoformat(),'build':os.getenv('BUILD_SHA'),
         'settings':lifecycle_settings(),'extended_exits_from':os.getenv('STOCK_SCANNER_EXTENDED_EXITS_FROM'),
         'baseline':baseline,'trades':[]}
    accounts=[dict(r) for r in c.execute('SELECT * FROM scanner_accounts')]
    trades=[dict(r) for r in c.execute('SELECT * FROM scanner_trades ORDER BY id')]
    for t in trades:
        fills=[dict(r) for r in c.execute('SELECT fill_type,price,quantity,fee,gross_pnl,bar_at,created_at FROM scanner_fills WHERE trade_id=? ORDER BY id',(t['id'],))]
        entries=[f for f in fills if f['fill_type']=='entry'];exits=[f for f in fills if f['fill_type']!='entry']
        out['trades'].append({k:t[k] for k in ('id','signal_id','order_id','ticker','status','is_shadow','legacy_position_id','opened_at','closed_at','last_bar_at')}|{
            'quantity_delta':sum(f['quantity'] for f in entries)-sum(f['quantity'] for f in exits)-t['remaining_quantity'],
            'fee_delta':sum(f['fee'] for f in fills)-t['fees'],
            'realized_delta':sum(f['gross_pnl'] for f in exits)-t['realized_pnl'],
            'fills':fills,'execution_settings':{k:v for k,v in json.loads(t['settings_json']).items() if k in ('strategy','slippage_bps','commission_per_share','minimum_commission','captured_at')}})
    native=[t for t in trades if not t['is_shadow'] and not t['legacy_position_id']]
    for a in accounts:
        rows=[t for t in native if t['agent_id']==a['agent_id']]
        fs=[f for t in out['trades'] if t['id'] in {r['id'] for r in rows} for f in t['fills']]
        by_id={t['id']:t for t in rows}
        flow=sum(fill_cash_flow(by_id[t['id']],f) for t in out['trades'] if t['id'] in by_id for f in t['fills'])
        out['account_reconciliation']={'cash_delta':a['cash']-(a['initial_cash']+(baseline or {}).get('cash_adjustment',0)+flow),
           'realized_vs_retained_trades_delta':a['realized_pnl']-sum(t['realized_pnl'] for t in rows),
           'fees_vs_retained_trades_delta':a['fees_paid']-sum(t['fees'] for t in rows)}
    out['orders']=[dict(r) for r in c.execute('SELECT id,signal_id,purpose,status,quantity,filled_quantity,created_at,valid_until,updated_at FROM scanner_orders ORDER BY id')]
    out['signals']=[dict(r) for r in c.execute('SELECT id,action,status,legacy_unverified,created_at FROM scanner_signals ORDER BY id')]
    out['duplicate_fills']=c.execute('SELECT count(*) n FROM (SELECT event_key FROM scanner_fills GROUP BY event_key HAVING count(*)>1) q').fetchone()['n']
    out['leases']=[dict(r) for r in c.execute("SELECT objid,count(*) n FROM pg_locks WHERE locktype='advisory' AND classid=719322 AND granted GROUP BY objid")]
    out['monitor']=dict(c.execute("SELECT status,last_success_at,detail FROM scanner_service_status WHERE component='monitor'").fetchone())
    # Optional explicit, independently verified cutover time; never infer from a
    # green health flag or from aggregated live_e2e_complete counters.
    if os.getenv('AUDIT_CLOUD_STARTED_AT'):
        out['chain_evidence']=chain_evidence(c,os.environ['AUDIT_CLOUD_STARTED_AT'])
    print(json.dumps(out,default=str))
