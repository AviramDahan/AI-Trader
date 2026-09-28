"""Deterministic news-only factual title gate; never infers missing facts."""
import re
from .model import Source, canonical_url, timestamp


def opinion(title):
    return bool('?' in title or re.search(
        r'^(?:why\b|how to\b|is\b|could\b|should\b|can\b|\d+\s+(?:best\s+)?stocks\b)|'
        r'\b(?:stocks to (?:buy|watch)|could explode|ready for a (?:rally|big move)|'
        r'investors should watch|best stock to own)\b', title, re.I))


FACT = re.compile(
    r'\b(?:upgrades?|downgrades?|raises?|cuts?|warns?|announces?|reports?|appoints?|'
    r'resigns?|launches?|wins?|secures?|signs?|acquires?|sells?|divests?|recalls?|'
    r'closes?|opens?|files?|approves?|rejects?|investigates?|settles?|halts?|'
    r'expands?|issues?|slashes?|restructures?|reduces?|increases?|extends?)\b|'
    r'\bto (?:close|open|cut|launch|acquire|sell|appoint|raise)\b|'
    r'\b(?:price target|data breach|cyberattack|bankruptcy|clinical trial results|'
    r'stock split|debt issuance|share offering|layoffs)\b|'
    r'\b(?:oil|gas|yields?|inflation|CPI|GDP|employment)\b.{0,45}'
    r'\b(?:rises?|falls?|above|below|hits?|drops?|increases?|declines?)\b', re.I)


def factual_title(event):
    if event.get('event_type') in (None, 'unknown'):return False
    if not event.get('tickers') and event['event_type'] != 'market':return False
    title=event.get('title','')
    if opinion(title) or not FACT.search(title):return False
    for source in event.get('sources',[]):
        if source.get('rights')!='approved' or not source.get('publisher'):continue
        # A different observation cannot lend its approval to this headline.
        if source.get('title')!=title:continue
        try:
            canonical_url(source['url']);timestamp(source['published_at'])
        except (ValueError,TypeError,KeyError):continue
        if event.get('tickers'):
            from .yahoo_identity import corroborate
            # Reuse the existing primary-subject guard, not a new identity.
            identities=event.get('company_identity',[])
            if not identities:continue
            candidate=Source(**{k:v for k,v in source.items() if k in Source.__dataclass_fields__})
            from dataclasses import replace
            candidate=replace(candidate,raw_metadata={'provider_tickers':event['tickers']})
            if not all(corroborate(candidate,i['ticker'],i['company'],i.get('cik','')) for i in identities):continue
        return True
    return False


def sufficient(event):
    if opinion(event.get('title','')):return False
    return bool(event.get('normalized_evidence')) and (
        any(len(s.get('source_excerpt','').split())>=12 for s in event.get('sources',[]))
        or factual_title(event))
