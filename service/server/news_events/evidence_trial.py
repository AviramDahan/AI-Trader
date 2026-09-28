"""Offline evidence experiment. Not wired into production eligibility or routing.

Flags describe evidence availability, NOT truth, materiality or model confidence.
Canonical membership is supplied by the existing store; this never merges events.
"""
import re
from urllib.parse import urlsplit
from .eligibility import company_aliases
from .model import timestamp

FACTS = {
    'product': r'\b(?:starts?|launches?|begins?)\b.{0,90}\b(?:drone delivery pilot|production of|clinical trial)\b|\bships? redesigned engines\b',
    'guidance': r'\b(?:raises?|cuts?|lowers?|increases?)\b.{0,45}\b(?:guidance|store outlook|revenue outlook|profit outlook|FY\d* outlook)\b',
    'management': r'\b(?:appoints?|names?)\s+[A-Z][\w.-]+(?:\s+[A-Z][\w.-]+){1,3}\s+(?:as |its |new )*(?:CEO|CFO|COO|chief executive officer)\b',
    'buyback': r'\b(?:announces?|approves?|authorizes?)\b.{0,35}\$\s*\d[\d.,]*\s*(?:million|billion|[MB])\b.{0,30}\b(?:buyback|repurchase)\b',
    'insider_transaction': r'\b(?:counsel|officer|director|CEO|CFO|insider)\b.{0,70}\b(?:sells?|buys?)\b.{0,80}(?:\$\s*\d|\b\d[\d,]*\s+shares)',
    'analyst_rating': r'\b(?:upgrades?|downgrades?)\b.{0,90}\b(?:to|from)\s+(?:buy|sell|hold|outperform|underperform|overweight|underweight|neutral)\b',
    'price_target': r'\b(?:raises?|cuts?|lifts?|lowers?)\b.{0,60}\bprice target\b.{0,35}\$\s*\d',
    'customer_win': r'\b(?:wins?|secures?|awarded)\b.{0,80}\$\s*\d.{0,40}\b(?:contract|order)\b',
    'asset_sale': r'\bsells?\b.{0,80}\b(?:campus|division|assets)\b.{0,30}\$\s*\d',
}
NOISE = r'\b(?:could|might|should|rumou?r|why investors|ready for a big move|stocks? to buy|best stocks?|prediction)\b'


def assess(event):
    flags = {'verified_identity': bool(event.get('company_identity') and event.get('tickers')),
             'known_event_type': event.get('event_type') not in (None, '', 'unknown', 'market')}
    result = {'eligible': False, 'reason': '', 'flags': flags, 'evidence_used': []}
    def reject(reason):
        result['reason'] = reason
        return result
    if not flags['verified_identity']: return reject('identity_unverified')
    if not flags['known_event_type']: return reject('unknown_or_market_type')
    aliases = [a for i in event['company_identity'] for a in company_aliases(i['ticker'], i['company'])]
    usable = []
    for s in event.get('sources', []):
        try: timestamp(s['published_at'])
        except (ValueError, TypeError, KeyError): continue
        # Approved ingestion provenance is not independent verification of a claim.
        if not s.get('publisher') or s.get('rights') not in ('approved', 'internal_review'): continue
        if urlsplit(s.get('url', '')).scheme != 'https': continue
        body = s.get('title', '') + ' ' + s.get('source_excerpt', '')
        linked = any(re.search(r'(?<!\w)' + re.escape(a) + r'(?!\w)', body, re.I) for a in aliases)
        linked = linked or bool(set(s.get('tickers', [])) & set(event['tickers']))
        if not linked: continue
        if s.get('source_type') in ('social', 'relay', 'social/relay') or s.get('provider_id') == 'telegram_channels': continue
        # Title-only Investing cannot self-supply corroborating evidence.
        if s.get('provider_id') == 'investing' and not s.get('source_excerpt'): continue
        usable.append(s)
    flags['eligible_source_count'] = len(usable)
    flags['distinct_source_urls'] = len({s.get('url') for s in usable})
    flags['source_excerpt'] = any(s.get('source_excerpt') for s in usable)
    flags['structured_metadata'] = any(s.get('tickers') or s.get('cik') or s.get('raw_metadata', {}).get('subjects') for s in usable)
    flags['official_regulatory_evidence'] = any(s.get('cik') and s.get('source_type') in ('official/regulatory', 'regulatory', 'official') for s in usable)
    if not usable: return reject('no_usable_company_linked_evidence')
    # Evaluate complete factual clauses, not arbitrary fragments joined into facts.
    for s in usable:
        clauses = [(field,s.get(field,'')) for field in ('title','source_excerpt')]
        # Structured values are usable only when their quote and value are
        # actually present in the retained source text. No metadata-only facts.
        retained = s.get('title','')+' '+s.get('source_excerpt','')
        for claim in s.get('claims',{}).values():
            if not isinstance(claim,dict): continue
            quote,value=claim.get('quote',''),str(claim.get('value',''))
            if quote and value and quote in retained and value in quote:
                clauses.append(('grounded_claim',quote))
        for field,value in clauses:
            if not value or '?' in value or re.search(NOISE, value, re.I): continue
            pattern = FACTS.get(event['event_type'])
            if not pattern or not re.search(pattern, value, re.I): continue
            flags['concrete_factual_event'] = True
            flags['numeric_fact'] = bool(re.search(r'\d', value))
            flags['context'] = 'publication_timestamp_and_specific_event'
            result.update(eligible=True, reason='FACTUAL_MINIMUM_EVIDENCE', evidence_used=[{
                'provider': s['provider_id'], 'url': s['url'], 'field': field, 'text': value}])
            return result
    return reject('no_specific_factual_clause_or_missing_event_detail')
