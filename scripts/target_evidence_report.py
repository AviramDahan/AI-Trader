"""Bounded read-only journal report; no init, providers, AI, messages or workers.

Run inside the API/scanner container with PGOPTIONS default_transaction_read_only=on.
Supply --since as an ISO-8601 timestamp with timezone. No historical reconstruction.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


def report(conn, since, limit=1000):
    stamp = datetime.fromisoformat(since.replace('Z', '+00:00'))
    if stamp.tzinfo is None or not 1 <= limit <= 10000:
        raise ValueError('timezone and bounded limit required')
    since = stamp.astimezone(timezone.utc).isoformat()
    rows = conn.execute("""SELECT scan_id,ticker,metrics_json FROM scanner_candidates
        WHERE stage='target_check' AND created_at>=? ORDER BY id DESC LIMIT ?""", (since, limit+1)).fetchall()
    result, seen = [], set()
    for row in rows[:limit]:
        r = json.loads(row['metrics_json'])
        if r['observation_id'] in seen:
            continue
        seen.add(r['observation_id'])
        # Link by persisted scan/ticker, not by current holdings or a global policy flag.
        signals = conn.execute('SELECT id,status,technical_json FROM scanner_signals WHERE scan_id=? AND ticker=?',
                               (row['scan_id'],row['ticker'])).fetchall()
        links = []
        for s in signals:
            orders = conn.execute('SELECT id,status FROM scanner_orders WHERE signal_id=?', (s['id'],)).fetchall()
            plan = json.loads(s['technical_json']).get('target_plan') or {}
            links.append({'signal_id':s['id'],'signal_status':s['status'],
                          'saved_policy_version':plan.get('policy_version',plan.get('method')),
                          'orders':[dict(o) for o in orders]})
        result.append({k:r.get(k) for k in ('observation_id','review_id','scan_id','ticker','phase','build_sha',
            'policy_version','decided_at','outcome','rejection_reason','rejection_detail','quote','geometry',
            'accepted_levels','evidence_gap')} | {'signal_links':links})
    return {'window_since':since,'clipped':len(rows)>limit,'observations':len(result),
            'outcomes':dict(Counter((r['phase']+':'+r['outcome']) for r in result)),
            'rejections':dict(Counter(r['rejection_reason'] for r in result if r['rejection_reason'])),
            'records':result,'note':'Actual observations, not proof of counterfactual fills or returns. Older history has no journal.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--since',required=True);p.add_argument('--limit',type=int,default=1000)
    args=p.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'service/server'))
    from database import get_db_connection, using_postgres
    with get_db_connection() as c:
        if using_postgres():
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            c.execute("SET LOCAL statement_timeout='20s'")
            assert c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
        else:
            c.execute('PRAGMA query_only=ON')
        print(json.dumps(report(c,args.since,args.limit),ensure_ascii=False))


if __name__=='__main__':main()
