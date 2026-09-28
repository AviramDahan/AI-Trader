"""Deterministic news eligibility only; no I/O, model scoring or trading rules."""
import re

# Explicitly reviewed brand/legal-name differences; no inferred fuzzy aliases.
REVIEWED_ALIASES = {'NVDA': ('Nvidia',), 'AAPL': ('Apple',), 'MEDP': ('Medpace',),
                    'HOOD': ('Robinhood',), 'INTC': ('Intel',)}
AMBIGUOUS = {'A', 'IT', 'ON', 'TGT'}  # "price target" is not Target Corporation.


def company_aliases(ticker, name):
    stem = re.sub(r'(?:,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|Ltd\.?|plc))+$', '', name, flags=re.I).strip()
    values = {name, stem, *REVIEWED_ALIASES.get(ticker, ())}
    return {v for v in values if len(v) >= 4 and (ticker not in AMBIGUOUS or len(v.split()) >= 2)}


EXTENDED_EVENTS = (
    # Observed in the frozen September 28 audit; intentionally narrow actions.
    ('product', r'\bstarts?\b.{0,50}\bdrone delivery pilot\b|\bships? redesigned engines\b'),
    ('business_update', r'\bexpands? into\b.{0,70}\bwith\b.{0,50}\bdeal\b'),
    ('business_risk', r'\bwarns? of heightened\b.{0,40}\bcompetition\b'),
    ('asset_sale', r'\bsells? (?:its |the )?\w+ campus for\b'),
    ('analyst_rating', r'\b(?:upgrades?|downgrades?)\b.+\b(?:to|from|rating|stock|shares)\b'),
    ('price_target', r'\b(?:price target|target price)\b|\b(?:raises?|cuts?|lowers?|adjusts?)\b.+\bPT\b'),
    ('earnings_preview', r'\b(?:earnings|profit|revenue) (?:preview|estimates?|warning)\b'),
    ('customer_win', r'\b(?:wins?|secures?|awarded)\b.+\b(?:contract|customer|order)\b'),
    ('financing', r'\b(?:financing|stock offering|debt issuance|senior notes|credit facility)\b'),
    ('restructuring', r'\b(?:restructuring|bankruptcy|chapter 11)\b'),
    ('stock_split', r'\b(?:reverse[- ]split|stock split|split of (?:its )?stock)\b'),
    ('cybersecurity', r'\b(?:cyberattack|cybersecurity incident|data breach|ransomware)\b'),
    ('recall', r'\brecalls?\b.+\b(?:products?|vehicles?|units?|devices?|drugs?)\b'),
    ('operations', r'\bproduction update\b|\bsupply[- ]chain disruption\b|\b(?:factory|plant)\b.+\b(?:expansion|closure|close|expand)\b'),
    ('management', r'\b(?:CEO|CFO|COO|executive|chief\s+\w+\s+officer)\b.+\b(?:departs?|resigns?|retires?|steps down|appointed|appointment)\b|\b(?:appoints?|names?)\b.+\b(?:CEO|CFO|COO|officer)\b'),
    ('clinical', r'\bclinical trial\b.+\b(?:results?|meets?|misses?|endpoint)\b|\bFDA\b.+\b(?:approv|reject|milestone|clearance)\w*'),
    ('investigation', r'\b(?:regulatory|SEC|DOJ) investigation\b'),
    ('strategic_review', r'\b(?:strategic review|strategic alternatives|asset sale|divestiture)\b'),
    ('licensing', r'\blicensing (?:deal|agreement)\b'),
    ('insider_transaction', r'\b(?:CEO|CFO|COO|officer|director|general counsel|insider)\b.+\b(?:sells?|buys?|purchases?)\b.+\b(?:shares?|stock)\b'),
)


