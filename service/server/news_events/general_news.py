"""News publication is not verified stock attribution. No I/O or new AI calls."""
import re

from .factual_evidence import FACT, opinion
from .model import Source, canonical_url, text, timestamp, fingerprint


CORPORATE_EVENTS = frozenset({
    'regulatory', 'merger', 'analyst_action', 'financing', 'cybersecurity',
    'clinical', 'restructuring', 'business_update', 'management', 'earnings',
    'guidance', 'capital_return', 'litigation', 'insider_transaction',
})
GENERIC_SUBJECT = re.compile(r'^(?:(?:a|an|the)\s+)?(?:company|issuer|firm|business)\b', re.I)


def eligible_source(source):
    """A concrete source with actual context may enter GENERAL review only.

    Never manufacture an issuer/ticker, reclassify a company as macro, treat a
    hint as identity, or widen the headline-only factual-evidence exception.
    Twelve excerpt words are the existing minimum, NOT publication approval;
    factual/independent bilingual review and all downstream gates still apply.
    """
    try:
        headline = text(source.title) if isinstance(source, Source) else ''
        if (not isinstance(source, Source) or source.event_type not in CORPORATE_EVENTS
                or source.rights != 'approved' or not isinstance(source.publisher, str)
                or not text(source.publisher) or not isinstance(source.source_excerpt, str)
                or not isinstance(source.title, str) or opinion(headline)
                or GENERIC_SUBJECT.search(headline) or not FACT.search(headline)
                or re.search(r'\binducement grants?\b', headline, re.I)
                or len(text(source.source_excerpt).split()) < 12):
            return False
        canonical_url(source.url)
        timestamp(source.published_at)
        timestamp(source.collected_at)
        return True
    except (ValueError, TypeError, KeyError):
        return False


def eligible_sources(event):
    """Exact source matches only; also usable for verified-story dedupe."""
    if (not isinstance(event, dict) or not isinstance(event.get('event_type'), str)
            or event.get('event_type') not in CORPORATE_EVENTS
            or event.get('conflicts') or not isinstance(event.get('sources'), list)):
        return []
    sources = []
    for value in event['sources']:
        if not isinstance(value, dict) or value.get('title') != event.get('title'):
            continue
        if value.get('event_type') != event['event_type']:
            continue
        try:
            source = Source(**{k: v for k, v in value.items() if k in Source.__dataclass_fields__})
        except TypeError:
            continue
        if eligible_source(source):
            sources.append(source)
    return sources


def eligible_event(event):
    """Re-evaluate retained evidence at queue/send; no persistent bypass bit."""
    return bool(isinstance(event, dict)
                and all(event.get(key) == [] for key in ('tickers', 'company_identity', 'cik'))
                and eligible_sources(event))


def publication_keys(event, version, destination):
    """Exact evidence/time/destination dedupe, independent of ticker discovery.

    Version hashes exact normalized title/excerpt and grounded claims, not
    headline similarity. A URL/publisher/ticker change cannot multiply verbatim
    information. Changed facts/time/destination get different keys. This avoids
    an A -> [A,B] -> B source-alias bypass without merging canonical audits or
    maintaining historical aliases. URLs remain validated and attributed.
    """
    return sorted({'canonical:general-v1:' + fingerprint([
        timestamp(s.published_at), version, destination])
        for s in eligible_sources(event)})
