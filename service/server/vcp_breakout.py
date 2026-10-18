"""Default-OFF VCP confirmation for the existing BUY/SINGLE breakout only.

Pure market-data evaluation: no IO, database, AI, orders, sizing or exit policy.
Donor scores are descriptive, not probabilities or new ranking weights. Every
accepted plan must still pass the original structure, execution and risk gates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from vendor.vcp.vcp_pattern_calculator import calculate_vcp_pattern
from vendor.vcp.volume_pattern_calculator import calculate_volume_pattern
from vendor.vcp.execution_state import compute_execution_state
from vendor.vcp.pivot_proximity_calculator import calculate_pivot_proximity

VERSION = 'vcp_breakout_evidence_v1'
SOURCE_PIN = 'b29c6dfc2d4dc82bdfcfc13891e490863283405f'
MIN_BARS = 253  # 252 completed prior sessions plus the separate trigger session.
MAX_BARS = 1024
MAX_BYTES = 4096
ET = ZoneInfo('America/New_York')
UTC = timezone.utc
STATES = frozenset({'UNKNOWN', 'REJECTED', 'FORMING', 'CONFIRMED', 'OVEREXTENDED'})
REASONS = frozenset({'vcp_history_unavailable', 'vcp_history_oversized',
    'vcp_invalid_data', 'vcp_availability_unknown', 'vcp_future_availability',
    'vcp_insufficient_history', 'vcp_history_not_current', 'vcp_pattern_unconfirmed',
    'vcp_pivot_unavailable', 'vcp_pivot_unconfirmed', 'vcp_volume_not_dry',
    'vcp_trigger_not_confirmed', 'vcp_trigger_volume_unconfirmed',
    'vcp_overextended', 'vcp_trend_damaged', 'vcp_quote_unavailable',
    'vcp_quote_not_fresh', 'vcp_evidence_invalid', 'vcp_calculation_failed'})


def enabled():
    return os.getenv('STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED', 'false').lower() == 'true'


def _instant(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError('invalid time')
        return datetime.fromtimestamp(value, UTC)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('time requires timezone')
    return parsed.astimezone(UTC)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _market_available(day):
    return datetime.combine(day, time(16, 5), ET).astimezone(UTC)


def _finish(evidence, state, reason=None):
    evidence.update(state=state, reasons=[reason] if reason else [])
    encoded = json.dumps(evidence, allow_nan=False, sort_keys=True, separators=(',', ':'))
    if len(encoded.encode()) > MAX_BYTES:
        raise ValueError('vcp_evidence_invalid')
    return json.loads(encoded)


def _execution(features, price):
    # The donor's stop proposal is deliberately not passed through or used.
    proximity = calculate_pivot_proximity(price, features['pivot_price'],
                                         breakout_volume=features['trigger_volume_confirmed'])
    raw_distance = (price / features['pivot_price'] - 1) * 100
    state = compute_execution_state(raw_distance, price, features['sma50'], features['sma200'],
        (price / features['sma200'] - 1) * 100, features['last_contraction_low'],
        features['trigger_volume_confirmed'])
    return state['state'], raw_distance, proximity['score']


def evaluate(frame, *, decision_at, source_observed_at=None, expected_session=None):
    """Evaluate completed as-of daily OHLCV; the last bar is NOT part of the base.

    Global source observation and optional per-row ``available_at`` are input
    provenance, never replaced by today's download time. A missing clock or
    warmup returns UNKNOWN, not a weak/positive VCP. The conservative pivot
    confirmation bound is the end of its prior prefix, not a claimed exact
    historical first-seen timestamp. No historical order/fill is reconstructed.
    """
    evidence = dict(version=VERSION, source_pin=SOURCE_PIN, state='UNKNOWN', reasons=[],
                    decision_at=None, source_data_at=None, source_observed_at=None,
                    effective_available_at=None, pivot_confirmed_at=None,
                    coverage=dict(completed_bars=0, required_bars=MIN_BARS, status='UNKNOWN'),
                    features={})
    try:
        decision = _instant(decision_at)
        evidence['decision_at'] = decision.isoformat()
        if frame is None or not hasattr(frame, 'iterrows') or frame.empty:
            return _finish(evidence, 'UNKNOWN', 'vcp_history_unavailable')
        if len(frame) > MAX_BARS:
            return _finish(evidence, 'UNKNOWN', 'vcp_history_oversized')
        observed_value = source_observed_at if source_observed_at is not None else frame.attrs.get('history_fetched_at')
        if observed_value is None:
            return _finish(evidence, 'UNKNOWN', 'vcp_availability_unknown')
        observed = _instant(observed_value)
        evidence['source_observed_at'] = observed.isoformat()
        if observed > decision:
            return _finish(evidence, 'UNKNOWN', 'vcp_future_availability')
        # Reuse the engine's existing calendar, never a second holiday policy.
        # This function performs no IO or runtime/database initialization.
        from scanner_engine import market_session_state
        rows = []
        for index, row in frame.iterrows():
            day = index.date() if hasattr(index, 'date') else datetime.fromisoformat(str(index)).date()
            available = _market_available(day)
            # Future/unfinished rows cannot poison the completed prefix or its metrics.
            if available > min(observed, decision):
                continue
            if 'available_at' in row:
                available = max(available, _instant(row['available_at']))
                if available > min(observed, decision):
                    continue
            if not market_session_state(datetime.combine(day, time(12), ET))['is_trading_day']:
                return _finish(evidence, 'UNKNOWN', 'vcp_invalid_data')
            values = {name.lower(): float(row[name]) for name in ('Open', 'High', 'Low', 'Close', 'Volume')}
            if not all(math.isfinite(value) and value > 0 for value in values.values()):
                return _finish(evidence, 'UNKNOWN', 'vcp_invalid_data')
            if not values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']:
                return _finish(evidence, 'UNKNOWN', 'vcp_invalid_data')
            rows.append(dict(date=day.isoformat(), available_at=available.isoformat(), **values))
        if len({r['date'] for r in rows}) != len(rows) or rows != sorted(rows, key=lambda r: r['date']):
            return _finish(evidence, 'UNKNOWN', 'vcp_invalid_data')
        evidence['coverage']['completed_bars'] = len(rows)
        if len(rows) < MIN_BARS:
            return _finish(evidence, 'UNKNOWN', 'vcp_insufficient_history')
        trigger, base = rows[-1], rows[:-1]
        if expected_session is not None and trigger['date'] != str(expected_session):
            return _finish(evidence, 'UNKNOWN', 'vcp_history_not_current')
        evidence.update(source_data_at=trigger['available_at'],
            effective_available_at=max(observed, _instant(trigger['available_at'])).isoformat())
        evidence['coverage'].update(status='COMPLETE', base_bars=len(base),
            confirmation_basis='prior_prefix_completed_cutoff_not_exact_first_seen')
        base_window = base[-120:]
        evidence['pivot_confirmed_at'] = max(_instant(r['available_at']) for r in base_window).isoformat()
        if _instant(evidence['pivot_confirmed_at']) >= _instant(trigger['available_at']):
            return _finish(evidence, 'UNKNOWN', 'vcp_pivot_unconfirmed')
        pattern = calculate_vcp_pattern(list(reversed(base_window)))
        contractions = pattern.get('contractions') or []
        pivot = pattern.get('pivot_price')
        if not _finite(pivot) or pivot <= 0:
            return _finish(evidence, 'UNKNOWN', 'vcp_pivot_unavailable')
        # Every returned contraction comes from a confirmed ZigZag reversal (or
        # five-later-bar fallback). Do not accept a fabricated/future endpoint.
        if any(not isinstance(c.get(k), int) or not 0 <= c[k] < len(base_window)
               for c in contractions for k in ('high_idx', 'low_idx')):
            return _finish(evidence, 'UNKNOWN', 'vcp_pivot_unconfirmed')
        if contractions:
            if any(c['high_idx'] >= c['low_idx'] or
                    c.get('high_date') != base_window[c['high_idx']]['date'] or
                    c.get('low_date') != base_window[c['low_idx']]['date'] for c in contractions):
                return _finish(evidence, 'UNKNOWN', 'vcp_pivot_unconfirmed')
            # Upstream rounds pivot/low prices to cents for display. Actual
            # confirmation uses original OHLCV, not a rounded-down resistance.
            pivot = base_window[contractions[-1]['high_idx']]['high']
        volume = calculate_volume_pattern(list(reversed(base_window + [trigger])), pivot, contractions)
        avg50 = math.fsum(r['volume'] for r in base[-50:]) / 50
        # Donor numerator excludes bar0. Correct its trigger-contaminated 50-bar
        # denominator using actual prior sessions only; never synthesize a bar.
        dry_up = (math.fsum(r['volume'] for r in base[-10:]) / 10) / avg50
        trigger_ratio = trigger['volume'] / avg50
        closes = [r['close'] for r in base]
        sma50 = math.fsum(closes[-50:]) / 50
        sma200 = math.fsum(closes[-200:]) / 200
        sma200_22 = math.fsum(closes[-222:-22]) / 200
        features = dict(pattern_valid=bool(pattern.get('valid_vcp')), pattern_score=pattern.get('score', 0),
            num_contractions=len(contractions), pivot_price=float(pivot),
            last_contraction_low=base_window[contractions[-1]['low_idx']]['low'] if contractions else None,
            contraction_depths_pct=[float(c['depth_pct']) for c in contractions],
            atr_compression_ratio=pattern.get('atr_compression_ratio'),
            wide_and_loose=bool(pattern.get('wide_and_loose')), dry_up_ratio=dry_up,
            avg_prior_volume_50=avg50, avg_prior_volume_10=dry_up * avg50,
            trigger_volume_ratio=trigger_ratio, trigger_volume_confirmed=trigger_ratio >= 1.5,
            trigger_close=trigger['close'], trigger_date=trigger['date'],
            base_last_date=base[-1]['date'], sma50=sma50, sma200=sma200,
            sma200_22_sessions_ago=sma200_22,
            high_prior_252=max(r['high'] for r in base[-252:]),
            low_prior_252=min(r['low'] for r in base[-252:]),
            donor_volume_score=volume.get('score', 0),
            contraction_volume_declining=bool((volume.get('contraction_volume_trend') or {}).get('declining')))
        evidence['features'] = features
        evidence['source_fingerprint'] = hashlib.sha256(json.dumps(rows, sort_keys=True,
            allow_nan=False, separators=(',', ':')).encode()).hexdigest()
        if not features['pattern_valid'] or features['wide_and_loose'] or not contractions:
            return _finish(evidence, 'REJECTED', 'vcp_pattern_unconfirmed')
        if dry_up >= 1:
            return _finish(evidence, 'REJECTED', 'vcp_volume_not_dry')
        if trigger['close'] <= pivot:
            return _finish(evidence, 'FORMING', 'vcp_trigger_not_confirmed')
        if not features['trigger_volume_confirmed']:
            return _finish(evidence, 'FORMING', 'vcp_trigger_volume_unconfirmed')
        state, distance, score = _execution(features, trigger['close'])
        features.update(distance_from_pivot_pct=distance, donor_proximity_score=score)
        evidence['execution_state'] = state
        if state in {'Overextended', 'Extended', 'Early-post-breakout'}:
            return _finish(evidence, 'OVEREXTENDED', 'vcp_overextended')
        if state != 'Breakout':
            return _finish(evidence, 'REJECTED', 'vcp_trend_damaged')
        return _finish(evidence, 'CONFIRMED')
    except (ValueError, TypeError, KeyError, OverflowError, IndexError):
        evidence['features'] = {}
        return _finish(evidence, 'UNKNOWN', 'vcp_invalid_data')


def validate_trigger(evidence, price, quote_at, decision_at):
    """A current quote rechecks a frozen as-of setup; never changes order levels."""
    try:
        result = public_evidence(evidence)
        if result is None:
            raise ValueError('vcp_evidence_invalid')
        if result['state'] != 'CONFIRMED':
            raise ValueError((result.get('reasons') or ['vcp_trigger_not_confirmed'])[0])
        decision, quote = _instant(decision_at), _instant(quote_at)
        if (quote > decision or (decision - quote).total_seconds() > 720 or
                quote < _instant(result['source_data_at']) or
                _instant(result['effective_available_at']) > decision or not _finite(price) or price <= 0):
            raise ValueError('vcp_quote_not_fresh')
        if (_instant(result['decision_at']) > decision or
                _instant(result['pivot_confirmed_at']) >= _instant(result['source_data_at'])):
            raise ValueError('vcp_pivot_unconfirmed')
        features = result['features']
        state, distance, score = _execution(features, float(price))
        if price <= features['pivot_price']:
            raise ValueError('vcp_trigger_not_confirmed')
        if state in {'Overextended', 'Extended', 'Early-post-breakout'}:
            raise ValueError('vcp_overextended')
        if state != 'Breakout':
            raise ValueError('vcp_trend_damaged')
        result.update(entry_checked_at=decision.isoformat(), entry_quote_at=quote.isoformat(),
                      entry_price=float(price), execution_state=state)
        result['features'].update(distance_from_pivot_pct=distance, donor_proximity_score=score)
        return _finish(result, 'CONFIRMED')
    except (KeyError, TypeError, OverflowError):
        raise ValueError('vcp_evidence_invalid') from None
    except ValueError as exc:
        if str(exc) in REASONS:
            raise
        raise ValueError('vcp_evidence_invalid') from None


def public_evidence(value):
    """Bounded immutable audit projection, never an executable recovery contract."""
    if not isinstance(value, dict) or value.get('version') != VERSION or value.get('source_pin') != SOURCE_PIN:
        return None
    try:
        allowed = {'version', 'source_pin', 'state', 'reasons', 'decision_at', 'source_data_at',
            'source_observed_at', 'effective_available_at', 'pivot_confirmed_at', 'coverage',
            'features', 'source_fingerprint', 'execution_state', 'entry_checked_at',
            'entry_quote_at', 'entry_price'}
        if set(value) - allowed or value.get('state') not in STATES:
            return None
        reasons = value.get('reasons')
        if not isinstance(reasons, list) or len(reasons) > 1 or any(r not in REASONS for r in reasons):
            return None
        for key in ('decision_at', 'source_data_at', 'source_observed_at',
                    'effective_available_at', 'pivot_confirmed_at', 'entry_checked_at', 'entry_quote_at'):
            if value.get(key) is not None and (not isinstance(value[key], str) or
                    _instant(value[key]).isoformat() != value[key]):
                return None
        if 'source_fingerprint' in value and (not isinstance(value['source_fingerprint'], str) or
                len(value['source_fingerprint']) != 64 or
                any(c not in '0123456789abcdef' for c in value['source_fingerprint'])):
            return None
        coverage = value.get('coverage')
        if not isinstance(coverage, dict) or set(coverage) - {
                'completed_bars', 'required_bars', 'status', 'base_bars', 'confirmation_basis'}:
            return None
        if coverage.get('status') not in {'UNKNOWN', 'COMPLETE'} or coverage.get('required_bars') != MIN_BARS:
            return None
        for key in ('completed_bars', 'base_bars'):
            if key in coverage and (type(coverage[key]) is not int or not 0 <= coverage[key] <= MAX_BARS):
                return None
        if 'confirmation_basis' in coverage and coverage['confirmation_basis'] != 'prior_prefix_completed_cutoff_not_exact_first_seen':
            return None
        features = value.get('features')
        feature_names = {'pattern_valid', 'pattern_score', 'num_contractions', 'pivot_price',
            'last_contraction_low', 'contraction_depths_pct', 'atr_compression_ratio', 'wide_and_loose',
            'dry_up_ratio', 'avg_prior_volume_50', 'avg_prior_volume_10', 'trigger_volume_ratio',
            'trigger_volume_confirmed', 'trigger_close', 'trigger_date', 'base_last_date', 'sma50',
            'sma200', 'sma200_22_sessions_ago', 'high_prior_252', 'low_prior_252', 'donor_volume_score',
            'contraction_volume_declining', 'distance_from_pivot_pct', 'donor_proximity_score'}
        if not isinstance(features, dict) or set(features) - feature_names:
            return None
        booleans = {'pattern_valid', 'wide_and_loose', 'trigger_volume_confirmed', 'contraction_volume_declining'}
        for key, number in features.items():
            if key in booleans:
                if type(number) is not bool:
                    return None
            elif key in {'trigger_date', 'base_last_date'}:
                if not isinstance(number, str) or datetime.fromisoformat(number).date().isoformat() != number:
                    return None
            elif key == 'contraction_depths_pct':
                if not isinstance(number, list) or len(number) > 4 or any(not _finite(n) for n in number):
                    return None
            elif number is not None and not _finite(number):
                return None
        if value.get('execution_state') is not None and value['execution_state'] not in {
                'Invalid', 'Damaged', 'Overextended', 'Extended', 'Early-post-breakout', 'Breakout', 'Pre-breakout'}:
            return None
        if 'entry_price' in value and (not _finite(value['entry_price']) or value['entry_price'] <= 0):
            return None
        if value['state'] == 'CONFIRMED':
            if (reasons or coverage.get('status') != 'COMPLETE' or coverage.get('completed_bars', 0) < MIN_BARS
                    or not features.get('pattern_valid') or features.get('wide_and_loose')
                    or not features.get('trigger_volume_confirmed') or features.get('dry_up_ratio', 1) >= 1
                    or not _finite(features.get('pivot_price')) or features['pivot_price'] <= 0
                    or not all(value.get(k) for k in ('decision_at', 'source_data_at', 'source_observed_at',
                                                     'effective_available_at', 'pivot_confirmed_at'))):
                return None
            if not (_instant(value['pivot_confirmed_at']) < _instant(value['source_data_at']) <=
                    _instant(value['effective_available_at']) <= _instant(value['decision_at'])):
                return None
            if _instant(value['source_observed_at']) > _instant(value['effective_available_at']):
                return None
        encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':'))
        if len(encoded.encode()) > MAX_BYTES:
            return None
        return copy.deepcopy(json.loads(encoded))
    except (ValueError, TypeError, OverflowError):
        return None
