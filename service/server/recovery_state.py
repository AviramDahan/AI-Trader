"""Secret-free, transactionally consistent PostgreSQL ACTIVE-state recovery.

Not a database dump. Authentication is re-provisioned at restore, never exported.
News/history/outbox/pending orders are intentionally excluded.
"""
import copy
import gzip
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import active_snapshot as active

AGENT_FIELDS = {'id','name','cash','deposited','created_at','updated_at'}
CONFIG_FIELDS = {'active_strategy','entry_order_type','signal_validity_hours','paper_notional',
    'max_symbol_exposure','max_total_exposure','slippage_bps','commission_per_share',
    'minimum_commission','breakeven_threshold','tp1_pct','tp2_pct','tp3_pct',
    'staged_stop_after_tp2','news_interval_hours','news_overlap_hours','monitor_interval',
    'quote_refresh_seconds','strategy','captured_at'}
SECRET_PATTERN = re.compile(r'sk-or-v1-[a-zA-Z0-9]+|-----BEGIN .*PRIVATE KEY|postgres(?:ql)?://|\b\d{7,12}:[A-Za-z0-9_-]{30,}|\bgh[pousr]_[A-Za-z0-9_]{20,}')
POLICY_DEFAULTS = {
    'STOCK_SCANNER_EXIT_STRATEGY':'single', 'STOCK_SCANNER_EXTENDED_EXITS_FROM':'',
    'STOCK_SCANNER_SIGNAL_VALIDITY_HOURS':'24', 'STOCK_SCANNER_PAPER_NOTIONAL':'100',
    'STOCK_SCANNER_MAX_SYMBOL_EXPOSURE':'250', 'STOCK_SCANNER_MAX_TOTAL_EXPOSURE':'1000',
    'STOCK_SCANNER_SIM_SLIPPAGE_BPS':'2', 'STOCK_SCANNER_SIM_COMMISSION_PER_SHARE':'0.005',
    'STOCK_SCANNER_SIM_MIN_COMMISSION':'0.25', 'STOCK_SCANNER_BREAKEVEN_THRESHOLD':'0.5',
    'STOCK_SCANNER_STAGED_STOP_AFTER_TP2':'entry', 'STOCK_SCANNER_POSITION_NEWS_INTERVAL_HOURS':'6',
    'STOCK_SCANNER_POSITION_NEWS_OVERLAP_HOURS':'2', 'STOCK_SCANNER_LEVEL_MONITOR_INTERVAL':'300',
    'STOCK_SCANNER_QUOTE_REFRESH_SECONDS':'30', 'STOCK_SCANNER_AI_CANDIDATE_LIMIT':'6'}


def runtime_policy():
    return {key:os.getenv(key,value) for key,value in POLICY_DEFAULTS.items()}


def sanitize(data):
    data=copy.deepcopy(data)
    data.pop('snapshot_id',None)
    for row in data['tables']['agents']:
        for key in set(row)-AGENT_FIELDS:
            del row[key]
    data['tables']['scanner_operators']=[]
    data['tables']['scanner_target_revisions']=[]
    for row in data['tables']['scanner_signals']:
        row.update(news_json='[]', technical_json='{}',market_context_json='{}')
    for row in data['tables']['signals']:
        for field in ('content','title','tags'):
            if field in row: row[field]=None
    for row in data['tables']['scanner_legacy_adoptions']:
        row['evidence_json']='{"recovery_state":true,"historical_evidence_omitted":true}'
    for row in data['tables']['scanner_price_cursors']:
        row['error']=None  # Provider exceptions can contain URLs/credentials.
    for row in data['tables']['scanner_trades']:
        settings=json.loads(row['settings_json'])
        row['settings_json']=json.dumps({k:v for k,v in settings.items() if k in CONFIG_FIELDS},sort_keys=True)
    data['recovery_format']=1
    data['runtime_policy']=runtime_policy()
    data['snapshot_id']=active.digest(data)
    validate(data)
    return data


def validate(data):
    if data.get('recovery_format') != 1: raise ValueError('not_a_recovery_snapshot')
    if set(data.get('runtime_policy',{}))!=set(POLICY_DEFAULTS):
        raise ValueError('recovery_runtime_policy_missing_or_unknown')
    active.validate(data)
    if any(set(row)-AGENT_FIELDS for row in data['tables']['agents']):
        raise ValueError('authentication_columns_forbidden')
    if data['tables']['scanner_operators'] or data['tables']['scanner_target_revisions']:
        raise ValueError('unnecessary_history_in_recovery')
    for row in data['tables']['scanner_signals']:
        if row['news_json']!='[]' or row['technical_json']!='{}' or row['market_context_json']!='{}':
            raise ValueError('news_history_forbidden')
    for row in data['tables']['scanner_trades']:
        if set(json.loads(row['settings_json']))-CONFIG_FIELDS:
            raise ValueError('unapproved_recovery_settings')
    raw=json.dumps(data,ensure_ascii=True,allow_nan=False)
    if SECRET_PATTERN.search(raw): raise ValueError('secret_pattern_in_recovery')
    for name,value in os.environ.items():
        if any(part in name for part in ('TOKEN','PASSWORD','SECRET','API_KEY')) and len(value)>15 and value in raw:
            raise ValueError('environment_secret_in_recovery')
    return active.validate(data)


