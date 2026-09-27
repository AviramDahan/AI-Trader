"""One pipeline per canonical event. Sandbox has NO public delivery transport."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import time
import uuid
from .model import IdentityResolver, timestamp, fingerprint
from .providers import ProviderFailure


@dataclass(frozen=True)
class Policy:
    # Same existing defaults; trial must load the effective production values.
    personal_relevance: float=.65
    stock_relevance: float=.80
    market_relevance: float=.50
    max_age_hours: int=168
    market_age_hours: int=6
    universe_age_hours: int=6


@dataclass
class Analysis:
    result:dict
    calls:list=field(default_factory=list)


def route(event,result,positions,watchlist,universe,policy):
    """Provider/trust intentionally absent from all topic decisions."""
    if not result.get('related'):return [],'irrelevant'
    relevance=result['relevance'];materiality=result['materiality'];sentiment=result['sentiment']
    tickers=set(event['tickers'])
    if not tickers and event['event_type']=='market':
        return ([('market_news',[])],None) if relevance>=policy.market_relevance else ([], 'below_market_threshold')
    if relevance<policy.personal_relevance:return [],'below_relevance_threshold'
    if materiality not in ('medium','high'):return [],'low_importance'
    if sentiment not in ('positive','negative','mixed'):return [],'no_directional_impact'
    personal=tickers&(set(positions)|set(watchlist))
    routes=[('portfolio_watchlist',sorted(personal))] if personal else []
    broad=(tickers&set(universe))-personal
    if broad and materiality=='high' and relevance>=policy.stock_relevance:
        routes.append(('important_stock_news',sorted(broad)))
    return routes,None if routes else 'below_broad_threshold'


class Pipeline:
    def __init__(self,store,universe,membership,*,not_before,policy=None):
        self.store=store;self.universe=universe;self.identities=IdentityResolver(universe)
        self.membership=membership;self.not_before=timestamp(not_before);self.policy=policy or Policy()

    def ingest(self,source,now):
        try:
            published=datetime.fromisoformat(timestamp(source.published_at))
            age=(now-published).total_seconds()
            identities=self.identities.resolve(source)
            reason=None
            if published<datetime.fromisoformat(self.not_before):reason='backlog_blocked'
            elif age<0 or age>self.policy.max_age_hours*3600:reason='stale_or_future'
            elif not identities and source.event_type!='market':reason='identity_unverified'
            elif source.event_type=='unknown':reason='unsupported_or_noise'
            return self.store.ingest(source,identities,reason)
        except (ValueError,TypeError,KeyError):
            with self.store.transaction(True) as c:
                self.store.metric(c,'normalize','invalid_metadata',timestamp(now),provider_id=source.provider_id)
            return None

    def collect(self,providers,now):
        def one(provider):
            pid=provider.provider_id
            with self.store.transaction(True) as c:
                saved=c.execute('SELECT state_json FROM ne_provider_state WHERE provider_id=?',(pid,)).fetchone()
                state=json.loads(saved['state_json']) if saved else {}
                if state.get('terminal') or state.get('next_at','')>timestamp(now) or state.get('lease_until','')>timestamp(now):return pid,state
                # Short DB lease; no open transaction across provider I/O.
                state['lease_until']=timestamp(now+timedelta(minutes=5))
                c.execute('INSERT INTO ne_provider_state VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET state_json=excluded.state_json',
                          (pid,json.dumps(state)))
            started=time.monotonic()
            try:
                response=provider.fetch(state,now)
                accepted=0;invalid=0
                for raw in response['items']:
                    try: source=provider.normalize(raw,now)
                    except (ValueError,TypeError,KeyError):
                        invalid+=1
                        with self.store.transaction(True) as c:self.store.metric(c,'normalize','invalid_metadata',timestamp(now),provider_id=pid)
                        continue
                    accepted+=bool(self.ingest(source,now))
                state={**state,'status':response.get('status','ok'),'attempts':0,'terminal':False,'error':None,
                    'cursor':response.get('cursor'),'page':response.get('page',0),
                    'cycle_started':response.get('cycle_started'),
                    'checkpoint_json':json.dumps(response.get('checkpoint',json.loads(state.get('checkpoint_json','{}')))),
                    'etag':response.get('etag',state.get('etag','')),
                    'last_modified':response.get('last_modified',state.get('last_modified','')),
                    'coverage':response.get('coverage'),'last_success':timestamp(now),
                    'next_at':timestamp(now+timedelta(seconds=max(60,provider.config.cadence)))}
                if response.get('errors'):state['error']='partial_provider_failure';state['status']='degraded'
                if invalid:
                    state['error']='source_metadata_invalid';state['status']='degraded'
                    if invalid==len(response['items']):
                        state['status']='requires_configuration';state['terminal']=True
                state['invalid_items']=invalid
                data={'raw_items':len(response['items']),'accepted_items':accepted}
            except Exception as exc:
                attempts=state.get('attempts',0)+1
                known=isinstance(exc,ProviderFailure)
                terminal=known and exc.terminal
                delay=max(exc.retry_after if known else 0, min(3600,60*2**min(attempts,6)))
                if attempts>=3:delay=max(delay,3600)
                state={**state,'status':'requires_configuration' if terminal else 'rate_limited' if known and exc.http_status==429 else 'degraded',
                    'attempts':attempts,'terminal':bool(terminal),'error':exc.reason if known else type(exc).__name__,
                    'http_status':exc.http_status if known else None,'retry_after':exc.retry_after if known else 0,
                    'next_at':timestamp(now+timedelta(seconds=delay))}
                data={}
            state['last_attempt']=timestamp(now);state['latency']=time.monotonic()-started;state.pop('lease_until',None)
            with self.store.transaction(True) as c:
                c.execute('INSERT INTO ne_provider_state VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET state_json=excluded.state_json',
                          (pid,json.dumps(state)))
                self.store.metric(c,'provider',state['status'],timestamp(now),provider_id=pid,latency=state['latency'],**data)
            return pid,state
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='phase2-provider') as pool:
            return dict(pool.map(one,providers))

    def enrich(self,event_id,providers,now):
        event=self.store.event(event_id)['body']
        if event['non_publication_reason'] in ('backlog_blocked','stale_or_future','identity_unverified','unsupported_or_noise'):return False
        changed=False
        for provider in providers:
            if not provider.can_handle(event):continue
            key=provider.cache_key(event)
            job_key='evidence:'+key
            with self.store.transaction(True) as c:
                cache=c.execute('SELECT body_json FROM ne_evidence_cache WHERE cache_key=?',(key,)).fetchone()
                saved=c.execute('SELECT state_json FROM ne_provider_state WHERE provider_id=?',(job_key,)).fetchone()
                state=json.loads(saved['state_json']) if saved else {}
                if not cache:
                    if state.get('terminal') or state.get('next_at','')>timestamp(now):continue
                    state['next_at']=timestamp(now+timedelta(minutes=5))
                    c.execute('INSERT INTO ne_provider_state VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET state_json=excluded.state_json',
                              (job_key,json.dumps(state)))
            if cache:
                from .model import Source
                source=Source(**json.loads(cache['body_json']))
            else:
                try:
                    raw=provider.fetch_evidence(event)
                    source=provider.normalize_evidence(raw,event)
                    if not provider.validate_identity(source,event):raise ValueError('evidence_identity_mismatch')
                except Exception as exc:
                    known=isinstance(exc,ProviderFailure)
                    attempts=state.get('attempts',0)+1
                    state.update(status='degraded',attempts=attempts,
                        error=exc.reason if known else type(exc).__name__,
                        terminal=exc.terminal if known else True,
                        next_at=timestamp(now+timedelta(seconds=max(exc.retry_after if known else 0,3600 if attempts>=3 else 60*2**attempts))))
                    with self.store.transaction(True) as c:
                        c.execute('UPDATE ne_provider_state SET state_json=? WHERE provider_id=?',(json.dumps(state),job_key))
                        self.store.metric(c,'enrichment','failed',timestamp(now),event_id,provider.provider_id,
                            reason=state['error'],http_status=exc.http_status if known else None)
                    continue
                with self.store.transaction(True) as c:
                    c.execute('INSERT INTO ne_evidence_cache VALUES(?,?,?) ON CONFLICT(cache_key) DO NOTHING',
                              (key,json.dumps(source.data()),timestamp(now)))
                    c.execute('UPDATE ne_provider_state SET state_json=? WHERE provider_id=?',
                              (json.dumps({'status':'ok','last_success':timestamp(now)}),job_key))
                    self.store.metric(c,'enrichment','success',timestamp(now),event_id,provider.provider_id)
            before=self.store.event(event_id)['evidence_version']
            attached=self.ingest(source,now)
            if attached!=event_id:
                raise ValueError('evidence_event_mismatch')
            changed|=before!=self.store.event(event_id)['evidence_version']
        return changed

    def analyze(self,event_id,analyzer,now):
        record=self.store.event(event_id)
        if record['status'] not in ('pending','analyzed'):return record['status']
        event=record['body'];version=record['evidence_version']
        positions,watchlist=self.membership()
        age=(now-datetime.fromisoformat(event['published_at'])).total_seconds()
        maximum=self.policy.max_age_hours if set(event['tickers'])&(set(positions)|set(watchlist)) else self.policy.market_age_hours if event['event_type']=='market' else self.policy.universe_age_hours
        reason=None
        if age<0 or age>maximum*3600:reason='stale_or_future'
        elif not event['normalized_evidence'] or not any(len(s['source_excerpt'].split())>=12 for s in event['sources']):reason='insufficient_information'
        elif sum(len(v['text']) for v in event['normalized_evidence'])>12000:reason='evidence_budget_exceeded' # no silent truncation
        elif any(s['rights'] not in ('approved','internal_review') for s in event['sources']):reason='license_required'
        if reason:
            with self.store.transaction(True) as c:
                c.execute('UPDATE ne_events SET status=?,reason=? WHERE event_id=?',('blocked',reason,event_id))
                self.store.metric(c,'precheck',reason,timestamp(now),event_id,ai_calls_avoided=0)
            return reason
        owner=uuid.uuid4().hex
        with self.store.transaction(True) as c:
            c.execute('''INSERT INTO ne_analysis(event_id,version,status,started_at,owner) VALUES(?,?,'running',?,?)
                ON CONFLICT(event_id,version) DO NOTHING''',(event_id,version,timestamp(now),owner))
            saved=c.execute('SELECT * FROM ne_analysis WHERE event_id=? AND version=?',(event_id,version)).fetchone()
            if saved['owner']!=owner:
                self.store.metric(c,'analysis','cached_or_already_claimed',timestamp(now),event_id,ai_calls_avoided=1)
                return saved['status']
        started=time.monotonic()
        try:
            # Network/LLM is strictly outside every DB transaction.
            output=analyzer(event)
            from news_quality import ANALYSIS_SCHEMA
            import jsonschema
            jsonschema.validate(output.result,ANALYSIS_SCHEMA)
            if any(not __import__('re').search('[\u0590-\u05ff]',output.result[k]) for k in ('title_he','summary_he','interpretation_he')):
                raise ValueError('news_missing_hebrew')
            status='done';error=None
        except Exception as exc:
            output=Analysis({},getattr(exc,'calls',[]))
            status='failed';error=getattr(exc,'safe_reason',type(exc).__name__)
            # Fail closed; no automatic rerun of a permanent/ambiguous call.
        with self.store.transaction(True) as c:
            c.execute('UPDATE ne_analysis SET status=?,result_json=?,error=?,finished_at=?,latency=? WHERE event_id=? AND version=? AND owner=?',
                      (status,json.dumps(output.result),error,timestamp(now),time.monotonic()-started,event_id,version,owner))
            # If new facts arrived during the call, old output cannot publish.
            current=c.execute('SELECT evidence_version FROM ne_events WHERE event_id=?',(event_id,)).fetchone()
            if current['evidence_version']==version:
                c.execute('UPDATE ne_events SET status=?,reason=? WHERE event_id=?',('analyzed' if status=='done' else 'quality_failed',error,event_id))
            self.store.metric(c,'analysis',status,timestamp(now),event_id,providers=event['providers'],
                latency=time.monotonic()-started,calls=output.calls,invocations=1)
        return status

    def queue(self,event_id,now):
        positions,watchlist=self.membership()
        with self.store.transaction(True) as c:
            r=c.execute('SELECT * FROM ne_events WHERE event_id=?',(event_id,)).fetchone()
            if r['status']!='analyzed':return []
            event=json.loads(r['body_json']);version=r['evidence_version']
            analyzed=c.execute("SELECT result_json FROM ne_analysis WHERE event_id=? AND version=? AND status='done'",(event_id,version)).fetchone()
            if not analyzed:return []
            age=(now-datetime.fromisoformat(event['published_at'])).total_seconds()
            personal=bool(set(event['tickers'])&(set(positions)|set(watchlist)))
            max_age=self.policy.max_age_hours if personal else self.policy.market_age_hours if event['event_type']=='market' else self.policy.universe_age_hours
            reason='backlog_blocked' if event['published_at']<self.not_before else 'stale_or_future' if not 0<=age<=max_age*3600 else 'source_conflict' if event['conflicts'] else 'license_required' if any(s['rights']!='approved' for s in event['sources']) else None
            routes=[]
            if not reason:routes,reason=route(event,json.loads(analyzed['result_json']),positions,watchlist,self.universe,self.policy)
            for topic,tickers in routes:
                c.execute('INSERT INTO ne_delivery VALUES(?,?,?,?,?,?) ON CONFLICT(event_id,version,topic) DO NOTHING',
                          (event_id,version,topic,json.dumps(tickers),'sandbox_pending',timestamp(now)))
            c.execute('UPDATE ne_events SET reason=? WHERE event_id=?',(reason,event_id))
            return routes

    def deliver_preview(self,event_id,now):
        """Revalidates current membership/version. Never calls Telegram."""
        self.queue(event_id,now)
        positions,watchlist=self.membership()
        previews=[]
        with self.store.transaction(True) as c:
            event_row=c.execute('SELECT * FROM ne_events WHERE event_id=?',(event_id,)).fetchone()
            event=json.loads(event_row['body_json'])
            for r in c.execute("SELECT * FROM ne_delivery WHERE event_id=? AND status='sandbox_pending'",(event_id,)).fetchall():
                allowed=not event_row['reason'] and r['version']==event_row['evidence_version']
                tickers=set(json.loads(r['tickers_json']))
                if r['topic']=='portfolio_watchlist':
                    tickers &= set(positions)|set(watchlist)
                    allowed=allowed and bool(tickers)
                if r['topic']=='important_stock_news':allowed=allowed and not bool(tickers&(set(positions)|set(watchlist)))
                c.execute('UPDATE ne_delivery SET status=? WHERE event_id=? AND version=? AND topic=?',
                          ('previewed' if allowed else 'cancelled',event_id,r['version'],r['topic']))
                if allowed:previews.append({'topic':r['topic'],'event_id':event_id,'version':r['version'],'tickers':sorted(tickers)})
        return previews

    def recover_interrupted(self,now,maximum_seconds=600):
        """Do not repeat a possibly billed request after a process crash."""
        with self.store.transaction(True) as c:
            rows=c.execute("SELECT * FROM ne_analysis WHERE status='running' AND started_at<?",
                           (timestamp(now-timedelta(seconds=maximum_seconds)),)).fetchall()
            for row in rows:
                c.execute("UPDATE ne_analysis SET status='interrupted_unknown',error='operator_review_required' WHERE event_id=? AND version=?",
                          (row['event_id'],row['version']))
            return len(rows)
