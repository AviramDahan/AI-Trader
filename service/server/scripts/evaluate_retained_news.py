"""Offline retained-news replay. No DB connection, provider I/O, AI or delivery.

Usage: python scripts/evaluate_retained_news.py dataset.json [--baseline-ref SHA]
Output is JSON to stdout. Treat route counts as proxies, NOT delivery forecasts.
The dataset is private and must not be committed; it contains news/account context.
"""
import json,re,sys,argparse,subprocess,types
from collections import Counter
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
parser=argparse.ArgumentParser()
parser.add_argument('dataset')
parser.add_argument('--baseline-ref')
args=parser.parse_args()
if args.baseline_ref:
 # Load trusted repository versions only, in this isolated audit process.
 import news_events
 for name in ('model','macro_rules','factual_evidence'):
  code=subprocess.check_output(['git','show',f'{args.baseline_ref}:service/server/news_events/{name}.py'],text=True,encoding='utf8')
  module=types.ModuleType('news_events.'+name)
  module.__package__='news_events'
  sys.modules[module.__name__]=module
  setattr(news_events,name,module)
  exec(compile(code,f'{args.baseline_ref}:{name}', 'exec'),module.__dict__)
from news_events.model import Source,event_type,IdentityResolver,timestamp
from news_events.store import combine
from news_events.factual_evidence import sufficient
from news_events.engine import route,Policy
dataset=json.loads(Path(args.dataset).read_text(encoding='utf-8-sig'))
START,END=dataset['window']
# This isolated audit process only: avoid recompiling 518 unchanged issuer regexes per row.
re._MAXCACHE=10000
def dt(s):return datetime.fromisoformat(timestamp(s))
universe=dataset['universe'];rows=dataset['rows'];deliveries=dataset['deliveries']
trades=dataset['trades'];watch=dataset['watch'];source_rows=dataset['source_rows']
ids={int(r['dedupe_key'].split(':')[1]) for r in deliveries if not r['dedupe_key'].startswith('canonical:')}
for r in trades+watch:universe.setdefault(r['ticker'],{'company':r['company']})
resolver=IdentityResolver(universe);sources_by={}
for r in source_rows:sources_by.setdefault(r['news_id'],[]).append(r)
results={};all_reasons=Counter();metadata_missing=0;alternate_after=0
for r in sorted(rows,key=lambda x:x.get('collected_at') or x['fetched_at']):
 at=dt(r.get('collected_at') or r['fetched_at']);facts=json.loads(r.get('source_facts_json') or '{}');excerpt=facts.get('source_excerpt','')
 try:
  sources=[]
  for s in sources_by.get(r['id'],[]):
   if dt(s['collected_at'])>at:alternate_after+=1;continue
   raw=json.loads(s.get('raw_metadata_json') or '{}');pid=s['provider'];cik=''
   if pid=='sec_edgar':
    m=re.search(r'/Archives/edgar/data/(\d+)/',s['url']);cik=m[1] if m else ''
   sources.append(Source(pid,s['url'],s['url'],s['publisher'],s['published_at'],s['collected_at'],r['title'],raw.get('source_excerpt') or excerpt,'social/relay' if pid=='telegram_channels' else 'aggregator',(),cik,'regulatory' if pid=='sec_edgar' else event_type(r['title'],raw.get('source_excerpt') or excerpt),raw_metadata=raw,rights='approved'))
  if not sources:
   sources=[Source(r['provider'],r['url'],r['url'],r['publisher'],r['published_at'],at.isoformat(),r['title'],excerpt,event_type=event_type(r['title'],excerpt),rights='approved')]
  if r['provider']=='yahoo_priority' and not any('provider_tickers' in s.raw_metadata for s in sources):metadata_missing+=1
  identities={i['ticker']:i for s in sources for i in resolver.resolve(s)}
  evidence,conflicts=combine([s.data() for s in sources])
  event={'title':r['title'],'event_type':sources[0].event_type,'tickers':sorted(identities),'company_identity':list(identities.values()),'sources':[s.data() for s in sources],'normalized_evidence':evidence,'conflicts':conflicts}
  held={t['ticker'] for t in trades if dt(t['opened_at'])<=at and (not t['closed_at'] or dt(t['closed_at'])>at)}
  watched={t['ticker'] for t in watch if t['enabled'] and dt(t['created_at'])<=at}
  age=(at-dt(r['published_at'])).total_seconds();personal=bool(set(identities)&(held|watched))
  # Counterfactual continuous service, NOT a new activation at the sample start.
  # Do not falsely reject articles published shortly before the audit window.
  reason='stale_or_future' if age<0 or age>(168 if personal else 6)*3600 else 'identity_unverified' if not identities and event['event_type']!='market' else 'unsupported_or_noise' if event['event_type']=='unknown' else 'source_conflict' if conflicts else 'insufficient_information' if not sufficient(event) else 'evidence_budget_exceeded' if sum(len(e['text']) for e in evidence)>12000 else None
  routes=[];reuse='not_needed'
  if not reason:
   if r['analysis_status']=='analyzed' and r['relevance'] is not None and r['materiality'] and r['sentiment']:
    routes,rejected=route(event,{'related':True,'relevance':r['relevance'],'materiality':r['materiality'],'sentiment':r['sentiment']},held,watched,universe,Policy())
    reuse='proxy_existing_analysis';reason='proxy_route_eligible' if routes else rejected or 'route_rejected'
   else:reason='requires_analysis'
  if r['provider']=='yahoo_priority' and not any('provider_tickers' in s.raw_metadata for s in sources):
   reason='missing_original_yahoo_metadata';routes=[];reuse='unknown'
  all_reasons[reason]+=1
  results[r['id']]={'news_id':r['id'],'title':r['title'],'provider':r['provider'],'reason':reason,'event_type':event['event_type'],'tickers':event['tickers'],'routes':[v[0] for v in routes],'relevance':r['relevance'],'reuse':reuse}
 except (ValueError,TypeError,KeyError) as e:
  results[r['id']]={'news_id':r['id'],'reason':'reconstruction_error','error':type(e).__name__};all_reasons['reconstruction_error']+=1
by_topic={};examples={};proxy_routes=Counter()
for d in deliveries:
 nid=int(d['dedupe_key'].split(':')[1]);r=results.get(nid,{'reason':'missing_row'})
 by_topic.setdefault(d['event_type'],Counter())[r['reason']]+=1
 examples.setdefault(r['reason'],[])
 if len(examples[r['reason']])<8:examples[r['reason']].append(r)
 if r.get('routes'):
  for topic in r['routes']:proxy_routes[topic]+=1
print(json.dumps({'window':[START,END],'actual_deliveries':dict(Counter(r['event_type'] for r in deliveries)),'unique_delivered_news':len(ids),'reconstructed_rows':len(rows),'all_row_funnel':all_reasons,'delivered_first_block':by_topic,'proxy_routes_before_canonical_dedupe':proxy_routes,'missing_yahoo_raw_metadata_rows':metadata_missing,'later_source_observations_excluded':alternate_after,'examples':examples,'results':results,'limitations':['Reuses saved legacy scores, not a canonical AI/quality result.','Current universe; watchlist history is incomplete.','Latest stored source content may differ from first ingestion.','Yahoo raw provider_tickers not preserved in legacy source rows; identity results incomplete.','No cross-row canonical merge or new SEC enrichment simulated.','No hypothetical missed direct-provider items reconstructed.']},ensure_ascii=False))