def export_postgres(url):
    tables={name:[] for name in active.TABLES}
    with psycopg.connect(url,row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='30000'")
        if conn.execute('SELECT max(version) version FROM schema_migrations').fetchone()['version']!=2:
            raise ValueError('unsupported_source_schema')
        def select(table,condition,args=()):
            rows=conn.execute(sql.SQL('SELECT * FROM {} WHERE ').format(sql.Identifier(table))+condition,args).fetchall()
            for row in rows:
                if row not in tables[table]: tables[table].append(dict(row))
            return rows
        def ids(table,column,values):
            values=sorted({v for v in values if v is not None})
            return select(table,sql.SQL('{} = ANY(%s)').format(sql.Identifier(column)),(values,)) if values else []
        agents=select('agents',sql.SQL('name=%s'),('us-stock-scanner',))
        if len(agents)!=1: raise ValueError('stable_scanner_identity_missing')
        agent=agents[0]['id']
        trades=select('scanner_trades',sql.SQL("agent_id=%s AND status='open'"),(agent,))
        select('scanner_accounts',sql.SQL('agent_id=%s'),(agent,))
        ids('scanner_signals','id',[r['signal_id'] for r in trades])
        fills=ids('scanner_fills','trade_id',[r['id'] for r in trades])
        ids('scanner_orders','id',[r['order_id'] for r in trades]+[r['order_id'] for r in fills])
        ids('scanner_legacy_adoptions','trade_id',[r['id'] for r in trades])
        ids('scanner_price_cursors','ticker',[r['ticker'] for r in trades])
        positions=ids('positions','id',[r.get('legacy_position_id') for r in trades])
        unmanaged=conn.execute('SELECT id FROM positions WHERE agent_id=%s AND quantity>0',(agent,)).fetchall()
        if {r['id'] for r in unmanaged}-{r['id'] for r in positions}:
            raise ValueError('unmanaged_original_positions_require_review')
        ids('signals','id',[r.get('external_signal_id') for r in tables['scanner_signals']])
        # Original positions/signals can reference other agent parents.
        ids('agents','id',[r.get('agent_id') for r in positions+tables['signals']]+[r.get('leader_id') for r in positions])
        settings=[dict(r) for r in conn.execute("SELECT * FROM scanner_settings WHERE key='active_exit_strategy'")]
        data={'version':1,'created_at':datetime.now(timezone.utc).isoformat(),
              'tables':tables,'settings':settings,'primary_agent_id':agent}
        return sanitize(data)


def restore(data,url,scanner_token):
    validate(data)
    if data['runtime_policy']!=runtime_policy():
        raise ValueError('restore_runtime_policy_mismatch_configure_saved_policy_before_import')
    return active.import_data(data,url,allow_defaults=True,scanner_token=scanner_token)


def encrypted_bytes(data,recipient):
    validate(data)
    raw=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    compressed=gzip.compress(raw,mtime=0)
    encrypted=subprocess.run(['age','-r',recipient],input=compressed,capture_output=True,check=True).stdout
    return encrypted,{'json_bytes':len(raw),'compressed_bytes':len(compressed),'encrypted_bytes':len(encrypted)}


def decrypt(path,identity):
    result=subprocess.run(['age','-d','-i',str(identity),str(path)],capture_output=True,check=True)
    data=json.loads(gzip.decompress(result.stdout))
    validate(data)
    return data


def main():
    import argparse
    import sys
    parser=argparse.ArgumentParser(description='Validate or restore an encrypted ACTIVE-state snapshot')
    parser.add_argument('action',choices=['validate','restore'])
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--identity',required=True)
    parser.add_argument('--database-url-file')
    parser.add_argument('--scanner-token-file')
    parser.add_argument('--workers-stopped',action='store_true')
    args=parser.parse_args()
    try:
        data=decrypt(args.snapshot,args.identity)
        if args.action=='restore':
            if not (args.workers_stopped and args.database_url_file and args.scanner_token_file):
                raise ValueError('restore_requires_stopped_workers_and_external_credentials')
            result=restore(data,Path(args.database_url_file).read_text().strip(),
                           Path(args.scanner_token_file).read_text().strip())
        else:
            result=validate(data)
        print(json.dumps({'status':'PASS','counts':result,'snapshot_id':data['snapshot_id']}))
    except Exception as exc:
        print('Recovery failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':
    main()
