"""Bounded READ ONLY evidence for scheduled checks. Never init/fetch/replay execution."""
import json
import os
from collections import Counter
from datetime import datetime,timezone,timedelta
from database import get_db_connection, using_postgres
from single_target_policy import build as baseline_build, instant
from single_breakout_policy import build as breakout_build


def compare(check,high):
    source=check['source_inputs'];entry=check['quote']['price']
    args=(entry,source['atr'],source['zones'],source['data_as_of'],check['decided_at'])
    try:
        baseline_build(*args)
        return 'BOTH_PASS'
    except ValueError as exc:
        if str(exc)!='no_forward_zone':
            return 'BOTH_FAIL'
    if high is None:
        return 'NOT_VERIFIED_MISSING_COMPLETED_HIGH'
    try:
        breakout_build(*args,high)
        return 'BASELINE_FAIL_NEW_PASS'
    except ValueError:
        return 'BOTH_FAIL'


def collect(conn,since):
    assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
    # Filter before the cap: overnight NOT_EVALUATED observations must not
    # crowd out the actual paired checks. Invalid JSON is explicit unknown.
    # Two set-based reads replace one full technical-table scan per observation.
    evidence=conn.execute("""WITH observed AS (
        SELECT id,scan_id,ticker,metrics_json,
          CASE WHEN pg_input_is_valid(metrics_json,'jsonb') THEN metrics_json::jsonb END body
        FROM scanner_candidates WHERE stage='target_check' AND created_at>=?)
        SELECT id,scan_id,ticker,metrics_json FROM observed
        WHERE body IS NULL OR jsonb_typeof(body)<>'object' OR
          (body->>'phase'='pre_ai' AND body->>'action'='BUY' AND body->'evaluated'='true'::jsonb)
        ORDER BY id LIMIT 2001""",(since,)).fetchall()
    pairs=sorted({(row['scan_id'],row['ticker']) for row in evidence[:2000]})
    technical={}
    if pairs:
        values=','.join('(?,?)' for _ in pairs)
        rows=conn.execute(f"""WITH wanted(scan_id,ticker) AS (VALUES {values})
            SELECT DISTINCT ON (t.scan_id,t.ticker) t.scan_id,t.ticker,t.metrics_json
            FROM scanner_candidates t JOIN wanted w ON w.scan_id=t.scan_id AND w.ticker=t.ticker
            WHERE t.stage='technical' ORDER BY t.scan_id,t.ticker,t.id""",
            tuple(value for pair in pairs for value in pair)).fetchall()
        technical={(row['scan_id'],row['ticker']):row['metrics_json'] for row in rows}
    cohort=Counter();sources=set();rejections=Counter()
    for row in evidence[:2000]:
        try:
            check=json.loads(row['metrics_json'])
            if not isinstance(check,dict):raise ValueError('invalid_target_observation')
            if check.get('phase')!='pre_ai' or check.get('action')!='BUY' or check.get('evaluated') is not True:
                continue
            if check.get('rejection_reason'):rejections[check['rejection_reason']]+=1
            source=json.loads(technical.get((row['scan_id'],row['ticker'])) or '{}')
            if not isinstance(source,dict):raise ValueError('invalid_technical_observation')
            high=check.get('source_inputs',{}).get('completed_high',source.get('recent_high_20d'))
            cohort[compare(check,high)]+=1
            sources.add((check.get('ticker'),check.get('source_inputs_sha256')))
        except (ValueError,KeyError,TypeError,AttributeError):
            cohort['NOT_VERIFIED_INVALID_OR_INCOMPLETE_EVIDENCE']+=1
    outcomes=[dict(r) for r in conn.execute("""SELECT s.status,count(*) count
        FROM scanner_signals s WHERE s.created_at>=?
        AND s.technical_json::jsonb->'target_plan'->>'policy_version'='single_breakout_v1'
        GROUP BY s.status""",(since,))]
    chains=[dict(r) for r in conn.execute("""SELECT s.id signal_id,o.id order_id,t.id trade_id,
        count(f.id) FILTER (WHERE f.fill_type='entry') entries,
        count(f.id) FILTER (WHERE f.fill_type IN ('tp','stop','sell')) exits,
        min(f.bar_at) first_fill_at,max(f.bar_at) last_fill_at
        FROM scanner_signals s JOIN scanner_orders o ON o.signal_id=s.id
        JOIN scanner_trades t ON t.order_id=o.id AND t.is_shadow=0 AND t.legacy_position_id IS NULL
        LEFT JOIN scanner_fills f ON f.trade_id=t.id
        WHERE s.created_at>=? AND s.technical_json::jsonb->'target_plan'->>'policy_version'='single_breakout_v1'
        GROUP BY s.id,o.id,t.id ORDER BY s.id LIMIT 101""",(since,))]
    holds=conn.execute("""SELECT count(*) count FROM scanner_orders
        WHERE purpose='entry' AND status='recovery_uncertain'""").fetchone()['count']
    duplicates=conn.execute("""SELECT count(*) count FROM
        (SELECT event_key FROM scanner_fills GROUP BY event_key HAVING count(*)>1) d""").fetchone()['count']
    return dict(window_start=since,build_sha=os.getenv('BUILD_SHA'),
                creation_enabled=os.getenv('STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED','false').lower()=='true',
                full_bar_creation_enabled=os.getenv('STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED','false').lower()=='true',
                paired_structural_checks=dict(cohort),unique_ticker_source_structures=len(sources),
                target_rejections=dict(rejections),new_policy_signals=outcomes,
                linked_chains=chains[:100],new_policy_completed_chains=sum(r['entries']==1 and r['exits']>0 for r in chains[:100]),
                recovery_uncertain=holds,duplicate_fill_keys=duplicates,
                evidence_truncated=len(evidence)>2000,chains_truncated=len(chains)>100,
                interpretation='Structure comparison is not historical AI approval, executed trades or proof of improved returns.')


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since',required=True)
    args=parser.parse_args()
    now=datetime.now(timezone.utc);since=instant(args.since)
    if not now-timedelta(days=14)<=since<=now:
        raise ValueError('read_only_audit_window_must_be_within_14_days')
    if not using_postgres():
        raise ValueError('read_only_audit_requires_postgresql')
    with get_db_connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='10000'")
        print(json.dumps(collect(conn,since.isoformat()),default=str,ensure_ascii=True))


if __name__=='__main__':main()
