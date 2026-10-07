"""Retry only the public projection of an already-durable scanner signal."""
import json
import logging
from datetime import datetime, timedelta, timezone

LOG = logging.getLogger(__name__)


def retry_pending(api):
    from database import get_db_connection, using_postgres
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute('SET TRANSACTION READ ONLY')
            conn.execute("SET LOCAL statement_timeout='5s'")
        else:
            conn.execute('PRAGMA query_only=ON')
        rows = conn.execute('''SELECT id,technical_json FROM scanner_signals
            WHERE external_signal_id IS NULL AND legacy_unverified=0 AND created_at>=?
            AND technical_json LIKE '%"_strategy_projection"%'
            ORDER BY id LIMIT 3''', ((datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(),)).fetchall()
    finally:
        conn.close()
    for row in rows:
        try:
            projection = json.loads(row['technical_json']).get('_strategy_projection')
            if isinstance(projection, dict):
                api('POST', '/signals/strategy', json=dict(projection, scanner_signal_id=row['id']))
        except Exception as exc:
            LOG.warning('signal_strategy_projection_retry_pending:%s:%s', row['id'], type(exc).__name__)
