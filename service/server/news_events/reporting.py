"""SQL/Python only; never spends AI tokens to calculate operational metrics."""
import json
from collections import Counter,defaultdict
from datetime import datetime
from .queue_health import summarize


def health_report(store, now):
    """Aggregate health, without materializing history or per-event details.

    PostgreSQL is the production database. Keep the legacy detailed report for
    explicit diagnostics and SQLite sandbox callers; never fall back on PG error.
    """
    with store.transaction() as c:
        if getattr(c, '_backend', 'sqlite') != 'postgres':
            compact = None
        else:
            from .queue_health import queue_rows
            compact = dict(c.execute('''SELECT count(*) canonical_events,
                count(*) FILTER (WHERE jsonb_array_length(body_json::jsonb->'providers')>1) multi_source_events,
                count(*) FILTER (WHERE status='needs_material_review') held_material_review_count
                FROM ne_events''').fetchone())
            compact['source_versions'] = c.execute('SELECT count(*) n FROM ne_sources').fetchone()['n']
            compact.update(dict(c.execute('''SELECT count(*) billable_calls,
                coalesce(sum((call->>'cost')::double precision),0) known_cost,
                count(*) FILTER (WHERE call->>'cost' IS NULL) calls_with_unknown_cost,
                coalesce(sum((call->>'input_tokens')::bigint),0) input_tokens,
                coalesce(sum((call->>'output_tokens')::bigint),0) output_tokens
                FROM ne_metrics CROSS JOIN LATERAL jsonb_array_elements(data_json::jsonb->'calls') call
                WHERE stage='analysis' ''').fetchone()))
            # PostgreSQL SUM(bigint) returns numeric/Decimal, unlike Python sum.
            for key in ('input_tokens','output_tokens'):
                compact[key] = int(compact[key])
            compact['outcomes'] = {r['outcome']:r['n'] for r in c.execute(
                "SELECT coalesce(nullif(reason,''),status) outcome,count(*) n FROM ne_events GROUP BY 1")}
            providers = defaultdict(Counter)
            for r in c.execute('''SELECT provider_id,stage,result,count(*) n,
                    coalesce(sum((data_json::jsonb->>'raw_items')::bigint),0) raw_items
                    FROM ne_metrics WHERE provider_id IS NOT NULL AND provider_id!=''
                    GROUP BY provider_id,stage,result'''):
                p = providers[r['provider_id']]
                p[r['stage']+':'+r['result']] += r['n']
                p['raw_items'] += int(r['raw_items'])
            compact['providers'] = {k:dict(v) for k,v in providers.items()}
            compact['provider_health'] = {r['provider_id']:json.loads(r['state_json'])
                for r in c.execute('SELECT provider_id,state_json FROM ne_provider_state')}
            duplicate = c.execute("SELECT count(*) n FROM ne_metrics WHERE stage='ingest' AND result='cross_source_duplicate'").fetchone()['n']
            compact.update(cross_source_duplicate_versions=duplicate,
                analysis_jobs_avoided_by_identical_evidence=duplicate,
                source_to_event_ratio=compact['source_versions']/compact['canonical_events'] if compact['canonical_events'] else None,
                identical_cross_source_dedupe_ratio=duplicate/compact['source_versions'] if compact['source_versions'] else None)
            compact.update(summarize(queue_rows(c), now))
    if compact is None:
        compact = report(store, now)
        compact.pop('per_event')
    compact['cost_attribution'] = 'Event/call cost counted once. Contributing providers are not separately billed or allocated.'
    return compact


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
