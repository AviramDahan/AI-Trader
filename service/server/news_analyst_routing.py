"""Analyst-update destination only: deterministic retained facts, never AI.

Original durable news kinds/keys and every admission/delivery fence stay intact.
Personal ticker audiences remain personal; only broad news converges here.
"""
import json
import os
import re
from decimal import Decimal

BROAD_TYPES=frozenset({'market_news','stock_news'})
CONTROLS=re.compile('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]')
RATING=r'(?:buy|sell|hold|neutral|overweight|underweight|outperform|underperform|equal[ -]weight|market[ -]perform|קנייה|קניה|מכירה|החזק|ניטרלי|תשואת יתר|תשואת חסר)'


def enabled():
    return os.getenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','false').lower()=='true'


def is_analyst_update(title, excerpt=''):
    """An actual rating/coverage/price-target action in the factual headline.

    An excerpt supplies financial context only; a model interpretation buried
    below a different headline cannot promote an unrelated story. No broker
    whitelist or sentiment/price prediction is inferred.
    """
    if not isinstance(title,str):return False
    text=CONTROLS.sub('',title)[:6000]
    text=re.split(r'משמעות אפשרית לסוחר\s*\(AI\):|פרשנות AI:',text,maxsplit=1)[0]
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if not lines:return False
    headline=next((line.split('כותרת:',1)[1] for line in lines if line.startswith('כותרת:')),lines[0])
    if (re.search(r'\b(?:could|might|may|would|will|should|potential|expects? to)\b|\?|ייתכן|עשוי|צפוי|האם',headline,re.I)
            or re.search(r'\b(?:my|our) (?:trade|trading|target)|\b(?:trading plan|entry target|take profit|buy zone|stop[ -]loss)\b|תוכנית מסחר|יעד הכניסה|הסטופ',headline,re.I)
            or re.search(r'\b(?:credit rating|government debt|sovereign|bond rating)\b|דירוג אשראי',headline,re.I)):
        return False
    # Price-target changes are explicit actions, not a static target or plan.
    adjusted=re.search(r'\badjust(?:s|ed)?\b.{0,100}\b(?P<label>price[ -]target|PT)\b.{0,90}\bto\s+'
        r'(?P<new_currency>(?:US|C|A)?[$€£])?\s*(?P<new>[0-9][0-9,]*(?:\.[0-9]+)?)\s+from\s+'
        r'(?P<old_currency>(?:US|C|A)?[$€£])?\s*(?P<old>[0-9][0-9,]*(?:\.[0-9]+)?)',headline,re.I)
    if adjusted and (adjusted['label'].lower()!='pt' or (adjusted['new_currency'] and adjusted['old_currency'])):
        # PT is accepted only with explicit monetary to/from values. A static
        # maintained rating may accompany a changed target, but is not a change.
        if Decimal(adjusted['new'].replace(',',''))!=Decimal(adjusted['old'].replace(',','')):return True
    target=r'(?:price[ -]targets?|מחיר(?:י)? ה?יעד)'
    change=r'(?:rais(?:e[sd]?|ing)|hikes?|boosts?|lift(?:s|ed)?|cut(?:s)?|lower(?:s|ed)?|reduc(?:e[sd]?|ing)|העל(?:ה|ו|תה)|הוריד(?:ה|ו)?|הפחית(?:ה|ו)?|הגדיל(?:ה|ו)?|מעלה|מוריד)'
    if re.search(change+r'.{0,100}'+target+'|'+target+r'.{0,35}(?:raised|cut|lowered|hiked|boosted|הועלה|הורד)',headline,re.I):
        return True
    # Explicit equity rating targets prevent software/operational upgrades.
    if re.search(r'\b(?:upgrad(?:es?|ed)|downgrad(?:es?|ed))\b.{0,120}\b(?:to|from)\s+[\"\x27]?'+RATING+r'\b',headline,re.I):return True
    if re.search(r'\binitiat(?:es?|ed)\s+(?:research\s+)?coverage\b.{0,120}\b(?:at|with)\s+(?:an?\s+)?[\"\x27]?'+RATING,headline,re.I):return True
    if re.search(r'(?:העלה|העלתה|הוריד|הורידה|שדרג|שדרגה|הפחית|מעלה|מוריד).{0,35}המלצ.{0,90}'+RATING,headline,re.I):return True
    if re.search(r'(?:החל|החלה).{0,15}לסקר.{0,90}המלצ.{0,20}'+RATING,headline,re.I):return True
    context=CONTROLS.sub('',excerpt)[:4000] if isinstance(excerpt,str) else ''
    if (re.search(r'\b(?:upgrad(?:es?|ed)|downgrad(?:es?|ed))\b',headline,re.I)
            and not re.search(r'\b(?:software|devices?|platform|cloud|infrastructure|credit)\b|תוכנה|מכשיר|דירוג אשראי',headline,re.I)
            and re.search(r'\b(?:stock|equity|share) (?:rating|recommendation)\b',context,re.I)
            and re.search(r'\b(?:to|from)\s+[\"\x27]?'+RATING+r'\b',context,re.I)):
        return True
    return False


