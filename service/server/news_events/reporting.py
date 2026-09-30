"""SQL/Python only; never spends AI tokens to calculate operational metrics."""
import json
from collections import Counter,defaultdict
from datetime import datetime
from .queue_health import summarize


def report(store,now):
    with store.transaction() as c:
        events=[dict(r) for r in c.execute('''SELECT e.*,v.created_at AS version_created_at FROM ne_events e
            LEFT JOIN ne_versions v ON v.event_id=e.event_id AND v.version=e.evidence_version''')]
        metrics=[dict(r) for r in c.execute('SELECT * FROM ne_metrics')]
        states={r['provider_id']:json.loads(r['state_json']) for r in c.execute('SELECT * FROM ne_provider_state')}
        sources=c.execute('SELECT COUNT(*) AS n FROM ne_sources').fetchone()['n']
    providers=defaultdict(Counter);calls=[];ingest=Counter();outcomes=Counter();per_event={}
    for row in metrics:
        d=json.loads(row['data_json'])
        if row['stage']=='ingest':ingest[row['result']]+=1
        if row['provider_id']:
            p=providers[row['provider_id']];p[row['stage']+':'+row['result']]+=1
            p['raw_items']+=d.get('raw_items',0)
        if row['stage']=='analysis':
            calls.extend(d.get('calls',[]))
            event=per_event.setdefault(row['event_id'],{'calls':0,'known_cost':0,'unknown_cost_calls':0,'providers':[],
                                                       'input_tokens':0,'output_tokens':0,'latency_seconds':0})
            event['providers']=sorted(set(event['providers'])|set(d.get('providers',[])))
            event['latency_seconds']+=d.get('latency',0)
            for call in d.get('calls',[]):
                event['calls']+=1
                event['unknown_cost_calls']+=call.get('cost') is None
                event['known_cost']+=call.get('cost') or 0
                event['input_tokens']+=call.get('input_tokens') or 0
                event['output_tokens']+=call.get('output_tokens') or 0
    multi=0
    for row in events:
        outcomes[row['reason'] or row['status']]+=1
        body=json.loads(row['body_json']);multi+=len(body['providers'])>1
    known=[v['cost'] for v in calls if v.get('cost') is not None]
    return {'canonical_events':len(events),'source_versions':sources,'multi_source_events':multi,
        'source_to_event_ratio':sources/len(events) if events else None,
        'identical_cross_source_dedupe_ratio':ingest['cross_source_duplicate']/sources if sources else None,
        'cross_source_duplicate_versions':ingest['cross_source_duplicate'],
        'analysis_jobs_avoided_by_identical_evidence':ingest['cross_source_duplicate'],
        'billable_calls':len(calls),'known_cost':sum(known),'calls_with_unknown_cost':len(calls)-len(known),
        'input_tokens':sum(v.get('input_tokens') or 0 for v in calls),
        'output_tokens':sum(v.get('output_tokens') or 0 for v in calls),
        **summarize(events,now),
        'held_material_review_count':sum(r['status']=='needs_material_review' for r in events),
        'outcomes':dict(outcomes),'providers':{k:dict(v) for k,v in providers.items()},'provider_health':states,'per_event':per_event,
        'cost_attribution':'Event/call cost counted once. Contributing providers are not separately billed or allocated.'}
