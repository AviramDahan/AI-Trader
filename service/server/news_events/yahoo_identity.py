"""Yahoo-only corroboration: structured hint AND primary headline subject."""
import re

REVIEWED = {'NVDA':('Nvidia',),'AAPL':('Apple',),'SBUX':('Starbucks',),
            'INTC':('Intel',),'ON':('Onsemi','ON Semiconductor'),
            'A':('Agilent Technologies',),'IT':('Gartner',)}
AMBIGUOUS = {'A','IT','ON','TGT','ALL','ARE','CAN','FOR','OR','SO','TO'}


def corroborate(source, ticker, company, cik):
    if ticker not in source.raw_metadata.get('provider_tickers',[]):return None
    title=source.title
    stem=re.sub(r'(?:,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|Ltd\.?|plc))+$','',company,flags=re.I).strip()
    names={company,stem,*REVIEWED.get(ticker,())}
    names={n for n in names if len(n)>=4 and (ticker not in AMBIGUOUS or len(n.split())>=2 or n in REVIEWED.get(ticker,()))}
    named='(?:'+'|'.join(re.escape(n) for n in sorted(names,key=len,reverse=True))+')' if names else r'(?!)'
    explicit=r'(?:\$|NASDAQ\s*:\s*|NYSE\s*:\s*)'+re.escape(ticker)+r'(?![A-Z0-9])'
    entity=r'(?:'+named+'|'+explicit+r')(?!\w)'
    # A leading company can still only describe the real subject (its rival,
    # supplier, etc.). Comparisons/roundups do not establish one primary issuer.
    if re.search(entity+r"(?:['’]s)?\s+(?:rival|competitor|supplier|customer)\b",title,re.I):return None
    if re.search(r'\b(?:vs\.?|versus)\b',title,re.I):return None
    primary=bool(re.search(r'^(?:(?:why|how|is|can|will|did)\s+)?'+entity,title,re.I))
    action=re.search(r'\b(?:upgrades?|downgrades?|raises?|cuts?|lifts?|adjusts?)\b',title,re.I)
    if action and re.search(r'\b(?:rating|price target|PT|upgrades?|downgrades?)\b',title,re.I):
        primary=bool(re.match(entity+r'\s*:',title,re.I) or re.search(entity,title[action.end():],re.I))
    if not primary:return None
    pair=bool(re.search(named+r'(?:\s+Companies)?\s*\('+re.escape(ticker)+r'\)',title,re.I))
    explicit_match=bool(re.search(explicit,title))
    matched_cik=bool(cik and source.cik and cik==source.cik.lstrip('0'))
    if not (re.search(named,title,re.I) or explicit_match or matched_cik):return None
    return 'cik' if matched_cik else 'exchange_ticker' if explicit_match else 'company_name_plus_parenthesized_ticker' if pair else 'verified_alias_plus_provider_ticker'
