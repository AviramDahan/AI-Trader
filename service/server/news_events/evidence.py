"""Source-neutral SEC evidence, isolated cache; never calls Phase 1 prepare()."""
from datetime import datetime, timezone
import re
from .model import Source, fingerprint, timestamp
from .providers import ProviderFailure


class SECEvidence:
    provider_id='sec_evidence'

    def __init__(self,user_agent,fetcher=None,clock=None):
        from news_evidence import fetch_filing
        self.fetcher=fetcher or fetch_filing
        self.user_agent=user_agent
        self.clock=clock or (lambda:datetime.now(timezone.utc))

    def target(self,event):
        from news_evidence import filing_url, EvidenceError
        found={}
        for s in event['sources']:
            for url in (s['url'],*s.get('event_refs',[])):
                try:cik,accession,_=filing_url(url)
                except EvidenceError:continue
                # Require scanner identity CIK, not merely a company-name guess.
                if cik in event['cik']:
                    found.setdefault((cik,accession),url)
        return next(iter(found.values())) if len(found)==1 else None

    def can_handle(self,event):return bool(event['tickers'] and self.target(event))

    def cache_key(self,event):
        return fingerprint(['sec-extract-v1',self.target(event),sorted(event['tickers'])])

    def fetch_evidence(self,event):
        from news_evidence import EvidenceError
        try:
            content,url=self.fetcher(self.target(event),self.user_agent)
            return {'content':content,'url':url}
        except EvidenceError as exc:
            raise ProviderFailure(exc.reason,exc.status,exc.delay,not exc.transient) from None

    def normalize_evidence(self,raw,event):
        from news_evidence import extract, filing_url
        parsed=extract(raw['content'],raw['url'],event['tickers'])
        if filing_url(raw['url'])[:2]!=filing_url(self.target(event))[:2]:
            raise ProviderFailure('sec_event_mismatch',terminal=True)
        claims={}
        for n,line in enumerate(parsed['selected_excerpt'].splitlines()):
            if not line.startswith('security:'):continue
            for label,value in re.findall(r'(?:^|; )([^:;]+): ([^;]*)',line):
                if value:
                    claims[f"{parsed['accession']}:transaction:{n}:{label}"]={'value':value,'quote':line}
        # Filing content does not supply publication time. Preserve discovery's
        # original publication time and label this origin, never rejuvenate news.
        return Source(self.provider_id,parsed['accession'],raw['url'],'SEC EDGAR',
            event['published_at'],timestamp(self.clock()),event['title'],parsed['selected_excerpt'],
            'official/regulatory',(parsed['ticker'],),parsed['issuer_cik'],event['event_type'],
            (self.target(event),),claims, {'accession':parsed['accession'],
                'publication_time_origin':'discovery_source','extraction':'excerpt_only',
                'content_version':parsed['content_version']},'approved')

    def validate_identity(self,evidence,event):
        return evidence.cik in event['cik'] and set(evidence.tickers)<=set(event['tickers'])
