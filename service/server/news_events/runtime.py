"""Cloud adapter: canonical jobs use the existing budget and durable outbox.

No trading writes; scanner_news is a presentation projection only. Final stock
review continues to use the scanner's independent input, never this projection.
Existing collectors retain their own checkpoint/backoff and session ownership.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from .control import active, state
from .model import timestamp, event_type, canonical_url
from .store import Store
from .engine import Pipeline, route
from .bridge import scanner_identity_catalog, effective_policy
from .providers import Config, ExistingProvider


def now():return datetime.now(timezone.utc)


def connect():
    from database import get_db_connection
    return get_db_connection()


def membership(cursor=None):
    own=cursor is None;c=cursor or connect()
    try:
        held={r['ticker'] for r in c.execute("SELECT DISTINCT ticker FROM scanner_trades WHERE status='open' AND remaining_quantity>0 AND is_shadow=0")}
        watched={r['ticker'] for r in c.execute('SELECT ticker FROM scanner_news_watchlist WHERE enabled=1')}
        return held,watched
    finally:
        if own:c.close()


def pipeline():
    from news_pipeline import ROOT, SEC_MAP_CACHE, feed_settings, _float_env, _int_env
    cache=json.loads((ROOT/'.runtime/stock-universe.json').read_text(encoding='utf-8'))
    if not cache.get('members'):raise RuntimeError('canonical_universe_missing')
    sec=json.loads(SEC_MAP_CACHE.read_text(encoding='utf-8')) if SEC_MAP_CACHE.exists() else {}
    universe=scanner_identity_catalog(cache,sec)
    with connect() as c:
        for row in c.execute("SELECT ticker,company FROM scanner_trades WHERE status='open' AND is_shadow=0 UNION SELECT ticker,company FROM scanner_news_watchlist WHERE enabled=1"):
            universe.setdefault(row['ticker'],{'company':row['company']})
    cfg=feed_settings()
    policy=effective_policy(cfg,_float_env('STOCK_SCANNER_GENERAL_NEWS_MIN_RELEVANCE',.3,.3,1),
        _int_env('STOCK_SCANNER_GENERAL_NEWS_MAX_AGE_HOURS',6,1,24),
        cfg['scan_bridge_max_age'],_int_env('STOCK_SCANNER_NEWS_FEED_MAX_AGE_HOURS',168,24,720))
    control=state()
    if control['mode']!='canonical' or not control['not_before']:raise RuntimeError('canonical_not_activated')
    return Pipeline(Store(connect,production=True),universe,membership,not_before=control['not_before'],policy=policy)


def ingest_items(items,at=None):
    current=at or now();p=pipeline()
    result=dict(received=len(items),inserted=0,sources=0,linked=0,duplicates=0,rejected_invalid=0,rejected_date=0)
    for item in items:
        pid=item.get('provider','')
        try:
            # Existing collectors already have an approved access path. Do not
            # infer a license for any new adapter from this compatibility path.
            from news_pipeline import PROVIDERS
            if pid not in PROVIDERS and pid!='scanner_yahoo':raise ValueError('unregistered_collector')
            raw={**item,'id':item.get('id') or item['url'],'excerpt':item.get('source_excerpt','')}
            if pid=='global_voices':
                raw.update(license_label='CC BY 3.0',license_url='https://creativecommons.org/licenses/by/3.0/')
            kind='official/regulatory' if pid in {'sec_edgar','federal_reserve','bls','ecb','fda','ftc','doj','eia'} else 'social/relay' if pid=='telegram_channels' else 'aggregator'
            if pid=='sec_edgar':
                match=re.search(r'https://www\.sec\.gov/Archives/edgar/data/(\d+)/',item['url'])
                if match:raw['cik']=match[1]
                raw['event_type']='regulatory'
            provider=ExistingProvider(Config(pid,'',item['publisher'],kind,True,'approved'),lambda *_: {})
            source=provider.normalize(raw,current)
            with p.store.transaction() as c:
                before=c.execute('SELECT COUNT(*) n FROM ne_events').fetchone()['n']
            eid=p.ingest(source,current)
            if eid:
                result['sources']+=1
                with p.store.transaction() as c:
                    added=c.execute('SELECT COUNT(*) n FROM ne_events').fetchone()['n']-before
                result['inserted']+=int(added>0);result['duplicates']+=int(added==0)
                project(p,eid,current)
            else:result['rejected_invalid']+=1
        except (KeyError,TypeError,ValueError):result['rejected_invalid']+=1
    return result


def project(p,eid,at):
    """Keep the original dashboard/six-hour review read model, not an AI queue."""
    record=p.store.event(eid);event=record['body'];stamp=timestamp(at)
    if record['reason'] in {'backlog_blocked','stale_or_future'}:
        return None # Audit in ne_events only; never repopulate the public feed.
    with p.store.transaction(True) as c:
        mapping=c.execute('SELECT news_id FROM ne_projection WHERE event_id=?',(eid,)).fetchone()
        held,watched=membership(c);tickers=event['tickers']
        scope='open_position' if set(tickers)&held else 'watchlist' if set(tickers)&watched else 'universe' if tickers else 'market'
        first=event['sources'][0]
        facts=json.dumps({'title':event['title'],'source_excerpt':event['source_excerpt'],'canonical_event_id':eid})
        if not mapping:
            c.execute('''INSERT INTO scanner_news(fingerprint,ticker,scope,title,publisher,url,published_at,
                analysis_status,fetched_at,provider,canonical_key,original_publisher,collected_at,source_kind,
                headline_only,source_facts_json,verified_tickers_json,alternate_sources_json,content_hash,updated_at,news_category)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('canonical:'+eid,tickers[0] if tickers else None,scope,event['title'],first['publisher'],first['url'],
                 event['published_at'],'canonical_pending',stamp,'canonical_events',eid,first['publisher'],
                 event['collected_at'],'canonical_evidence',int(not event['source_excerpt']),facts,json.dumps(tickers),
                 json.dumps(event['provenance']),record['evidence_version'],stamp,'company' if tickers else 'macro'))
            nid=c.execute('SELECT id FROM scanner_news WHERE fingerprint=?',('canonical:'+eid,)).fetchone()['id']
            c.execute('INSERT INTO ne_projection VALUES(?,?)',(eid,nid))
        else:nid=mapping['news_id']
        analysis=c.execute("SELECT result_json FROM ne_analysis WHERE event_id=? AND version=? AND status='done'",(eid,record['evidence_version'])).fetchone()
        r=json.loads(analysis['result_json']) if analysis else {}
        c.execute('''UPDATE scanner_news SET scope=?,title=?,title_he=?,summary_he=?,interpretation_he=?,sentiment=?,
            materiality=?,relevance=?,analysis_status=?,analysis_error=?,analyzed_at=?,alternate_sources_json=?,
            source_facts_json=?,content_hash=?,updated_at=? WHERE id=?''',
            (scope,event['title'],r.get('title_he'),r.get('summary_he'),r.get('interpretation_he'),r.get('sentiment'),
             r.get('materiality'),r.get('relevance'),'analyzed' if analysis else 'canonical_'+record['status'],record['reason'],
             stamp if analysis else None,json.dumps(event['provenance']),facts,record['evidence_version'],stamp,nid))
        for ticker in tickers:
            for trade in c.execute("SELECT id FROM scanner_trades WHERE ticker=? AND status='open' AND is_shadow=0",(ticker,)).fetchall():
                c.execute('''INSERT INTO scanner_trade_news(trade_id,news_id,linked_at) VALUES(?,?,?)
                    ON CONFLICT(trade_id,news_id) DO NOTHING''',(trade['id'],nid,stamp))
    return nid


def completion(stage,system,payload,schema):
    from ai_provider import json_completion
    from .call_context import CURRENT
    usage={}
    context=payload.get('source',payload)
    token=CURRENT.set(dict(event_id=context['canonical_event_id'],version=context['evidence_version'],stage=stage))
    try:
        value=json_completion(system,payload,schema=schema,task='news',max_attempts=1,
            usage_sink=usage,repair=stage in {'editorial_repair','repair_review'})
    except Exception as exc:
        exc.canonical_usage=usage
        raise
    finally:CURRENT.reset(token)
    return value,usage


def analyze_jobs(at=None):
    from ai_budget import check
    from scanner_engine import set_service_status
    from .analysis import CanonicalAnalyzer
    from .evidence import SECEvidence
    current=at or now();p=pipeline();p.recover_interrupted(current)
    with p.store.transaction() as c:
        unfinished=[r['event_id'] for r in c.execute("""SELECT e.event_id FROM ne_events e
            WHERE e.status='analyzed' AND e.reason IS NULL AND NOT EXISTS(SELECT 1 FROM ne_delivery d WHERE d.event_id=e.event_id AND d.version=e.evidence_version) LIMIT 20""")]
        rows=[dict(r) for r in c.execute("SELECT event_id FROM ne_events WHERE status='pending' ORDER BY created_at LIMIT 20")]
    recovered=0
    for eid in unfinished:
        project(p,eid,current)
        recovered+=queue_outbox(p,eid,current)
    if not rows:
        set_service_status('news_ai','idle','Canonical queue: no new due events',success=True)
        return dict(analyzed=0,alerts=recovered,errors=[])
    held,watched=membership()
    rows.sort(key=lambda r:not bool(set(p.store.event(r['event_id'])['body']['tickers'])&(held|watched)))
    eid=rows[0]['event_id'];event=p.store.event(eid)['body']
    from .factual_evidence import sufficient
    if not sufficient(event):
        p.enrich(eid,[SECEvidence(os.getenv('NEWS_SEC_USER_AGENT',''))],current)
    check() # Do not claim/bill a job if the global budget/cooldown is blocked.
    outcome=p.analyze(eid,CanonicalAnalyzer(completion),current)
    project(p,eid,current)
    alerts=queue_outbox(p,eid,current) if outcome=='done' else 0
    good=outcome=='done'
    set_service_status('news_ai','ok' if good else 'degraded',
        'Canonical event outcome: '+outcome,success=good)
    return dict(analyzed=int(good),alerts=alerts,errors=[] if good else [outcome])


def message(event,result,topic,tickers):
    from news_pipeline import _publication_time_he
    from news_presentation import hide_relay_branding
    parts=['📰 '+hide_relay_branding(result['title_he'])]
    if tickers:parts.append('מניות: '+', '.join(tickers))
    parts.append(hide_relay_branding(result['summary_he']))
    if topic!='market_news':parts.append('פרשנות AI: '+hide_relay_branding(result['interpretation_he']))
    # Ingestion provenance stays in storage. Retain required licensed credits.
    credits=[s['publisher'] for s in event['sources'] if s.get('raw_metadata',{}).get('license_url')]
    if credits:parts.append('\n'.join(dict.fromkeys(credits)))
    licenses={s.get('raw_metadata',{}).get('license_label','')+' '+s.get('raw_metadata',{}).get('license_url','')
              for s in event['sources'] if s.get('raw_metadata',{}).get('license_url')}
    if licenses:parts.append('תרגום/תקציר AI · '+ '; '.join(sorted(licenses)))
    parts.append('פורסם: '+_publication_time_he(event['published_at']))
    return '\n\n'.join(parts)[:4000]


def queue_outbox(p,eid,at):
    from scanner_engine import enqueue_telegram
    p.queue(eid,at);count=0
    with p.store.transaction(True) as c:
        control=state(c)
        if control['mode']!='canonical':return 0
        record=c.execute('SELECT * FROM ne_events WHERE event_id=?',(eid,)).fetchone()
        event=json.loads(record['body_json'])
        result=c.execute("SELECT result_json FROM ne_analysis WHERE event_id=? AND version=? AND status='done'",(eid,record['evidence_version'])).fetchone()
        if not result:return 0
        result=json.loads(result['result_json'])
        for row in c.execute("SELECT * FROM ne_delivery WHERE event_id=? AND status='sandbox_pending'",(eid,)).fetchall():
            topic=row['topic'];version=row['version'];tickers=json.loads(row['tickers_json'])
            if record['reason'] or version!=record['evidence_version']:continue
            if any(c.execute('SELECT 1 FROM ne_cutover_receipts WHERE source_url=? AND topic=?',(url,topic)).fetchone() for url in event['source_urls']):
                c.execute("UPDATE ne_delivery SET status='legacy_receipt' WHERE event_id=? AND version=? AND topic=?",(eid,version,topic));continue
            key='canonical:'+eid+':'+version+':'+topic
            kind={'market_news':'market_news','portfolio_watchlist':'position_news','important_stock_news':'stock_news'}[topic]
            if enqueue_telegram(c,key,kind,message(event,result,topic,tickers),published_at=event['published_at']):
                c.execute('INSERT INTO ne_outbox VALUES(?,?,?,?,?) ON CONFLICT(dedupe_key) DO NOTHING',(key,eid,version,topic,control['epoch']))
                count+=1
            c.execute("UPDATE ne_delivery SET status='outbox' WHERE event_id=? AND version=? AND topic=?",(eid,version,topic))
    return count


def delivery_message(outbox):
    """Re-check epoch, identity, evidence, current membership and age at send."""
    if not active():return None
    p=pipeline()
    with p.store.transaction() as c:
        link=c.execute('SELECT * FROM ne_outbox WHERE dedupe_key=?',(outbox['dedupe_key'],)).fetchone()
        if not link or link['epoch']!=state(c)['epoch']:return None
        record=c.execute('SELECT * FROM ne_events WHERE event_id=?',(link['event_id'],)).fetchone()
        if not record or record['evidence_version']!=link['version'] or record['status']!='analyzed' or record['reason']:return None
        event=json.loads(record['body_json'])
        result=c.execute("SELECT result_json FROM ne_analysis WHERE event_id=? AND version=? AND status='done'",(link['event_id'],link['version'])).fetchone()
        if not result:return None
        result=json.loads(result['result_json']);held,watched=membership(c)
        routes,reason=route(event,result,held,watched,p.universe,p.policy)
        matching=[tickers for topic,tickers in routes if topic==link['topic']]
        age=(now()-datetime.fromisoformat(event['published_at'])).total_seconds()
        max_age=p.policy.max_age_hours if set(event['tickers'])&(held|watched) else p.policy.market_age_hours if not event['tickers'] else p.policy.universe_age_hours
        if reason or not matching or not 0<=age<=max_age*3600:return None
        if event['published_at']<p.not_before or event['conflicts'] or any(s['rights']!='approved' for s in event['sources']):return None
        return message(event,result,link['topic'],matching[0])
