"""Independent, bounded BUY setup discovery. No baseline/AI/order/exit policy.

The five hypotheses are OR discovery paths, not additional baseline filters.
Scores describe setup evidence; they are not probabilities or proven returns.
Every emitted candidate still needs the existing quote, News/AI, RR and risk gates.
Only completed as-of bars and caller-supplied verified event/context data are used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from vendor.entry_discovery.vcp_pattern_calculator import calculate_vcp_pattern
from vendor.entry_discovery.stockbee import Bar, detect_base_profile, detect_triggers

VERSION = 'independent_entry_discovery_v1'
SOURCE_PIN = 'b29c6dfc2d4dc82bdfcfc13891e490863283405f'
STRATEGY_IDS = ('VCP_BASE_CONTRACTION', 'STOCKBEE_MOMENTUM_BURST', 'PEAD',
                'TREND_PULLBACK_RECLAIM', 'RELATIVE_STRENGTH_LEADER')
STATES = frozenset({'DETECTED', 'FORMING', 'UNKNOWN', 'REJECTED'})
MAX_BARS, MAX_BYTES = 1024, 4096
UTC, ET = timezone.utc, ZoneInfo('America/New_York')
HISTORY_REASONS = frozenset({'history_unavailable', 'history_oversized',
    'source_not_available_at_decision', 'invalid_market_session', 'invalid_ohlcv',
    'no_completed_bars', 'invalid_chronology', 'history_not_current', 'invalid_history'})

# Explicit untuned research hypotheses, independently configurable by the caller.
# None changes the existing global confidence/RR/sizing/exposure/exit thresholds.
DEFAULT_CONFIGS = {
    'VCP_BASE_CONTRACTION': dict(min_history=253, lookback=120,
        min_contractions=2, dry_up_max=1.0, volume_ratio_min=1.5, max_chase_pct=3.0),
    'STOCKBEE_MOMENTUM_BURST': dict(min_history=65, min_base_days=3,
        max_base_days=20, max_base_width_pct=15.0, max_prior_avg_range_pct=5.0,
        four_pct_threshold=4.0, dollar_threshold=.90, max_prev_day_gain_for_range=2.0,
        min_volume=100000, nine_million_volume=9000000, volume_ratio_min=1.5,
        close_location_min=.75, max_chase_pct=3.0),
    'PEAD': dict(min_history=65, min_gap_pct=4.0, max_event_age_sessions=20,
        min_consolidation_bars=2, max_consolidation_bars=10,
        gap_volume_ratio_min=1.5, trigger_volume_ratio_min=1.2,
        close_location_min=.60, max_chase_pct=3.0),
    'TREND_PULLBACK_RECLAIM': dict(min_history=65, pullback_lookback=10,
        pullback_min_pct=2.0, pullback_max_pct=12.0, touch_ema_pct=2.0,
        volume_ratio_min=1.0, max_chase_pct=3.0),
    'RELATIVE_STRENGTH_LEADER': dict(min_history=127, short_period=63,
        long_period=126, excess_short_min_pct=0.0, excess_long_min_pct=0.0,
        base_days=20, max_base_width_pct=15.0, volume_ratio_min=1.5,
        close_location_min=.75, max_chase_pct=3.0),
}


def _instant(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError('invalid_time')
        return datetime.fromtimestamp(value, UTC)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(UTC)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
        separators=(',', ':')).encode()).hexdigest()


def _available(day):
    return datetime.combine(day, time(16, 5), ET).astimezone(UTC)


def _prepare(frame, decision, observed, expected=None):
    if frame is None or not hasattr(frame, 'iterrows') or frame.empty:
        raise ValueError('history_unavailable')
    if len(frame) > MAX_BARS:
        raise ValueError('history_oversized')
    if observed > decision:
        raise ValueError('source_not_available_at_decision')
    from scanner_engine import market_session_state
    rows = []
    for index, row in frame.iterrows():
        day = index.date() if hasattr(index, 'date') else datetime.fromisoformat(str(index)).date()
        available = _available(day)
        if available > min(observed, decision):
            continue
        if 'available_at' in row:
            available = max(available, _instant(row['available_at']))
            if available > min(observed, decision):
                continue
        if not market_session_state(datetime.combine(day, time(12), ET))['is_trading_day']:
            raise ValueError('invalid_market_session')
        values = {key.lower(): float(row[key]) for key in ('Open', 'High', 'Low', 'Close', 'Volume')}
        if not all(math.isfinite(v) and v > 0 for v in values.values()):
            raise ValueError('invalid_ohlcv')
        if not values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high']:
            raise ValueError('invalid_ohlcv')
        rows.append(dict(date=day.isoformat(), available_at=available.isoformat(), **values))
    if not rows:
        raise ValueError('no_completed_bars')
    if rows != sorted(rows, key=lambda row: row['date']) or len({r['date'] for r in rows}) != len(rows):
        raise ValueError('invalid_chronology')
    if expected is None:
        day = decision.astimezone(ET).date()
        for _ in range(10):
            if (_available(day) <= decision and
                    market_session_state(datetime.combine(day, time(12), ET))['is_trading_day']):
                expected = day.isoformat()
                break
            day -= timedelta(days=1)
    if rows[-1]['date'] != str(expected):
        raise ValueError('history_not_current')
    return rows


def _mean(values):
    return math.fsum(values) / len(values)


def _ema(values, period=20):
    result = values[0]
    alpha = 2 / (period + 1)
    for value in values[1:]:
        result += alpha * (value - result)
    return result


def _location(row):
    width = row['high'] - row['low']
    return (row['close'] - row['low']) / width if width > 0 else 0.0


def _record(strategy_id, config, decision, observed, rows):
    last = rows[-1] if rows else None
    return dict(version=VERSION, strategy_id=strategy_id, source_pin=SOURCE_PIN,
        direction='BUY', state='UNKNOWN', score=0.0, reasons=[], config=copy.deepcopy(config),
        source_times=dict(decision_at=decision.isoformat(), source_observed_at=observed.isoformat(),
            source_data_at=last['available_at'] if last else None,
            effective_available_at=max(observed, _instant(last['available_at'])).isoformat() if last else None),
        sourcehash=_hash(rows) if rows else None, evidence_ids=[], features={}, trigger=None,
        coverage=dict(completed_bars=len(rows), required_bars=config['min_history']),
        entry_reference=dict(kind='COMPLETED_DAILY_CLOSE_NOT_EXECUTABLE',
            price=last['close'], at=last['available_at']) if last else None)


def _finish(record, state, reason=None, score=0.0):
    record.update(state=state, score=max(0.0, min(1.0, float(score))), reasons=[reason] if reason else [])
    identity = {k: record[k] for k in ('version', 'strategy_id', 'sourcehash', 'config', 'features', 'trigger')}
    record['evidence_ids'] = [_hash(identity)] if record['sourcehash'] else []
    raw = json.dumps(record, sort_keys=True, allow_nan=False, separators=(',', ':'))
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError('evidence_oversized')
    return json.loads(raw)


def _trigger(record, rows, level, max_chase, kind):
    last = rows[-1]
    record['trigger'] = dict(kind=kind, level=float(level),
        max_entry_price=float(level * (1 + max_chase / 100)),
        confirmed_at=last['available_at'], session=last['date'])
    if last['close'] <= level:
        return 'FORMING', 'trigger_not_confirmed'
    if last['close'] > record['trigger']['max_entry_price']:
        return 'REJECTED', 'trigger_overextended'
    return 'DETECTED', None


def _vcp(record, rows, context):
    cfg, base, last = record['config'], rows[:-1], rows[-1]
    window = base[-cfg['lookback']:]
    pattern = calculate_vcp_pattern(list(reversed(window)), lookback_days=cfg['lookback'],
                                    min_contractions=cfg['min_contractions'])
    contractions = pattern.get('contractions') or []
    if (not pattern.get('valid_vcp') or pattern.get('wide_and_loose') or
            len(contractions) < cfg['min_contractions']):
        record['features'] = dict(num_contractions=len(contractions), pattern_score=pattern.get('score', 0))
        return _finish(record, 'REJECTED', 'vcp_pattern_unconfirmed')
    for contraction in contractions:
        hi, lo = contraction['high_idx'], contraction['low_idx']
        if (type(hi) is not int or type(lo) is not int or not 0 <= hi < lo < len(window) or
                contraction.get('high_date') != window[hi]['date'] or
                contraction.get('low_date') != window[lo]['date']):
            return _finish(record, 'UNKNOWN', 'vcp_pivot_unconfirmed')
    pivot = window[contractions[-1]['high_idx']]['high']
    avg50 = _mean([r['volume'] for r in base[-50:]])
    dry = _mean([r['volume'] for r in base[-10:]]) / avg50
    ratio = last['volume'] / avg50
    sma50, sma200 = (_mean([r['close'] for r in base[-n:]]) for n in (50, 200))
    record['features'] = dict(num_contractions=len(contractions), pivot=pivot,
        contraction_depths_pct=[c['depth_pct'] for c in contractions],
        pattern_score=pattern['score'], dry_up_ratio=dry, trigger_volume_ratio=ratio,
        sma50=sma50, sma200=sma200, pivot_confirmed_at=max(r['available_at'] for r in window))
    if _instant(record['features']['pivot_confirmed_at']) >= _instant(last['available_at']):
        return _finish(record, 'UNKNOWN', 'vcp_pivot_unconfirmed')
    if dry >= cfg['dry_up_max']:
        return _finish(record, 'REJECTED', 'vcp_volume_not_dry')
    if last['close'] <= max(sma50, sma200):
        return _finish(record, 'REJECTED', 'vcp_trend_not_confirmed')
    state, reason = _trigger(record, rows, pivot, cfg['max_chase_pct'], 'PRIOR_CONFIRMED_VCP_PIVOT_BREAK')
    if state == 'DETECTED' and ratio < cfg['volume_ratio_min']:
        state, reason = 'FORMING', 'vcp_trigger_volume_unconfirmed'
    return _finish(record, state, reason, pattern['score'] / 100)


def _stockbee(record, rows, context):
    cfg, last = record['config'], rows[-1]
    bars = [Bar(**{k: row[k] for k in ('date', 'open', 'high', 'low', 'close', 'volume')}) for row in reversed(rows)]
    base = detect_base_profile(bars, **{k: cfg[k] for k in
        ('min_base_days', 'max_base_days', 'max_base_width_pct', 'max_prior_avg_range_pct')})
    profile = detect_triggers(bars, SimpleNamespace(**cfg))
    record['features'] = dict(prior_base_days=base.prior_base_days, base_width_pct=base.base_width_pct,
        avg_prior_range_pct=base.avg_prior_range_pct, volume_dry_up=base.volume_dry_up,
        trigger_tags=profile.trigger_tags, day_gain_pct=profile.day_gain_pct,
        volume_ratio_20d=profile.volume_ratio_20d, close_location=profile.close_location_pct / 100)
    if not base.prior_base_days:
        return _finish(record, 'REJECTED', 'momentum_base_unconfirmed')
    level = max(r['high'] for r in rows[-1-base.prior_base_days:-1])
    state, reason = _trigger(record, rows, level, cfg['max_chase_pct'], 'PRIOR_CONSOLIDATION_HIGH_BREAK')
    executable = any(tag != '9m_volume' for tag in profile.trigger_tags)
    if state == 'DETECTED' and not executable:
        state, reason = 'FORMING', 'momentum_burst_trigger_unconfirmed'
    if state == 'DETECTED' and (profile.volume_ratio_20d < cfg['volume_ratio_min'] or
            _location(last) < cfg['close_location_min']):
        state, reason = 'FORMING', 'momentum_volume_or_close_unconfirmed'
    return _finish(record, state, reason, min(1, .5 + profile.volume_ratio_20d / 10))


def _earnings_event(events, decision, symbol):
    """No headline parsing, scheduled dates, latest revisions or surprise guesses."""
    revisions = {}
    if not isinstance(events, list) or len(events) > 64:
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        if not isinstance(event.get('event_id'), str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}', event['event_id']):
            continue
        if not isinstance(event.get('source_id'), str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}', event['source_id']):
            continue
        try:
            release = _instant(event['released_at'])
            clocks = [_instant(event[key]) for key in
                ('source_observed_at', 'processed_at', 'effective_available_at')]
            if not release <= clocks[0] <= clocks[1] <= clocks[2] <= decision:
                continue
            previous = revisions.get(event['event_id'])
            if previous is None or clocks[-1] > previous[1]:
                revisions[event['event_id']] = (release, clocks[-1], event)
            elif clocks[-1] == previous[1] and event != previous[2]:
                # A conflicting same-clock revision has no deterministic truth.
                revisions[event['event_id']] = (release, clocks[-1], dict(event, verified=False))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    valid = []
    for release, effective, event in revisions.values():
        if (event.get('verified') is not True or event.get('timing_verified') is not True or
                event.get('retracted') is True or
                event.get('event_type') != 'EARNINGS_RELEASE' or event.get('timing') not in {'BMO', 'AMC'} or
                not symbol or event.get('symbol') != symbol):
            continue
        try:
            local = release.astimezone(ET)
            if ((event['timing'] == 'BMO' and local.time() >= time(9, 30)) or
                    (event['timing'] == 'AMC' and local.time() < time(16))):
                continue
            # Latest admissible revision is chosen only from already-available inputs.
            valid.append((release, effective, event))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return max(valid, key=lambda item: (item[0], item[1])) if valid else None


def _pead(record, rows, context):
    cfg, last = record['config'], rows[-1]
    times = record['source_times']
    event_tuple = _earnings_event(context.get('earnings_events'),
        _instant(times['decision_at']), context.get('symbol'))
    if event_tuple is None:
        return _finish(record, 'UNKNOWN', 'verified_earnings_timing_unavailable')
    release, effective, event = event_tuple
    from scanner_engine import market_session_state
    first_day = release.astimezone(ET).date()
    gap_session = None
    for _ in range(10):
        session_open = datetime.combine(first_day, time(9, 30), ET).astimezone(UTC)
        if session_open > release and market_session_state(datetime.combine(first_day, time(12), ET))['is_trading_day']:
            gap_session = first_day.isoformat()
            break
        first_day += timedelta(days=1)
    indexes = [i for i, row in enumerate(rows) if row['date'] == gap_session]
    if not indexes or indexes[0] == 0:
        return _finish(record, 'UNKNOWN', 'post_event_price_context_unavailable')
    gap_index = indexes[0]
    previous_day = first_day - timedelta(days=1)
    for _ in range(10):
        if market_session_state(datetime.combine(previous_day, time(12), ET))['is_trading_day']:
            break
        previous_day -= timedelta(days=1)
    if rows[gap_index-1]['date'] != previous_day.isoformat():
        return _finish(record, 'UNKNOWN', 'pre_event_price_context_unavailable')
    gap, prior = rows[gap_index], rows[gap_index-1]
    age = len(rows) - 1 - gap_index
    evidence_keys = ('event_id', 'source_id', 'symbol', 'event_type', 'released_at', 'timing',
        'source_observed_at', 'processed_at', 'effective_available_at',
        'revision', 'document_hash', 'parser_version', 'issuer_cik', 'issuer_mapping_hash')
    record['sourcehash'] = _hash(dict(bars=record['sourcehash'], event={k: event[k] for k in evidence_keys if k in event}))
    times['effective_available_at'] = max(_instant(times['effective_available_at']), effective).isoformat()
    gap_pct = (gap['open'] / prior['close'] - 1) * 100
    avg_gap_volume = _mean([r['volume'] for r in rows[max(0, gap_index-20):gap_index]])
    gap_volume = gap['volume'] / avg_gap_volume
    record['features'] = dict(event_id=event['event_id'], source_id=event['source_id'],
        released_at=release.isoformat(), event_effective_available_at=effective.isoformat(),
        timing=event['timing'], gap_session=gap['date'], gap_pct=gap_pct,
        gap_volume_ratio=gap_volume, event_age_sessions=age,
        inference='EARNINGS_GAP_FOLLOWTHROUGH_NOT_EPS_SURPRISE')
    # Exact immutable original-page revision is traceable from a saved decision,
    # not merely today's latest feed row. Older typed fixtures remain readable.
    release_evidence = {key: event[key] for key in ('revision', 'document_hash', 'parser_version',
        'issuer_cik', 'issuer_mapping_hash') if key in event}
    if isinstance(event.get('source_url'), str) and len(event['source_url']) <= 768:
        release_evidence['source_url'] = event['source_url']
    if release_evidence:
        record['features']['release_evidence'] = release_evidence
    if age > cfg['max_event_age_sessions']:
        return _finish(record, 'REJECTED', 'earnings_event_expired')
    if gap_pct < cfg['min_gap_pct'] or gap_volume < cfg['gap_volume_ratio_min'] or gap['close'] < gap['open']:
        return _finish(record, 'REJECTED', 'earnings_gap_quality_unconfirmed')
    consolidation = rows[gap_index+1:-1]
    if len(consolidation) < cfg['min_consolidation_bars']:
        return _finish(record, 'FORMING', 'post_event_consolidation_unconfirmed')
    if len(consolidation) > cfg['max_consolidation_bars']:
        return _finish(record, 'REJECTED', 'post_event_setup_expired')
    if min(r['low'] for r in consolidation) < gap['low']:
        return _finish(record, 'REJECTED', 'earnings_gap_support_lost')
    level = max(r['high'] for r in consolidation)
    ratio = last['volume'] / _mean([r['volume'] for r in rows[-21:-1]])
    record['features'].update(consolidation_bars=len(consolidation), trigger_volume_ratio=ratio)
    state, reason = _trigger(record, rows, level, cfg['max_chase_pct'], 'POST_EARNINGS_CONSOLIDATION_HIGH_BREAK')
    if state == 'DETECTED' and (ratio < cfg['trigger_volume_ratio_min'] or _location(last) < cfg['close_location_min']):
        state, reason = 'FORMING', 'earnings_followthrough_unconfirmed'
    return _finish(record, state, reason, min(1, .5 + ratio / 10))


def _pullback(record, rows, context):
    cfg, base, last = record['config'], rows[:-1], rows[-1]
    closes = [r['close'] for r in base]
    sma50 = _mean(closes[-50:])
    earlier = _mean(closes[-60:-10])
    ema20 = _ema(closes, 20)
    recent = base[-cfg['pullback_lookback']:]
    peak_index = max(range(len(recent)), key=lambda i: recent[i]['high'])
    if peak_index >= len(recent)-1:
        return _finish(record, 'REJECTED', 'pullback_setup_unconfirmed')
    peak = recent[peak_index]['high']
    trough = min(r['low'] for r in recent[peak_index+1:])
    depth = (1 - trough / peak) * 100
    ratio = last['volume'] / _mean([r['volume'] for r in base[-20:]])
    touched = any(r['low'] <= ema20 * (1 + cfg['touch_ema_pct'] / 100) for r in recent)
    record['features'] = dict(sma50=sma50, sma50_prior10=earlier, ema20=ema20,
        pullback_depth_pct=depth, touched_ema=touched, trigger_volume_ratio=ratio)
    if sma50 <= earlier or last['close'] <= sma50:
        return _finish(record, 'REJECTED', 'pullback_uptrend_unconfirmed')
    if not cfg['pullback_min_pct'] <= depth <= cfg['pullback_max_pct'] or not touched:
        return _finish(record, 'REJECTED', 'pullback_setup_unconfirmed')
    if base[-1]['close'] > ema20:
        return _finish(record, 'REJECTED', 'pullback_already_reclaimed')
    level = max(ema20, base[-1]['high'])
    state, reason = _trigger(record, rows, level, cfg['max_chase_pct'], 'PULLBACK_EMA20_AND_PRIOR_HIGH_RECLAIM')
    if state == 'DETECTED' and (last['close'] <= last['open'] or ratio < cfg['volume_ratio_min']):
        state, reason = 'FORMING', 'pullback_reclaim_quality_unconfirmed'
    return _finish(record, state, reason, min(1, .5 + ratio / 10))


def _relative_strength(record, rows, context):
    cfg, last = record['config'], rows[-1]
    if context.get('benchmark_frame') is None or context.get('benchmark_observed_at') is None:
        return _finish(record, 'UNKNOWN', 'benchmark_unavailable')
    try:
        observed = _instant(context['benchmark_observed_at'])
        benchmark = _prepare(context['benchmark_frame'], _instant(record['source_times']['decision_at']),
            observed, rows[-1]['date'])
    except (ValueError, TypeError, KeyError, OverflowError):
        return _finish(record, 'UNKNOWN', 'benchmark_unavailable_at_decision')
    by_date = {r['date']: r for r in benchmark}
    needed = rows[-(cfg['long_period']+1):]
    if any(row['date'] not in by_date for row in needed):
        return _finish(record, 'UNKNOWN', 'benchmark_period_mismatch')
    matched = [by_date[r['date']] for r in needed]
    short = ((last['close'] / rows[-cfg['short_period']-1]['close'] - 1) -
             (matched[-1]['close'] / matched[-cfg['short_period']-1]['close'] - 1)) * 100
    long = ((last['close'] / needed[0]['close'] - 1) -
            (matched[-1]['close'] / matched[0]['close'] - 1)) * 100
    record['sourcehash'] = _hash(dict(equity=record['sourcehash'], benchmark=matched,
        benchmark_observed_at=observed.isoformat()))
    record['source_times']['effective_available_at'] = max(observed,
        _instant(record['source_times']['effective_available_at'])).isoformat()
    base = rows[-cfg['base_days']-1:-1]
    level = max(r['high'] for r in base)
    width = (level - min(r['low'] for r in base)) / base[-1]['close'] * 100
    sma50 = _mean([r['close'] for r in rows[-51:-1]])
    sma50_old = _mean([r['close'] for r in rows[-61:-11]])
    ratio = last['volume'] / _mean([r['volume'] for r in rows[-21:-1]])
    record['features'] = dict(excess_short_pct=short, excess_long_pct=long,
        short_sessions=cfg['short_period'], long_sessions=cfg['long_period'],
        base_width_pct=width, trigger_volume_ratio=ratio, sma50=sma50,
        sector_status='OPTIONAL_NOT_USED_WITHOUT_VERIFIED_CONTEXT')
    mapping = context.get('sector_mapping')
    if isinstance(mapping, dict) and mapping.get('verified') is True and context.get('sector_frame') is not None:
        try:
            known = _instant(mapping['known_at'])
            sector_observed = _instant(context['sector_observed_at'])
            sector = _prepare(context['sector_frame'], _instant(record['source_times']['decision_at']),
                sector_observed, rows[-1]['date'])
            if known <= _instant(record['source_times']['decision_at']) and len(sector) > cfg['short_period']:
                sector_return = (sector[-1]['close'] / sector[-cfg['short_period']-1]['close'] - 1) * 100
                record['features'].update(sector_status='VERIFIED_OPTIONAL_CONTEXT', sector_short_return_pct=sector_return)
                record['sourcehash'] = _hash(dict(base=record['sourcehash'], sector=sector,
                    mapping_known_at=known.isoformat(), observed_at=sector_observed.isoformat()))
                record['source_times']['effective_available_at'] = max(sector_observed,
                    _instant(record['source_times']['effective_available_at'])).isoformat()
        except (ValueError, TypeError, KeyError, OverflowError):
            record['features']['sector_status'] = 'UNKNOWN_OPTIONAL_CONTEXT'
    if short <= cfg['excess_short_min_pct'] or long <= cfg['excess_long_min_pct']:
        return _finish(record, 'REJECTED', 'relative_strength_unconfirmed')
    if width > cfg['max_base_width_pct'] or last['close'] <= sma50 or sma50 <= sma50_old:
        return _finish(record, 'REJECTED', 'leader_setup_unconfirmed')
    state, reason = _trigger(record, rows, level, cfg['max_chase_pct'], 'RELATIVE_STRENGTH_LEADER_BASE_HIGH_BREAK')
    if state == 'DETECTED' and (ratio < cfg['volume_ratio_min'] or _location(last) < cfg['close_location_min']):
        state, reason = 'FORMING', 'leader_trigger_quality_unconfirmed'
    return _finish(record, state, reason, min(1, .5 + max(0, short) / 100))


_DETECTORS = dict(zip(STRATEGY_IDS, (_vcp, _stockbee, _pead, _pullback, _relative_strength)))


def detect_all(frame, *, decision_at, source_observed_at, enabled_ids=None, context=None):
    """Independent OR records; never calls baseline analyzer, network, AI or DB.

    ``context.earnings_events`` must contain already-verified release revisions:
    event_id/source_id/symbol matching context.symbol, event_type=EARNINGS_RELEASE,
    verified/timing_verified=True,
    released_at, timing=BMO|AMC, source_observed_at, processed_at,
    effective_available_at. No EPS/consensus/surprise inference is made.
    Sector is optional corroboration, not an extra AND across discovery paths.
    """
    ids = STRATEGY_IDS if enabled_ids is None else tuple(enabled_ids)
    if len(ids) != len(set(ids)) or any(s not in STRATEGY_IDS for s in ids):
        raise ValueError('unknown_or_duplicate_strategy_id')
    if not ids:
        return {}
    context = context or {}
    decision, observed = _instant(decision_at), _instant(source_observed_at)
    error = None
    try:
        rows = _prepare(frame, decision, observed, context.get('expected_session'))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        rows, error = [], str(exc) if str(exc) in HISTORY_REASONS else 'invalid_history'
    output = {}
    for strategy_id in ids:
        config = copy.deepcopy(DEFAULT_CONFIGS[strategy_id])
        overrides = (context.get('configs') or {}).get(strategy_id, {})
        if (not isinstance(overrides, dict) or set(overrides) - set(config) or
                any(not _finite(v) or v < 0 or v > 100000000 for v in overrides.values())):
            raise ValueError('invalid_strategy_config')
        config.update(overrides)
        for key, value in DEFAULT_CONFIGS[strategy_id].items():
            if type(value) is int and (type(config[key]) is not int or config[key] < 1):
                raise ValueError('invalid_integer_strategy_config')
        if config['min_history'] > MAX_BARS or config['min_history'] < DEFAULT_CONFIGS[strategy_id]['min_history']:
            raise ValueError('minimum_history_cannot_be_lowered')
        record = _record(strategy_id, config, decision, observed, rows)
        if error:
            output[strategy_id] = _finish(record, 'UNKNOWN', error)
        elif len(rows) < config['min_history']:
            output[strategy_id] = _finish(record, 'UNKNOWN', 'insufficient_history')
        else:
            try:
                output[strategy_id] = _DETECTORS[strategy_id](record, rows, context)
            except (ValueError, TypeError, KeyError, OverflowError, IndexError):
                output[strategy_id] = _finish(_record(strategy_id, config, decision, observed, rows),
                    'UNKNOWN', 'calculation_unavailable')
    return output


def validate_trigger(record, price, quote_at, decision_at):
    """Recheck actual fresh quote against frozen discovery trigger, not an order.

    Does not replace the existing planner, confidence/News/AI or execution gates.
    It cannot change a stop, target, order expiry or existing position.
    """
    if (not isinstance(record, dict) or record.get('version') != VERSION or record.get('source_pin') != SOURCE_PIN or
            record.get('strategy_id') not in STRATEGY_IDS or record.get('state') != 'DETECTED' or
            record.get('direction') != 'BUY' or not _finite(price) or price <= 0):
        raise ValueError('entry_strategy_not_detected')
    try:
        decision, quote = _instant(decision_at), _instant(quote_at)
        times, trigger = record['source_times'], record['trigger']
        if (not all(_finite(trigger.get(k)) and trigger[k] > 0 for k in ('level', 'max_entry_price')) or
                trigger['max_entry_price'] < trigger['level'] or
                not isinstance(record.get('sourcehash'), str) or
                not re.fullmatch('[0-9a-f]{64}', record['sourcehash'])):
            raise ValueError('entry_strategy_evidence_invalid')
        if (quote > decision or (decision-quote).total_seconds() > 720 or
                quote < _instant(trigger['confirmed_at']) or
                _instant(times['effective_available_at']) > decision or
                _instant(times['decision_at']) > decision):
            raise ValueError('entry_strategy_quote_not_fresh')
        if price <= trigger['level']:
            raise ValueError('entry_strategy_trigger_not_confirmed')
        if price > trigger['max_entry_price']:
            raise ValueError('entry_strategy_overextended')
        return True
    except (KeyError, TypeError, OverflowError):
        raise ValueError('entry_strategy_evidence_invalid') from None
    except ValueError as exc:
        if str(exc) in {'entry_strategy_quote_not_fresh', 'entry_strategy_trigger_not_confirmed',
                       'entry_strategy_overextended', 'entry_strategy_evidence_invalid'}:
            raise
        raise ValueError('entry_strategy_evidence_invalid') from None
