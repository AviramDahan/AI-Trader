"""Independent discovery composition and bounded, non-executable attribution.

No network, database, AI, orders or exits. Baseline and additional setup routes
are OR. Common market-data/liquidity/ATR eligibility still applies to every route.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from collections import deque

VERSION = 'entry_discovery_v1'
COMPONENT_VERSION = 'entry_discovery_component_v1'
BASELINE = 'BASELINE'
FLAGS = {
    'VCP_BASE_CONTRACTION': 'STOCK_SCANNER_VCP_DISCOVERY_ENABLED',
    'STOCKBEE_MOMENTUM_BURST': 'STOCK_SCANNER_MOMENTUM_BURST_ENABLED',
    'PEAD': 'STOCK_SCANNER_PEAD_ENABLED',
    'TREND_PULLBACK_RECLAIM': 'STOCK_SCANNER_PULLBACK_RECLAIM_ENABLED',
    'RELATIVE_STRENGTH_LEADER': 'STOCK_SCANNER_RS_LEADER_ENABLED',
}
MAX_BYTES = 32768
SOURCE_PIN = 'b29c6dfc2d4dc82bdfcfc13891e490863283405f'


def instant(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError('discovery_invalid_clock')
        return datetime.fromtimestamp(value, timezone.utc)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('discovery_timezone_required')
    return parsed.astimezone(timezone.utc)


def enabled_ids(cfg=None):
    from entry_discovery_capabilities import creation_allowed
    if not creation_allowed():
        return ()
    if cfg is not None and 'entry_strategy_ids' in cfg:
        requested = cfg['entry_strategy_ids']
        if not isinstance(requested, (list, tuple)) or set(requested) - set(FLAGS):
            raise ValueError('discovery_unknown_strategy')
        return tuple(key for key in FLAGS if key in requested)
    return tuple(key for key, flag in FLAGS.items() if os.getenv(flag, 'false').lower() == 'true')


def _canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()


def _baseline_evidence(candidate, decision, observed):
    material = {key: candidate.get(key) for key in ('ticker', 'technical_direction', 'technical_score',
        'price_as_of', 'entry', 'atr', 'recent_high_20d', 'recent_low_20d', 'single_target_source')}
    return dict(strategy_id=BASELINE, version='existing_trend_momentum_v1', state='DETECTED',
        direction=candidate['technical_direction'], score=float(candidate['technical_score']) / 7,
        source_times=dict(decision_at=decision.isoformat(), source_observed_at=instant(observed).isoformat(),
                          data_as_of=candidate['price_as_of']),
        sourcehash=hashlib.sha256(_canonical(material)).hexdigest(), evidence_ids=[],
        trigger=dict(kind='existing_trend_momentum', reference_close=candidate['entry']),
        entry_reference=candidate['entry'], reasons=[])


def attribution(records, decision_at, *, calculation_at=None):
    """Freeze audit evidence; never alter target-plan or execution contracts."""
    records = list(records)
    if not records:
        raise ValueError('discovery_missing_attribution')
    if len(records) > 6:
        raise ValueError('discovery_attribution_oversized')
    ids = [record.get('strategy_id') for record in records]
    if len(ids) != len(set(ids)) or set(ids) - ({BASELINE} | set(FLAGS)):
        raise ValueError('discovery_invalid_attribution_ids')
    payload = dict(version=VERSION, primary_strategy_id=ids[0], strategy_ids=ids,
                   detected_at=instant(decision_at).isoformat(), detections=records)
    if calculation_at is not None:
        payload.update(version=COMPONENT_VERSION, calculation_at=instant(calculation_at).isoformat())
    return validate_attribution(payload, allow_component=calculation_at is not None)


def validate_attribution(value, *, allow_component=False):
    """Allowlisted source metadata. Stored state does not consult creation flags."""
    try:
        component = isinstance(value, dict) and value.get('version') == COMPONENT_VERSION
        keys = {'version', 'primary_strategy_id', 'strategy_ids', 'detected_at', 'detections'}
        if component and allow_component:
            keys.add('calculation_at')
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError()
        if value['version'] != VERSION and not (component and allow_component):
            raise ValueError()
        ids, records = value['strategy_ids'], value['detections']
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 6 or len(ids) != len(set(ids)) or
                set(ids) - ({BASELINE} | set(FLAGS)) or value['primary_strategy_id'] != ids[0] or
                not isinstance(records, list) or len(records) != len(ids)):
            raise ValueError()
        decision = instant(value['detected_at'])
        if component and instant(value['calculation_at']) > decision:
            raise ValueError()
        allowed = {'strategy_id', 'version', 'source_pin', 'state', 'score', 'direction', 'source_times',
                   'sourcehash', 'evidence_ids', 'features', 'trigger', 'entry_reference',
                   'reasons', 'config', 'coverage'}
        for key, record in zip(ids, records):
            if (not isinstance(record, dict) or set(record) - allowed or
                    record.get('strategy_id') != key or record.get('state') != 'DETECTED' or
                    record.get('direction') not in {'BUY', 'SELL'} or
                    not isinstance(record.get('version'), str) or len(record['version']) > 80 or
                    isinstance(record.get('score'), bool) or not isinstance(record.get('score'), (int, float)) or
                    not math.isfinite(record['score']) or not 0 <= record['score'] <= 1 or
                    not isinstance(record.get('trigger'), dict)):
                raise ValueError()
            if key != BASELINE and record.get('source_pin') != SOURCE_PIN:
                raise ValueError()
            times = record.get('source_times')
            if not isinstance(times, dict) or not times.get('source_observed_at'):
                raise ValueError()
            record_decision = instant(times['decision_at'])
            if instant(times['source_observed_at']) > record_decision or record_decision > decision:
                raise ValueError()
            if key != BASELINE:
                from entry_strategies import VERSION as detector_version
                if record['direction'] != 'BUY' or record['version'] != detector_version:
                    raise ValueError()
                effective = instant(times['effective_available_at'])
                if not (instant(times['source_data_at']) <= effective <= record_decision and
                        instant(times['source_observed_at']) <= effective and
                        instant(record['trigger']['confirmed_at']) <= effective):
                    raise ValueError()
                trigger = record['trigger']
                if (any(isinstance(trigger.get(k), bool) or not isinstance(trigger.get(k), (int, float)) or
                        not math.isfinite(trigger[k]) or trigger[k] <= 0 for k in ('level', 'max_entry_price')) or
                        trigger['max_entry_price'] < trigger['level']):
                    raise ValueError()
            sourcehash = record.get('sourcehash')
            if not isinstance(sourcehash, str) or len(sourcehash) != 64 or any(c not in '0123456789abcdef' for c in sourcehash):
                raise ValueError()
            if len(_canonical(record)) > 4096:
                raise ValueError()
        encoded = _canonical(value)
        if len(encoded) > MAX_BYTES:
            raise ValueError()
        return json.loads(encoded)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError('discovery_invalid_attribution') from None


def strategy_ids(candidate):
    value = candidate.get('entry_discovery')
    if value:
        return validate_attribution(value, allow_component=True)['strategy_ids']
    return candidate.get('strategy_ids') or [BASELINE]


def discover_candidates(histories, universe, cfg, *, decision_at, context=None,
                        baseline_detector=None, include_baseline=True, calculation_at=None):
    """Compose detections before baseline-only rejection and shortlist selection.

    context.by_ticker may provide a separate long history_frame for detectors.
    Baseline/common metrics always use the original histories argument. A new
    BUY detection never turns the existing SELL route into a new SHORT policy.
    Opposing detections are recorded, with baseline direction taking precedence.
    """
    import stock_scanner
    from entry_strategies import detect_all
    decision, context = instant(decision_at), context or {}
    calculation = instant(calculation_at) if calculation_at is not None else decision
    if calculation > decision:
        raise ValueError('component_calculation_after_observation')
    ids = enabled_ids(cfg)
    output, observations = [], []
    for ticker in sorted(universe):
        member = universe[ticker]
        company = member.get('company', ticker)
        frame = histories.get(ticker)
        detail = dict(context)
        detail.pop('by_ticker', None)
        detail.update(context.get('by_ticker', {}).get(ticker, {}))
        detail['symbol'] = ticker
        if 'earnings_events' in detail:
            detail['earnings_events'] = [event for event in detail['earnings_events']
                if isinstance(event, dict) and event.get('symbol') == ticker]
        detector_frame = detail.pop('history_frame', frame)
        observed = getattr(detector_frame, 'attrs', {}).get('history_fetched_at')
        observation = dict(ticker=ticker, baseline_detected=False, strategy_results={},
                           common_reasons=[], candidate_strategy_ids=[])
        # Run all enabled independent detectors BEFORE any baseline-only gate.
        if ids:
            try:
                results = detect_all(detector_frame, decision_at=decision, source_observed_at=observed,
                                     enabled_ids=ids, context=detail)
            except (ValueError, TypeError, KeyError, OverflowError):
                results = {key: dict(strategy_id=key, state='UNKNOWN', reasons=['discovery_source_unavailable'])
                           for key in ids}
            observation['strategy_results'] = results
        else:
            results = {}
        if frame is None:
            observation['common_reasons'].append('common_history_unavailable')
            observations.append(observation)
            continue
        if baseline_detector is None:
            baseline = stock_scanner.analyze_history(ticker, company, frame, cfg, decision_at=calculation)
        else:
            baseline = baseline_detector(ticker, company, frame, cfg)
        observation['baseline_detected'] = baseline is not None
        common = stock_scanner.analyze_history(ticker, company, frame, cfg,
                                               baseline_filter=False, decision_at=calculation)
        if common is None:
            observation['common_reasons'].append('common_data_liquidity_or_atr_block')
            observations.append(observation)
            continue
        hits = [results[key] for key in ids if results.get(key, {}).get('state') == 'DETECTED']
        selected = []
        if include_baseline and baseline:
            original_observed = baseline.get('history_fetched_at')
            if original_observed is not None:
                selected.append(_baseline_evidence(baseline, decision, original_observed))
            elif ids:
                observation['common_reasons'].append('baseline_source_clock_unavailable')
        if baseline and baseline['technical_direction'] != 'BUY' and include_baseline and hits:
            observation['common_reasons'].append('opposing_baseline_direction')
            hits = []
        selected.extend(hits)
        if not selected:
            # A source-clock gap must not silently disable the otherwise valid
            # unchanged baseline route. It carries no fabricated provenance.
            if include_baseline and baseline:
                if calculation_at is not None:
                    observation['common_reasons'].append('component_source_clock_unavailable')
                    observations.append(observation)
                    continue
                candidate = dict(baseline)
            else:
                observations.append(observation)
                continue
        else:
            candidate = dict(baseline or common)
            if not baseline or not include_baseline:
                candidate['technical_direction'] = 'BUY'
                candidate['technical_score'] = common['baseline_buy_score']
            package = attribution(selected, decision, calculation_at=calculation_at)
            candidate.update(entry_discovery=package, strategy_ids=package['strategy_ids'],
                             strategy_id=package['primary_strategy_id'],
                             discovery_score=max(record['score'] for record in selected))
        candidate.update(indexes=member.get('indexes', []), market_cap=member.get('market_cap'))
        observation['candidate_strategy_ids'] = strategy_ids(candidate)
        output.append(candidate)
        observations.append(observation)
    return rank_candidates(output, cursor=int(context.get('ranking_cursor', 0))), observations


def rank_candidates(candidates, *, cursor=0):
    """Fair strategy queues, one ticker, fixed global quotas, no multi-hit bonus.

    Deterministic score ordering within each queue and rotating strategy order
    prevent a consistently large route monopolizing every shortlist/AI slot.
    Callers preserve the cursor in the existing scanner state across cycles.
    """
    by_ticker = {}
    for candidate in candidates:
        ticker = candidate['ticker']
        if ticker in by_ticker:
            raise ValueError('discovery_duplicate_candidate')
        by_ticker[ticker] = candidate
    def score(row):
        value = row.get('enhanced_rank_score', row.get('combined_rank_score',
                    row.get('discovery_score', float(row.get('technical_score', 0)) / 7)))
        return (float(value), float(row.get('technical_score', 0)),
                float(row.get('average_dollar_volume', 0)), row['ticker'])
    order = [BASELINE, *FLAGS]
    available = {key for row in by_ticker.values() for key in strategy_ids(row)}
    order = [key for key in order if key in available]
    if not order:
        return []
    offset = cursor % len(order)
    order = order[offset:] + order[:offset]
    queues = {key: deque(sorted([row for row in by_ticker.values() if key in strategy_ids(row)],
                               key=score, reverse=True)) for key in order}
    emitted, output = set(), []
    while any(queues.values()):
        for key in order:
            queue = queues[key]
            while queue and queue[0]['ticker'] in emitted:
                queue.popleft()
            if queue:
                row = queue.popleft()
                emitted.add(row['ticker'])
                output.append(row)
    return output


def validate_candidate_trigger(candidate, price, quote_at, decision_at, *, allowed_ids=None):
    """Check the current quote against a frozen discovery, never move levels.

    OR remains OR: a valid baseline or another still-valid trigger is sufficient.
    Retained orders are governed exclusively by the original execution contract.
    """
    package = candidate.get('entry_discovery')
    if package is None:
        return None
    package = validate_attribution(package)
    if BASELINE in package['strategy_ids']:
        return package
    from entry_strategies import validate_trigger
    reasons = []
    for record in package['detections']:
        if allowed_ids is not None and record['strategy_id'] not in allowed_ids:
            continue
        try:
            validate_trigger(record, price, quote_at, decision_at)
            return package
        except ValueError as exc:
            reasons.append(str(exc))
    raise ValueError('discovery_trigger_not_valid:' + (reasons[0] if reasons else 'no_detection'))


def review_projection(value):
    """Keep all decision facts, omit duplicated parser/configuration boilerplate.

    The immutable full attribution remains on the signal/order. This is only a
    smaller AI input; neither a replacement score nor an extra BUY instruction.
    """
    package = validate_attribution(value)
    return {key: package[key] for key in ('version', 'primary_strategy_id', 'strategy_ids', 'detected_at')} | {
        'detections': [{key: record[key] for key in ('strategy_id', 'version', 'state', 'direction',
            'score', 'source_times', 'sourcehash', 'evidence_ids', 'features', 'trigger',
            'entry_reference', 'reasons') if key in record} for record in package['detections']]}


def observation_summary(observation):
    """Small journal projection; no OHLCV, prompts or unbounded source payload."""
    return {key: copy.deepcopy(observation[key]) for key in
            ('ticker', 'baseline_detected', 'common_reasons', 'candidate_strategy_ids')} | {
        'strategy_results': {key: {field: copy.deepcopy(record[field]) for field in
            ('strategy_id', 'version', 'state', 'score', 'sourcehash', 'reasons', 'source_times', 'trigger')
            if field in record} for key, record in observation['strategy_results'].items()}}
