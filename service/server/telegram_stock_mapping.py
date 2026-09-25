"""Conservative source-text identity matching, never LLM-inferred tickers."""
import re
from functools import lru_cache


@lru_cache(maxsize=4096)
def _pattern(expression, flags=0):
    return re.compile(expression, flags)

# Reviewed distinctive identities. Common words such as Apple, Meta, Strategy,
# Target and Amazon deliberately require an explicit symbol or full legal name.
ALIASES = {
    'INTC': ('Intel',), 'NVDA': ('Nvidia',), 'MSFT': ('Microsoft',),
    'CRWD': ('CrowdStrike',), 'DELL': ('Dell Technologies',),
    'ANET': ('Arista Networks',), 'MRVL': ('Marvell',),
    'HPE': ('Hewlett Packard Enterprise',), 'HCA': ('HCA Healthcare',),
    'HOOD': ('Robinhood',), 'MSTR': ('MicroStrategy',),
    'TSLA': ('Tesla',), 'AVGO': ('Broadcom',),
}


def match_stocks(text, companies):
    # Links and channel signatures are not evidence of company involvement.
    text = re.sub(r'https?://\S+|@[A-Za-z0-9_]+', ' ', text)
    evidence = {}
    for ticker, company in companies.items():
        symbol = re.escape(ticker).replace(r'\-', r'[.-]')
        explicit = _pattern(r'(?<!\w)(?:\$|NASDAQ\s*:\s*|NYSE\s*:\s*)('+symbol+r')(?!\w|[.-]\w)').search(text)
        if explicit:
            evidence[ticker] = explicit.group(0)
            continue
        names = list(ALIASES.get(ticker, ()))
        # Require a multiword full identity; no first-word or substring matching.
        if company and len(company.split()) >= 2 and not re.search(r'[()]',company):
            names.append(company.rstrip('.'))
        for name in names:
            match = _pattern(r'(?<!\w)'+re.escape(name)+r'(?!\w)', re.I).search(text)
            if match:
                evidence[ticker] = match.group(0)
                break
    return evidence
