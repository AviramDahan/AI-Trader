"""Optional destination hint from already-reviewed, exact-version stock news.

No admission, text inference, model call, publication or persisted-key mutation.
Unknown evidence stays General; existing publisher/delivery guards remain first.
"""
import json
import math
import os
import re


def enabled():
    return os.getenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','false').lower() == 'true'


def _tickers(value):
    if (not isinstance(value,list) or not value or
            any(not isinstance(t,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',t) for t in value)
            or len(set(value)) != len(value)):
        return set()
    return set(value)


def _direction(result):
    if not isinstance(result,dict) or result.get('_public_translation_only'):
        return None
    relevance=result.get('relevance')
    if (result.get('related') is not True or type(relevance) not in (int,float)
            or not math.isfinite(relevance) or not 0 <= relevance <= 1
            or result.get('materiality') not in ('medium','high')):
        return None
    return result.get('sentiment') if result.get('sentiment') in ('positive','negative') else None


def direction_for_result(event, result):
    """Canonical completed analysis only; callers must verify version/status."""
    if not isinstance(event,dict):return None
    tickers=_tickers(event.get('tickers'))
    from news_public_importance import enabled as strict_public_quality
    if strict_public_quality() and len(tickers) != 1:
        return None
    identities=event.get('company_identity')
    if not tickers or not isinstance(identities,list) or not identities:return None
    if any(not isinstance(identity,dict) for identity in identities):return None
    if _tickers([identity.get('ticker') for identity in identities]) != tickers:return None
    return _direction(result)


def direction_for_outbox(outbox):
    """Bounded retained-state lookup after ordinary dispatch guards.

    Audit content_version takes precedence over the legacy row's original
    source hash: an evidence-enriched analysis is a distinct reviewed version.
    No fallback to a newer/different analysis, including during restart.
    """
    if not enabled() or outbox.get('event_type') != 'stock_news':return None
    from database import get_db_connection
    from news_events.control import state
    key=outbox.get('dedupe_key','')
    try:
        with get_db_connection() as c:
            control=state(c)
            if key.startswith('canonical:'):
                if control['mode'] != 'canonical':return None
                link=c.execute('SELECT * FROM ne_outbox WHERE dedupe_key=?',(key,)).fetchone()
                if not link or link['topic'] != 'important_stock_news' or link['epoch'] != control['epoch']:return None
                record=c.execute('SELECT * FROM ne_events WHERE event_id=?',(link['event_id'],)).fetchone()
                if (not record or record['status'] != 'analyzed' or record['reason']
                        or record['evidence_version'] != link['version']):return None
                analysis=c.execute("SELECT result_json FROM ne_analysis WHERE event_id=? AND version=? AND status='done'",
                                   (link['event_id'],link['version'])).fetchone()
                if not analysis:return None
                return direction_for_result(json.loads(record['body_json']),json.loads(analysis['result_json']))
            if control['mode'] != 'phase1':return None
            parts=key.split(':')
            if (len(parts) != 4 or parts[0] != 'stock-news' or not parts[1].isdigit() or int(parts[1]) <= 0
                    or not re.fullmatch(r'[0-9a-f]{20}|[0-9a-f]{64}|v1',parts[2])):return None
            tickers=parts[3].split(',')
            selected=_tickers(tickers)
            if not selected or tickers != sorted(selected):return None
            from news_public_importance import enabled as strict_public_quality
            if strict_public_quality() and len(selected) != 1:return None
            record=c.execute('SELECT * FROM scanner_news WHERE id=?',(int(parts[1]),)).fetchone()
            if not record:return None
            record=dict(record)
            audit=c.execute('SELECT content_version FROM news_publication_audit WHERE news_id=?',(record['id'],)).fetchone()
            version=audit['content_version'] if audit else record.get('content_hash') or 'v1'
            if (version != parts[2] or record.get('analysis_status') != 'analyzed'
                    or record.get('quality_version') not in (2,3) or record.get('duplicate_of')
                    or record.get('analysis_error')):return None
            verified=_tickers(json.loads(record.get('verified_tickers_json') or 'null'))
            if not selected <= verified:return None
            return _direction({**record,'related':True})
    except (ValueError,TypeError,KeyError):
        return None  # Malformed retained provenance never acquires a direction.
