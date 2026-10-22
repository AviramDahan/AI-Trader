"""News-only low-impact briefs. Pure checks; never assert impact or trading value."""
from .factual_evidence import factual_title, sufficient
from .model import canonical_url, timestamp


def source(event):
    """A matching approved original, not approval borrowed from another title."""
    for item in event.get('sources', []):
        if (item.get('rights') != 'approved' or not isinstance(item.get('publisher'),str)
                or not item['publisher']
                or item.get('title') != event.get('title')):
            continue
        try:
            url = canonical_url(item['url'])
            timestamp(item['published_at'])
            if len(url) <= 1000 and len(item['publisher']) <= 160:
                return {**item, 'url': url}
        except (KeyError, TypeError, ValueError):
            continue
    return None


def eligible(event, result):
    """Called by the common route at queue AND dispatch, after reviewed analysis.

    This never widens company routing or bypasses the outer age/epoch/version,
    rights/conflict, relevance or independent quality-review gates.
    """
    if (result.get('materiality') != 'low' or result.get('related') is not True
            or event.get('event_type') != 'market' or event.get('tickers')
            or event.get('company_identity') or event.get('conflicts')):
        return False
    try:
        sources = event.get('sources', [])
        if not sources or any(s.get('rights') != 'approved' or s.get('cik')
                or s.get('tickers') or s.get('raw_metadata', {}).get('provider_tickers')
                for s in sources):
            return False
        # Keep the WHOLE reviewed text, not a truncation that can drop qualifiers.
        if not (isinstance(result['title_he'],str) and isinstance(result['summary_he'],str)
                and 0 < len(result['title_he'].strip()) <= len(result['title_he']) <= 240
                and 0 < len(result['summary_he'].strip()) <= len(result['summary_he']) <= 600):
            return False
        original=source(event)
        if not original:return False
        credits={s['publisher'] for s in sources if s.get('raw_metadata',{}).get('license_url')}
        licenses={s.get('raw_metadata',{}).get('license_label','')+' '+s['raw_metadata']['license_url']
                  for s in sources if s.get('raw_metadata',{}).get('license_url')}
        # Reserve header, separators, labels and publication time; never truncate
        # mandatory credits or a qualifier merely to fit Telegram's bound.
        size=(len(result['title_he'])+len(result['summary_he'])+len(original['publisher'])
              +len(original['url'])+sum(len(v)+4 for v in credits)
              +sum(len(v)+4 for v in licenses)+512)
        return bool(size<=4000 and factual_title(event) and sufficient(event))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
