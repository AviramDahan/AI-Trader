"""Read existing verified news evidence for signals; never ingest/analyze/publish.

Public-news routing scores are not signal-news eligibility. The final stock
review remains the veto. Source rights, identity, timestamps and conflicts are
checked independently and do not borrow approval from a different observation.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from news_events.model import Source, canonical_url, timestamp
from news_events.factual_evidence import sufficient
from news_events.yahoo_identity import corroborate

LOG = logging.getLogger(__name__)
MAX_EVENTS = 1000


def _time(value):
    return datetime.fromisoformat(timestamp(value))


def eligible_observations(record, candidate, max_age_hours, now):
    event = json.loads(record['body_json'])
    ticker = candidate['ticker']
    if (ticker not in event.get('tickers', []) or event.get('conflicts') or
            event.get('event_type') in (None, 'unknown', 'market') or
            record.get('reason') in {'source_conflict', 'source_retracted', 'license_required',
                'backlog_blocked', 'identity_unverified', 'unsupported_or_noise'}):
        return []
    if _time(record['created_at']) > now or _time(record['updated_at']) > now or not sufficient(event):
        return []
    identity = next((v for v in event.get('company_identity', []) if v.get('ticker') == ticker), None)
    if not identity or not event.get('sources') or any(s.get('rights') != 'approved' for s in event['sources']):
        return []
    result = []
    for value in event['sources']:
        source = Source(**{k:v for k,v in value.items() if k in Source.__dataclass_fields__})
        published, collected = _time(source.published_at), _time(source.collected_at)
        age = (now - published).total_seconds()/3600
        if not 0 <= age <= max_age_hours or collected > now:
            continue
        url = canonical_url(source.url)
        if not url.startswith('https://'):
            continue
        subject = replace(source, raw_metadata={'provider_tickers': [ticker]})
        basis = corroborate(subject, ticker, candidate['company'], identity.get('cik', ''))
        if not basis:
            continue
        row = dict(title=source.title[:300], publisher=source.publisher[:100], url=url,
            original_url=source.url, published_at=timestamp(published), age_hours=round(age, 2),
            relevance=round(min(1., .85+.15*max(0., 1-age/max_age_hours)), 3),
            relatedTickers=[ticker], canonical_event_id=record['event_id'],
            evidence_version=record.get('evidence_version'), identity_basis=basis,
            provenance=[dict(ingestion_provider=source.provider_id, publisher=source.publisher,
                original_url=source.url, published_at=timestamp(published), collected_at=timestamp(collected),
                rights=source.rights)])
        if source.source_excerpt.strip():
            row['source_excerpt'] = source.source_excerpt.strip()[:2000]
        result.append(row)
    return result


def existing_news(candidates, max_age_hours, now=None):
    """Bounded read-only snapshot, with no init/migration/provider/AI side effect."""
    from database import get_db_connection, using_postgres
    now = now or datetime.now(timezone.utc)
    result = {c['ticker']: [] for c in candidates}
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            conn.execute("SET LOCAL statement_timeout='8s'")
        else:
            conn.execute('PRAGMA query_only=ON')
        rows = conn.execute('''SELECT event_id,body_json,status,reason,evidence_version,created_at,updated_at
            FROM ne_events WHERE updated_at>=? AND updated_at<=? AND created_at<=? AND
            (status IN ('pending','analyzing','analyzed') OR (status='blocked' AND reason='stale_or_future'))
            ORDER BY updated_at DESC LIMIT ?''',
            ((now-timedelta(hours=max_age_hours)).isoformat(), now.isoformat(), now.isoformat(), MAX_EVENTS+1)).fetchall()
        if len(rows) > MAX_EVENTS:
            LOG.warning('signal_news_snapshot_clipped:%s', MAX_EVENTS)
        for row in rows[:MAX_EVENTS]:
            for candidate in candidates:
                try:
                    result[candidate['ticker']].extend(eligible_observations(dict(row), candidate, max_age_hours, now))
                except (ValueError, TypeError, KeyError, AttributeError):
                    # Malformed one event must not disable Yahoo or other events.
                    continue
        return {ticker: merge([], rows) for ticker, rows in result.items()}
    finally:
        conn.close()


def merge(yahoo, canonical):
    result, keys = [], {}
    for row in [*canonical, *yahoo]:
        try:
            key = ('url', canonical_url(row['url']))
        except (ValueError, KeyError):
            key = ('explicit_story', row.get('title'), row.get('published_at'))
        if key in keys:
            prior = keys[key]
            prior['provenance'] = prior.get('provenance', []) + row.get('provenance', [])
            if not prior.get('source_excerpt') and row.get('source_excerpt'):
                prior['source_excerpt'] = row['source_excerpt']
        else:
            item = dict(row)
            result.append(item); keys[key] = item
    result.sort(key=lambda r:r.get('published_at') or '', reverse=True)
    return result[:5]
