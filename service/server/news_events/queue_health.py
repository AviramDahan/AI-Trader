"""Age of continuous runnable work, not age of the original news story."""
import json
from datetime import datetime
from .model import timestamp

ACTIVE = ('pending', 'analyzing')


def entered_at(row):
    body = json.loads(row['body_json'])
    # Older releases have no queue clock. Evidence-version time is immutable;
    # updated_at/collection time would let repeated polls hide a stuck job.
    candidates = (body.get('queue_entered_at'), row.get('version_created_at'), row['created_at'])
    for value in candidates:
        try:
            return timestamp(value)
        except (ValueError, TypeError):
            continue
    raise ValueError('queue_timestamp_missing')


def queue_rows(c):
    return [dict(r) for r in c.execute("""SELECT e.*,v.created_at AS version_created_at
        FROM ne_events e LEFT JOIN ne_versions v
        ON v.event_id=e.event_id AND v.version=e.evidence_version
        WHERE e.status IN ('pending','analyzing')""")]


def summarize(rows, now):
    entries = [(max(0, (now-datetime.fromisoformat(entered_at(r))).total_seconds()), r)
               for r in rows if r['status'] in ACTIVE]
    oldest = max(entries, key=lambda item: item[0]) if entries else None
    return dict(queue_size=len(entries), oldest_queue_seconds=oldest[0] if oldest else 0,
                oldest_queue_event_id=oldest[1]['event_id'] if oldest else None,
                oldest_queue_entered_at=entered_at(oldest[1]) if oldest else None,
                queue_age_basis='continuous_pending_or_analyzing')
