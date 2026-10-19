"""Bounded discovery observations in the existing candidate journal, not trades."""
import json
from datetime import datetime, timezone

from entry_discovery import observation_summary


def record_observations(scan_id, observations):
    from database import get_db_connection
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        for observation in observations[:1000]:
            item = observation_summary(observation)
            raw = json.dumps(item, sort_keys=True, allow_nan=False)
            if len(raw.encode()) > 8192:
                item = {key: item[key] for key in ('ticker', 'baseline_detected', 'common_reasons',
                                                  'candidate_strategy_ids')}
                item['evidence_gap'] = 'discovery_observation_exceeds_8k'
                raw = json.dumps(item, sort_keys=True, allow_nan=False)
            # A replay of the same scan must not duplicate research observations.
            exists = conn.execute('''SELECT 1 FROM scanner_candidates
                WHERE scan_id=? AND ticker=? AND stage='entry_discovery' LIMIT 1''',
                (scan_id, observation['ticker'])).fetchone()
            if not exists:
                conn.execute('''INSERT INTO scanner_candidates
                    (scan_id,ticker,company,stage,status,reason,metrics_json,created_at)
                    VALUES(?,?,NULL,'entry_discovery','observed',NULL,?,?)''',
                    (scan_id, observation['ticker'], raw, now))
