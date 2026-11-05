"""Optional public-feed editorial floor from original source facts only.

Not an investment score, AI substitute, trading gate or factual verification.
Unknown importance is held for public delivery, never turned into a fake zero.
Personal alerts and specialist feeds retain their own existing policies.
"""
import json
import math
import os
import re


def enabled():
    return os.getenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','false').lower()=='true'


def source_importance(title, excerpt=''):
    """Bounded factual source classifier; translated/AI summaries are excluded."""
    from news_analyst_routing import is_analyst_update
    from news_report_routing import is_company_report
    title=title if isinstance(title,str) else ''
    excerpt=excerpt if isinstance(excerpt,str) else ''
    title=re.sub(r'\s+',' ',title).strip()[:2000]
    # An occurrence must be explicit in the headline. Risk-factor/marketing
    # boilerplate in a body is not evidence that an event actually happened.
    body=title
    if not title:return False,'public_quality_source_missing'
    # Reject opinion/promotion in the headline even if a boilerplate excerpt
    # mentions financial results. Actual analyst actions are handled separately.
    if '?' in title or re.search(r'\b(?:\d+ (?:best )?stocks? to (?:buy|sell|watch)|stocks? (?:you )?should buy|'
                 r'could .{0,70}(?:climb|double|soar|rally)|(?:why|will|can) .{0,80}stock.{0,40}(?:double|soar)|'
                 r'(?:could|might) .{0,50}(?:stock|market).{0,30}(?:rise|fall)|'
                 r'(?:my|our) (?:top picks|trade ideas)|going to boom)\b|'
                 r'האם.{0,50}מני|מניות שכדאי לקנות',title,re.I):
        return False,'public_quality_opinion_or_promotion'
    if re.search(r'\b(?:earnings preview|earnings calendar|earnings call transcript|'
                 r'(?:conference|earnings) call highlights|what to expect|will report|'
                 r'announces? (?:the )?(?:earnings|results) date|'
                 r'(?:financial results|earnings) conference|schedule for|annual meeting notice)\b|לוח דוחות|לקראת הדוחות',title,re.I):
        return False,'public_quality_preview_or_recap'
    if is_analyst_update(title,excerpt):return True,None
    # A body-only report needs an explicit actual-period/result clause under
    # the report classifier, never a forward-looking disclaimer.
    if is_company_report(title,excerpt):return True,None
    # Explicit developments, not generic launch/partnership marketing or a
    # large percentage in an editorial forecast. No full-article requirement.
    patterns=(
        r'\b(?:guidance|outlook|forecast)\b.{0,60}\b(?:rais\w*|cut\w*|lower\w*|withdraw\w*|reaffirm\w*)\b|'
        r'\b(?:rais(?:e[sd]?|ing)|cuts?|lower(?:s|ed)?|withdr(?:aws?|awn|ew)|reaffirm(?:s|ed)?)\b.{0,60}\b(?:guidance|outlook|revenue outlook|profit forecast)\b',
        r'\b(?:stops?|stopped|suspends?)\b.{0,30}\b(?:giving )?guidance\b',
        r'\b(?:sales|revenue|profit|production|deliveries)\b.{0,35}\b(?:drops?|falls?|rises?|declines?|increases?|down|up)\b.{0,25}(?:\d|zero)',
        r'\b(?:wins?|awarded|signs?|secures?)\b.{0,90}\b(?:contract|order)\b.{0,50}(?:\$|million|billion)|'
        r'\b(?:contract|order)\b.{0,50}(?:\$|million|billion)|'
        r'\b(?:wins?|awarded|signs?|secures?)\b.{0,30}(?:\$|million|billion).{0,50}\b(?:contract|order)\b',
        r'\b(?:FDA|EMA|regulator|court|DOJ|FTC|SEC|antitrust)\b.{0,100}\b(?:approves?|approved|rejects?|rejected|blocks?|blocked|sues?|sued|charges?|charged|investigates?|investigation|fines?|fined|rules?|ruled)\b',
        r'\b(?:phase [123]|clinical|trial)\b.{0,90}\b(?:meets?|misses?|fails?|improv\w*|endpoint|results)\b',
        r'\b(?:recalls?)\b.{0,60}\b(?:products?|devices?|vehicles?|cars?|safety|fault\w*)\b|'
        r'\b(?:reports?|discloses?|suffers?|confirms?|files? for|announces?)\b.{0,60}\b(?:data breach|cyberattack|bankruptcy|default|layoffs?|restructuring)\b|'
        r'\b(?:cutting|cuts?|eliminates?)\b.{0,30}\b(?:jobs|workforce)\b',
        r'\b(?:acquisition|merger|takeover|buyout)\b.{0,90}(?:\$|million|billion|agrees?|approv\w*|complet\w*)|'
        r'\bagrees? to (?:buy|acquire|merge)\b',
        r'\b(?:share offering|stock offering|debt issuance|dividend|buyback)\b.{0,70}(?:\$|million|billion|raises?|cuts?|suspends?|announces?)|'
        r'\b(?:raises?|cuts?|suspends?|announces?)\b.{0,60}\b(?:dividend|buyback)\b',
        r'\b(?:Federal Reserve|Fed|ECB|central bank)\b.{0,40}\b(?:holds?|raises?|cuts?|keeps?|leaves?|hikes?|lowers?|increases?)\b.{0,35}\b(?:rates?|bond purchases)\b',
        r'\b(?:CPI|PPI|PCE|GDP|payrolls?|jobless claims|unemployment|retail sales|inflation)\b.{0,90}(?:\d|rises?|falls?|increases?|declines?)',
        r'\b(?:S&P ?500|Nasdaq|Dow|Treasury yields?|credit.default swaps?|CDS|oil|gold|crude)\b.{0,80}\b(?:rises?|falls?|drops?|gains?|jumps?|surges?|widens?|widening|climbs?|down|up)\b.{0,35}\d',
        r'\b(?:announces?|imposes?|removes?|proposes?|approves?|suspends?)\b.{0,80}\b(?:tariffs?|sanctions?|export (?:ban|controls?)|interest rates?)\b',
        r'העל.{0,30}תחזית|הוריד.{0,30}תחזית|ריבית|מכסים|תוצאות ניסוי|אישר.{0,30}תרופה|פיטור|רכישה.{0,30}(?:מיליון|מיליארד)',
    )
    if any(re.search(p,body,re.I) for p in patterns):return True,None
    return False,'public_quality_importance_not_established'