def analyst_event(event):
    if not isinstance(event,dict):return False
    return any(isinstance(s,dict) and s.get('title')==event.get('title')
               and is_analyst_update(s.get('title'),s.get('source_excerpt',''))
               for s in event.get('sources',[]))


def analyst_for_outbox(row):
    """Exact retained version only, after existing rights/freshness guards."""
    if not enabled() or row.get('event_type') not in BROAD_TYPES:return False
    from database import get_db_connection
    from news_events.control import state
    key=row.get('dedupe_key','')
    try:
        with get_db_connection() as c:
            control=state(c)
            if key.startswith('canonical:'):
                if control['mode']!='canonical':return False
                link=c.execute('SELECT * FROM ne_outbox WHERE dedupe_key=?',(key,)).fetchone()
                if (not link or link['epoch']!=control['epoch'] or
                        {'market_news':'market_news','important_stock_news':'stock_news'}.get(link['topic'])!=row['event_type']):return False
                event=c.execute('SELECT * FROM ne_events WHERE event_id=?',(link['event_id'],)).fetchone()
                if (not event or event['evidence_version']!=link['version'] or event['status']!='analyzed' or event['reason']):return False
                if not c.execute("SELECT 1 FROM ne_analysis WHERE event_id=? AND version=? AND status='done'",(link['event_id'],link['version'])).fetchone():return False
                return analyst_event(json.loads(event['body_json']))
            if control['mode']!='phase1':return False
            parts=key.split(':')
            if (len(parts) not in (3,4) or parts[0] not in ('market-news','stock-news') or not parts[1].isdigit()
                    or int(parts[1])<=0 or not re.fullmatch('[0-9a-f]{20}|[0-9a-f]{64}|v1',parts[2])
                    or (parts[0]=='market-news' and len(parts)!=3)
                    or (parts[0]=='stock-news' and (len(parts)!=4 or not parts[3]))
                    or {'market-news':'market_news','stock-news':'stock_news'}[parts[0]]!=row['event_type']):return False
            news=c.execute('SELECT * FROM scanner_news WHERE id=?',(int(parts[1]),)).fetchone()
            if not news:return False
            news=dict(news)
            audit=c.execute('SELECT content_version FROM news_publication_audit WHERE news_id=?',(news['id'],)).fetchone()
            version=audit['content_version'] if audit else news.get('content_hash') or 'v1'
            if (parts[2]!=version or news.get('analysis_status') not in ('analyzed','public_translated')
                    or news.get('analysis_error') or news.get('duplicate_of')):return False
            if parts[0]=='stock-news':
                from news_direction_routing import _tickers
                selected=parts[3].split(',');chosen=_tickers(selected)
                verified=_tickers(json.loads(news.get('verified_tickers_json') or 'null'))
                if not chosen or selected!=sorted(chosen) or not chosen<=verified:return False
            facts=json.loads(news.get('source_facts_json') or '{}')
            return is_analyst_update(news.get('title'),facts.get('source_excerpt','') if isinstance(facts,dict) else '')
    except (ValueError,TypeError,KeyError):return False


