"""Bounded failure fingerprints of the causal input prefix, never raw OHLCV.

This is diagnostics, not input repair. Future/unconsumed rows must not be passed
by the detector. No tolerance, strategy rule or historical source is inferred.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone

VERSION = 'entry_input_failure_v1'
PREDICATES = frozenset({'invalid_ohlcv', 'invalid_market_session',
    'invalid_chronology', 'history_not_current', 'no_completed_bars',
    'invalid_history', 'NONPOSITIVE_OR_NONFINITE_OHLCV', 'OHLC_ORDER'})


def _clock(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('diagnostic_timezone_required')
    return at.astimezone(timezone.utc).isoformat()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {'invalid_type': type(value).__name__[:32]}
    if math.isnan(value):
        return {'nonfinite': 'nan'}
    if math.isinf(value):
        return {'nonfinite': 'positive_inf' if value > 0 else 'negative_inf'}
    return float(value)


def history_failure_metadata(consumed_rows, *, decision_at, source_observed_at, predicate):
    """Fingerprint only consumed, available rows through the first failure.

    Invalid/nonfinite numeric cells have explicit JSON tokens. The result does
    not expose the cells, price, ticker, free-form exception or frame attrs.
    Unknown original snapshots remain unknown; hashes cannot reconstruct them.
    """
    if predicate not in PREDICATES or not isinstance(consumed_rows, (list, tuple)) or len(consumed_rows) > 1024:
        raise ValueError('diagnostic_invalid_input')
    decision, observed = _clock(decision_at), _clock(source_observed_at)
    if datetime.fromisoformat(observed) > datetime.fromisoformat(decision):
        raise ValueError('diagnostic_future_source')
    prefix = []
    for row in consumed_rows:
        if not isinstance(row, dict):
            raise ValueError('diagnostic_invalid_row')
        day = date.fromisoformat(str(row['date'])).isoformat()
        available = _clock(row['available_at'])
        if datetime.fromisoformat(available) > min(datetime.fromisoformat(observed), datetime.fromisoformat(decision)):
            raise ValueError('diagnostic_future_row')
        prefix.append(dict(date=day, available_at=available,
            **{key: _number(row.get(key)) for key in ('open', 'high', 'low', 'close', 'volume')}))
    wire = json.dumps(prefix, sort_keys=True, allow_nan=False, separators=(',', ':')).encode('utf-8')
    return validate_metadata(dict(version=VERSION, predicate=predicate, source_observed_at=observed,
        decision_at=decision, consumed_rows=len(prefix),
        first_offending_session=prefix[-1]['date'] if prefix else None,
        hash_scope='CAUSAL_CONSUMED_PREFIX_THROUGH_FAILURE',
        consumed_prefix_sha256=hashlib.sha256(wire).hexdigest(),
        raw_values_retained=False, reconstructible=False))


def validate_metadata(value):
    fields = {'version', 'predicate', 'source_observed_at', 'decision_at',
        'consumed_rows', 'first_offending_session', 'hash_scope',
        'consumed_prefix_sha256', 'raw_values_retained', 'reconstructible'}
    if (not isinstance(value, dict) or set(value) != fields or value['version'] != VERSION or
            value['predicate'] not in PREDICATES or type(value['consumed_rows']) is not int or
            not 0 <= value['consumed_rows'] <= 1024 or
            value['hash_scope'] != 'CAUSAL_CONSUMED_PREFIX_THROUGH_FAILURE' or
            value['raw_values_retained'] is not False or value['reconstructible'] is not False or
            not isinstance(value['consumed_prefix_sha256'], str) or
            not re.fullmatch('[0-9a-f]{64}', value['consumed_prefix_sha256'])):
        raise ValueError('invalid_input_failure_metadata')
    if datetime.fromisoformat(_clock(value['source_observed_at'])) > datetime.fromisoformat(_clock(value['decision_at'])):
        raise ValueError('diagnostic_future_source')
    if value['consumed_rows']:
        date.fromisoformat(value['first_offending_session'])
    elif value['first_offending_session'] is not None:
        raise ValueError('diagnostic_invalid_session')
    return dict(value)