def row_publication_check(row):
    if not enabled():return True,None
    from news_quality import source_facts
    facts=source_facts(row)
    return source_importance(facts['title'],facts['source_excerpt'])


def event_publication_check(event):
    if not enabled():return True,None
    # Current event headline/excerpt, not a stale attached source title.
    return source_importance(event.get('title'),event.get('source_excerpt',''))


def outbox_publication_check(row):
    """Recheck retained pending public messages; never replay/rewrite sent keys."""
    if not enabled() or row.get('event_type') not in ('stock_news','market_news'):return True,None
    from database import get_db_connection
    from news_events.control import state
    key=row.get('dedupe_key','')
    try:
        with get_db_connection() as c:
            control=state(c)
            if key.startswith('canonical:'):
                # runtime.delivery_message already reapplies engine.route for
                # exact current analyzed version, rights, epoch and membership.
                return True,None
            parts=key.split(':')
            if (control['mode']!='phase1' or len(parts) not in (3,4)
                    or parts[0] not in ('stock-news','market-news') or not parts[1].isdigit()
                    or parts[0]!={'stock_news':'stock-news','market_news':'market-news'}[row['event_type']]
                    or int(parts[1])<=0 or not re.fullmatch(r'(?:[0-9a-f]{20}|[0-9a-f]{64}|v1)',parts[2])
                    or (parts[0]=='market-news' and len(parts)!=3)
                    or (parts[0]=='stock-news' and (len(parts)!=4 or not parts[3]))):
                return False,'public_quality_source_version_unverified'
            record=c.execute('SELECT * FROM scanner_news WHERE id=?',(int(parts[1]),)).fetchone()
            if not record:return False,'public_quality_source_version_unverified'
            record=dict(record)
            if row['event_type']=='stock_news':
                selected=parts[3].split(',')
                verified=json.loads(record.get('verified_tickers_json') or 'null')
                if (not isinstance(verified,list) or not verified
                        or any(not isinstance(t,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',t) for t in verified)
                        or selected!=sorted(set(selected)) or not set(selected)<=set(verified)):
                    return False,'public_quality_source_version_unverified'
            audit=c.execute('SELECT content_version FROM news_publication_audit WHERE news_id=?',(record['id'],)).fetchone()
            version=audit['content_version'] if audit else record.get('content_hash') or 'v1'
            if (parts[2]!=version or record.get('analysis_status') not in ('analyzed','public_translated')
                    or record.get('analysis_error') or record.get('duplicate_of')):
                return False,'public_quality_source_version_unverified'
            if record['analysis_status']!='public_translated':
                from news_pipeline import feed_settings, _float_env
                relevance=record.get('relevance')
                minimum=(max(.80,feed_settings()['broad_alert_min_relevance']) if row['event_type']=='stock_news'
                    else max(.55,_float_env('STOCK_SCANNER_GENERAL_NEWS_MIN_RELEVANCE',.3,.3,1)))
                if (type(relevance) not in (int,float) or not math.isfinite(relevance)
                        or not minimum<=relevance<=1 or record.get('materiality') not in ('medium','high')):
                    return False,'public_quality_below_public_threshold'
            return row_publication_check(record)
    except (ValueError,TypeError,KeyError):return False,'public_quality_source_version_unverified'