def prior_analyst_delivery(c,row):
    """Coalesce exact broad source/version/ticker audience, never personal."""
    key=row['dedupe_key'];peers=[]
    if key.startswith('canonical:'):
        link=c.execute('SELECT * FROM ne_outbox WHERE dedupe_key=?',(key,)).fetchone()
        if not link:return None
        def tickers(value):
            try:value=json.loads(value)
            except (TypeError,ValueError):return None
            return frozenset(value) if isinstance(value,list) and all(isinstance(t,str) for t in value) else None
        current=c.execute('SELECT tickers_json FROM ne_delivery WHERE event_id=? AND version=? AND topic=?',
                          (link['event_id'],link['version'],link['topic'])).fetchone()
        audience=tickers(current['tickers_json']) if current else None
        peers=c.execute('''SELECT o.*,n.topic,n.event_id AS peer_event_id,n.version AS peer_version
            FROM ne_outbox n JOIN scanner_telegram_outbox o ON o.dedupe_key=n.dedupe_key
            WHERE n.event_id=? AND n.version=? AND o.id!=? AND o.event_type IN ('market_news','stock_news') ORDER BY o.id LIMIT 33''',
            (link['event_id'],link['version'],row['id'])).fetchall()
        if key.startswith('canonical:general-v1:'):
            from news_events.general_news import publication_keys
            from telegram_topics import thread_id_for_event
            event=c.execute('SELECT body_json FROM ne_events WHERE event_id=?',(link['event_id'],)).fetchone()
            destinations={thread_id_for_event(kind) for kind in ('market_news','stock_news','analyst_update')}
            for name in ('TELEGRAM_POSITIVE_STOCK_NEWS_THREAD_ID','TELEGRAM_NEGATIVE_STOCK_NEWS_THREAD_ID'):
                try:
                    value=int(os.getenv(name,''))
                    if value>0:destinations.add(value)
                except (TypeError,ValueError):pass
            keys=sorted({k for destination in destinations for k in publication_keys(json.loads(event['body_json']),link['version'],
                        [os.getenv('TELEGRAM_CHAT_ID','').strip(),destination])}) if event else []
            if len(keys)>32:return 'analyst_update_peer_limit'
            if keys:
                peers=[*peers,*c.execute('''SELECT o.*,n.topic,n.event_id AS peer_event_id,n.version AS peer_version
                    FROM scanner_telegram_outbox o LEFT JOIN ne_outbox n ON n.dedupe_key=o.dedupe_key
                    WHERE o.id!=? AND o.event_type IN ('market_news','stock_news') AND o.dedupe_key IN ('''+
                    ','.join('?' for _ in keys)+') ORDER BY o.id LIMIT 33',(row['id'],*keys)).fetchall()]
        peers=sorted({p['id']:p for p in peers}.values(),key=lambda p:p['id'])
        if len(peers)>32:return 'analyst_update_peer_limit'
        if audience is None:return 'analyst_update_audience_unknown'
        matching=[]
        for peer in peers:
            route=c.execute('SELECT tickers_json FROM ne_delivery WHERE event_id=? AND version=? AND topic=?',
                            (peer['peer_event_id'],peer['peer_version'],peer['topic'])).fetchone()
            other=tickers(route['tickers_json']) if route else None
            if other is None:return 'analyst_update_audience_unknown'
            if other==audience:matching.append(peer)
        peers=matching
    else:
        parts=key.split(':')
        if len(parts) not in (3,4) or parts[0] not in ('market-news','stock-news'):return None
        peers=c.execute('''SELECT * FROM scanner_telegram_outbox WHERE id!=? AND event_type IN ('market_news','stock_news')
            AND (dedupe_key=? OR dedupe_key LIKE ? OR dedupe_key=?) ORDER BY id LIMIT 33''',
            (row['id'],'market-news:'+parts[1]+':'+parts[2],'stock-news:'+parts[1]+':'+parts[2]+':%',
             'stock-news:'+parts[1]+':'+parts[2])).fetchall()
        if len(peers)>32:return 'analyst_update_peer_limit'
        news=c.execute('SELECT verified_tickers_json FROM scanner_news WHERE id=?',(int(parts[1]),)).fetchone()
        try:verified=json.loads(news['verified_tickers_json'] or '[]') if news else []
        except (TypeError,ValueError):return 'analyst_update_audience_unknown'
        if not isinstance(verified,list) or any(not isinstance(t,str) for t in verified):return 'analyst_update_audience_unknown'
        def audience(k):
            p=k.split(':');return set(p[3].split(',')) if len(p)==4 else set(verified)
        peers=[p for p in peers if audience(p['dedupe_key'])==audience(key)]
    if len(peers)>32:return 'analyst_update_peer_limit'
    for p in peers:
        if p['status']=='sent':return 'analyst_update_already_sent'
        if p['status']=='sending' and p['id']<row['id']:return 'analyst_update_peer_delivery_unknown'
        try:error=json.loads(p['last_error'] or '{}')
        except (ValueError,TypeError):error={}
        if isinstance(error,dict) and (error.get('reason')=='delivery_unknown_manual_review'
                or (type(error.get('http_status')) is int and error['http_status']>=500)):
            return 'analyst_update_peer_delivery_unknown'
    return None
