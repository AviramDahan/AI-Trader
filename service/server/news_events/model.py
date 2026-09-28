"""Source-neutral identities and immutable evidence. No database/provider I/O."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Protocol
import hashlib
import html
import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def text(value):
    return ' '.join(html.unescape(re.sub('<[^>]*>', ' ', str(value or ''))).split())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def canonical_url(url):
    p = urlsplit(str(url))
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise ValueError('invalid_source_url')
    if p.port not in (None,80,443):
        raise ValueError('invalid_source_port')
    query = [(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in
             ('fbclid','gclid','ref','source','token','apikey','api_key','key','access_token')]
    return urlunsplit((p.scheme,p.hostname.lower(),p.path.rstrip('/'),urlencode(sorted(query)),''))


def timestamp(value):
    from email.utils import parsedate_to_datetime
    if isinstance(value,datetime):
        dt=value
    else:
        try: dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        except ValueError: dt=parsedate_to_datetime(str(value))
    if dt.tzinfo is None:
        raise ValueError('source_timezone_missing')
    return dt.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class Source:
    provider_id: str
    source_id: str
    url: str
    publisher: str
    published_at: str
    collected_at: str
    title: str
    source_excerpt: str
    source_type: str = 'aggregator'
    tickers: tuple = ()
    cik: str = ''
    event_type: str = 'unknown'
    event_refs: tuple = ()
    claims: dict = field(default_factory=dict)
    raw_metadata: dict = field(default_factory=dict)
    rights: str = 'review_required'

    def data(self):
        return asdict(self)


class NewsProvider(Protocol):
    provider_id: str
    def fetch(self, state, now): ...
    def normalize(self, raw, collected_at) -> Source: ...
    def canonical_url(self, raw) -> str: ...
    def source_timestamp(self, raw) -> str: ...
    def source_identity(self, raw) -> str: ...
    def raw_metadata(self, raw) -> dict: ...


class EvidenceProvider(Protocol):
    provider_id: str
    def can_handle(self, event) -> bool: ...
    def fetch_evidence(self, event): ...
    def normalize_evidence(self, raw, event): ...
    def validate_identity(self, evidence, event) -> bool: ...
    def cache_key(self, event) -> str: ...


class IdentityResolver:
    """Uses scanner union universe supplied by caller; no manual ticker list."""
    def __init__(self, universe):
        from .eligibility import company_aliases
        self.universe=universe
        aliases = {ticker: company_aliases(ticker, text(data.get('company') or data.get('name'))) for ticker, data in universe.items()}
        owners = {}
        for ticker, values in aliases.items():
            for value in values: owners.setdefault(value.lower(), set()).add(ticker)
        self.aliases = {ticker: [a for a in values if len(owners[a.lower()]) == 1] for ticker, values in aliases.items()}
        self.patterns = {}
        for ticker, data in universe.items():
            name = text(data.get('company') or data.get('name'))
            self.patterns[ticker] = (
                re.compile(r'(?:\$|NASDAQ\s*:\s*|NYSE\s*:\s*)'+re.escape(ticker)+r'(?![A-Z0-9])'),
                re.compile(r'(?<!\w)'+re.escape(name)+r'(?!\w)', re.I) if len(name.split()) >= 2 else None,
                [re.compile(r'(?<!\w)'+re.escape(a)+r'(?!\w)', re.I) for a in self.aliases[ticker]],
                [re.compile(r'(?<!\w)'+re.escape(a)+r'\s*\('+re.escape(ticker)+r'\)', re.I) for a in self.aliases[ticker]])

    def resolve(self, source):
        from .eligibility import primary_subject
        body=source.title+' '+source.source_excerpt
        folded=body.lower()
        result=[]
        for ticker, data in self.universe.items():
            name=text(data.get('company') or data.get('name'))
            cik=str(data.get('cik') or '').lstrip('0')
            explicit_pattern, name_pattern, alias_patterns, paired_patterns = self.patterns[ticker]
            explicit=bool(ticker in body and explicit_pattern.search(body))
            # A bare common word (e.g. "Apple" or "A") is not a legal-company
            # identity. Keep short-name discovery as a hint, never auto-verify.
            named=bool(name_pattern and name.lower() in folded and name_pattern.search(body))
            cik_match=bool(cik and source.cik and cik==source.cik.lstrip('0'))
            # Related tickers alone are discovery hints, not company verification.
            alias_match = any(a.lower() in folded and pattern.search(body) for a,pattern in zip(self.aliases[ticker],alias_patterns))
            paired = ticker.lower() in folded and any(a.lower() in folded and pattern.search(body) for a,pattern in zip(self.aliases[ticker],paired_patterns))
            supported = alias_match and ticker in source.tickers
            if explicit or named or cik_match or paired or supported:
                if not primary_subject(source,ticker,[name,*self.aliases[ticker]],cik_match):
                    continue
                basis = 'cik' if cik_match else 'exchange_ticker' if explicit else 'legal_name' if named else 'company_name_plus_parenthesized_ticker' if paired else 'verified_alias_plus_provider_ticker'
                result.append({'ticker':ticker,'company':name,'cik':cik,'basis':basis})
        return result


EVENT_PATTERNS=(('earnings',r'earnings|quarter.*results|financial results'),
    ('guidance',r'guidance|outlook'),('merger',r'acquisition|merger|acquire'),
    ('capital_return',r'dividend|share repurchase|buyback'),
    ('litigation',r'lawsuit|antitrust|settlement'),
    ('business_update',r'contract|partnership|product launch|layoff'),
    ('insider_transaction',r'Form 4|insider.*(?:sale|purchase)'),
    ('regulatory',r'FDA|regulatory|SEC filing|FORM [48]|\b4/A\b'),
    ('management',r'appoint.*(?:CEO|officer)|chief executive'),
    ('market',r'Federal Reserve|interest rates|inflation|nonfarm|CPI|FOMC|\bGDP\b|\bECB\b|'
              r'\bOPEC\b|\btariffs?\b|\bsanctions?\b|\bTreasury yields?\b|\bceasefire\b|'
              r'\btrade (?:deal|agreement|war)\b|\b(?:oil|gas) (?:prices?|supply)\b'))


def event_type(title, excerpt):
    from .eligibility import EXTENDED_EVENTS
    value=title+' '+excerpt
    for kind,pattern in EVENT_PATTERNS:
        if re.search(pattern,value,re.I):return kind
    for kind,pattern in EXTENDED_EVENTS:
        if re.search(pattern,value,re.I):return kind
    return 'unknown'


def anchors(source, identities):
    """No same-ticker/day or headline-similarity merges. Exact evidence only."""
    identity=','.join(sorted(v['ticker'] for v in identities)) or 'market'
    refs=[]
    for url in (source.url,*source.event_refs):
        try: url=canonical_url(url)
        except ValueError: continue
        # Home/category/quote links do not identify an event. References must be
        # explicit story/filing links, not every anchor in an HTML document.
        if url != canonical_url(source.url) and not strong_reference(url):continue
        match=re.search(r'/Archives/edgar/data/(\d+)/(\d{18})/',url)
        refs.append('sec:'+str(int(match[1]))+':'+match[2] if match and urlsplit(url).hostname=='www.sec.gov' else 'url:'+url)
    # Exact substantive source facts also recognize verbatim syndication.
    if len(source.source_excerpt.split())>=12:
        refs.append('facts:'+fingerprint(text(source.source_excerpt).lower()))
    return [fingerprint([identity,ref]) for ref in sorted(set(refs))]


def strong_reference(url):
    p=urlsplit(url)
    return bool(re.search(r'/Archives/edgar/data/\d+/\d{18}/',p.path) or
                re.search(r'/(?:news-release|news-releases|articles?)/.+\d{4,}',p.path) or
                re.search(r'/\d{4}/\d{2}/\d{2}/.+',p.path))