def primary_subject(source, ticker, aliases, cik_match=False):
    """Company mention is not subject identity. Fail closed on incidental mentions.

    Filing CIK is direct issuer identity; relatedTickers is not. Analyst-action
    headlines identify the rating target, never the bank merely issuing it.
    """
    if cik_match:
        return True
    title = source.title.strip()
    names = [re.escape(a) for a in aliases]
    names += [r'\$'+re.escape(ticker), r'(?:NASDAQ|NYSE)\s*:\s*'+re.escape(ticker)]
    entity = r'(?:'+'|'.join(names)+r')(?!\w)'
    action = re.search(r'\b(?:upgrades?|downgrades?|raises?|cuts?|lifts?|adjusts?)\b', title, re.I)
    analyst = action and re.search(r'\b(?:rating|price target|PT|upgrades?|downgrades?)\b', title, re.I)
    if analyst:
        # Subject followed by colon: "TD Synnex: Morgan Stanley lifts ...".
        if re.match(entity+r'\s*:', title, re.I):return True
        tail=title[action.end():]
        if re.search(entity, tail, re.I):return True
        return False
    prefix = r'^(?:(?:why|how|is|can|will|did)\s+)?'
    return bool(re.search(prefix+entity, title, re.I))


def sufficient_evidence(event):
    """Preserve existing long-excerpt path; allow concrete short combined facts.

    Identity/publication metadata establishes who/when, never invents what.
    Arbitrary provider metadata is not treated as a published fact. Structured
    claims count only with a verbatim source quote and a value in that quote.
    """
    sources = event.get('sources', [])
    if not event.get('normalized_evidence'):
        return False
    if any(len(s.get('source_excerpt', '').split()) >= 12 for s in sources):
        return True
    if not event.get('company_identity') or not event.get('tickers') or event.get('event_type') in (None, 'unknown', 'market'):
        return False
    from .model import timestamp
    try:
        timestamp(event['published_at'])
    except (KeyError, ValueError, TypeError):
        return False
    aliases = [a for i in event['company_identity'] for a in company_aliases(i['ticker'], i['company'])]
    verified_sources = [s for s in sources if any(re.search(r'(?<!\w)' + re.escape(a) + r'(?!\w)',
                       s.get('title', '')+' '+s.get('source_excerpt', ''), re.I) for a in aliases)]
    # The canonical store already joins event evidence. Only company-linked
    # observations may contribute to the new short-evidence path.
    shared_excerpt = ' '.join(dict.fromkeys(s.get('source_excerpt', '') for s in verified_sources))
    action = r'\b(?:announces?|reports?|wins?|secures?|awarded|raises?|cuts?|lowers?|upgrades?|downgrades?|appoints?|names?|sells?|buys?|files?|recalls?|confirms?|signs?|completes?|acquires?|approves?|rejects?|resigns?)\b'
    for source in sources:
        title = source.get('title', '')
        excerpt = shared_excerpt if source in verified_sources else source.get('source_excerpt', '')
        combined = title + ' ' + excerpt
        if '?' in title or re.search(r'\b(?:could|might|should|rumou?r|stocks? to buy|best stocks?|is it|what if)\b', title, re.I):
            continue
        if not re.search(action, combined, re.I):
            continue
        # At least one source must connect a verified company to the facts.
        if not any(re.search(r'(?<!\w)' + re.escape(a) + r'(?!\w)', combined, re.I) for a in aliases):
            continue
        title_words = set(re.findall(r'\w+', title.lower()))
        extra = set(re.findall(r'\w+', excerpt.lower())) - title_words
        numeric_fact = bool(re.search(r'(?:\$\s*\d|\b\d+(?:\.\d+)?\s*(?:million|billion|shares|units|%))', combined, re.I))
        grounded = any(isinstance(v, dict) and v.get('quote') and v['quote'] in combined
                       and str(v.get('value', '')) and str(v['value']) in v['quote']
                       for v in source.get('claims', {}).values())
        if len(combined.split()) >= 6 and (len(extra) >= 3 or numeric_fact or grounded):
            return True
    return False
