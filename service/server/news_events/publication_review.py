"""Bounded original-fact comparisons for publication, never trading evidence.

Retrieval overlap only selects reviewer context; it cannot suppress a story.
Only actually-sent market evidence is compared, with no model call added.
"""
import json
import re
from datetime import timedelta
from decimal import Decimal

from .model import timestamp

STOP = frozenset('a an the and or to of in on at for with from is are was were '
                 'says said as by be that it this its over after before'.split())


def words(value):
    return set(re.findall(r'[a-z\u0590-\u05ff]{3,}', value.casefold()))-STOP


def evidence_text(event):
    return '\n'.join(v['text'] for v in event.get('normalized_evidence', [])
                     if isinstance(v, dict) and isinstance(v.get('text'), str))


def candidates(store, event, at):
    if event.get('event_type') != 'market' or event.get('tickers') or event.get('conflicts'):
        return []
    current = evidence_text(event)
    if not current or len(current) > 4000:
        return []  # Keep context bounded without truncating source facts.
    lo = timestamp(at-timedelta(hours=6))
    with store.transaction() as c:
        rows = c.execute("""SELECT o.id,o.sent_at,o.message,n.event_id,n.version,v.evidence_json,e.body_json
          FROM scanner_telegram_outbox o JOIN ne_outbox n ON n.dedupe_key=o.dedupe_key
          JOIN ne_versions v ON v.event_id=n.event_id AND v.version=n.version
          JOIN ne_events e ON e.event_id=n.event_id
          WHERE o.status='sent' AND o.event_type='market_news' AND o.sent_at>=? AND o.sent_at<=?
          AND e.evidence_version=n.version AND e.status='analyzed'
          AND (e.reason IS NULL OR e.reason NOT IN ('source_retracted','source_conflict'))
          AND n.event_id<>? ORDER BY o.sent_at DESC,o.id DESC LIMIT 60""",
          (lo,timestamp(at),event['event_id'])).fetchall()
    found=[];used=0;seen=set()
    for row in rows:
        identity=(row['event_id'],row['version'])
        if identity in seen:continue
        seen.add(identity)
        try:
            prior=json.loads(row['evidence_json'])
            published_at=json.loads(row['body_json'])['published_at']
            if timestamp(published_at)[:10]!=timestamp(event['published_at'])[:10]:continue
        except (ValueError,TypeError):continue
        except KeyError:continue
        if (not isinstance(prior,list) or not prior or
            any(not isinstance(v,dict) or not isinstance(v.get('text'),str) for v in prior)):
            continue
        text='\n'.join(v['text'] for v in prior)
        # Compare the immutable evidence version that was sent. Do not use a
        # later mutable source correction as if it had already been published.
        overlap=len(words(current)&words(text))
        if overlap<3 or len(text)>1000 or len(row['message'])>1600:continue
        found.append((overlap,dict(id=row['id'],event_id=row['event_id'],version=row['version'],
                                 sent_at=row['sent_at'],published_at=published_at,
                                 evidence=text,published_text=row['message'])))
    chosen=[]
    for _,item in sorted(found,key=lambda v:v[0],reverse=True):
        size=len(item['evidence'])+len(item['published_text'])
        if used+size>2400:continue
        chosen.append(item);used+=size
        if len(chosen)==4:break
    return chosen


def duplicate_reference(review, previous, event):
    """A reviewer verdict cannot discard a new quantity, period or correction."""
    if review.get('material_new_fact') is not False:return None
    match=next((v for v in previous if v['id']==review.get('duplicate_of')),None)
    if match is None:return None
    current=evidence_text(event)
    def numbers(value):
        return {Decimal(n.replace(',','')) for n in re.findall(r'(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?',value)}
    if not numbers(current)<=numbers(match['evidence']):return None
    if not numbers(current)<=numbers(match['published_text']):return None
    periods=lambda v:set(re.findall(r'\b(?:q[1-4]|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b',v.casefold()))
    if periods(current)-periods(match['evidence']):return None
    measures=(r'\btrimmed mean\b',r'\bweighted median\b',r'\ball groups\b',
              r'\b(?:qoq|q/q)\b',r'\b(?:yoy|yr/yr|y/y|year on year)\b',r'\b(?:mom|m/m)\b')
    if any(re.search(p,current,re.I) and not re.search(p,match['evidence'],re.I) for p in measures):return None
    if re.search(r'\b(?:revised|revision|correction|corrected|retract\w*)\b',current,re.I):return None
    markers=lambda v:set(re.findall(r'\b(?:not|no|never|may|might|could|will|if)\b',v.casefold()))
    if markers(current)!=markers(match['evidence']):return None
    return {k:match[k] for k in ('id','event_id','version')}
