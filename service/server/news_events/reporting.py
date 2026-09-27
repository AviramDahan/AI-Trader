"""SQL/Python only; never spends AI tokens to calculate operational metrics."""
import json
from collections import Counter,defaultdict
from datetime import datetime


def report(store,now):
    with store.transaction() as c:
        events=[dict(r) for r in c.execute('SELECT * FROM ne_events')]
        metrics=[dict(r) for r in c.execute('SELECT * FROM ne_metrics')]
        states={r['provider_id']:json.loads(r['state_json']) for r in c.execute('SELECT * FROM ne_provider_state')}
        sources=c.execute('SELECT COUNT(*) AS n FROM ne_sources').fetchone()['n']
    providers=defaultdict(Counter);calls=[];ingest=Counter();outcomes=Counter()
    for row in metrics:
        d=json.loads(row['data_json'])
        if row['stage']=='ingest':ingest[row['result']]+=1
        if row['provider_id']:
            p=providers[row['provider_id']];p[row['stage']+':'+row['result']]+=1
            p['raw_items']+=d.get('raw_items',0)
        if row['stage']=='analysis':
            calls.extend(d.get('calls',[]))
    ages=[];multi=0
    for row in events:
        outcomes[row['reason'] or row['status']]+=1
        body=json.loads(row['body_json']);multi+=len(body['providers'])>1
        if row['status'] in ('pending','needs_material_review'):
            ages.append(max(0,(now-datetime.fromisoformat(row['created_at'])).total_seconds()))
    known=[v['cost'] for v in calls if v.get('cost') is not None]
    return {'canonical_events':len(events),'source_versions':sources,'multi_source_events':multi,
        'source_to_event_ratio':sources/len(events) if events else None,
        'cross_source_duplicate_versions':ingest['cross_source_duplicate'],
        'analysis_jobs_avoided_by_identical_evidence':ingest['cross_source_duplicate'],
        'billable_calls':len(calls),'known_cost':sum(known),'calls_with_unknown_cost':len(calls)-len(known),
        'input_tokens':sum(v.get('input_tokens') or 0 for v in calls),
        'output_tokens':sum(v.get('output_tokens') or 0 for v in calls),
        'queue_size':len(ages),'oldest_queue_seconds':max(ages,default=0),
        'outcomes':dict(outcomes),'providers':{k:dict(v) for k,v in providers.items()},'provider_health':states,
        'cost_attribution':'Event/call cost counted once. Contributing providers are not separately billed or allocated.'}
