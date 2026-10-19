"""Offline12-arm discovery comparison, not an AI/order/profit backtester.

The application owns the discovery and fair-ranking implementation. This tool
uses those exact pure helpers on the same frozen frames in every arm, never
reimplements entry strategy formulas and never creates a quote/order/fill.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, time, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import sys
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / 'service' / 'server'
UTC = timezone.utc
ET = ZoneInfo('America/New_York')
MAX_BYTES = 16_000_000
MAX_SNAPSHOTS = 100
MAX_OBSERVATIONS = 5000
MAX_BARS = 1024
STRATEGIES = ('VCP_BASE_CONTRACTION', 'STOCKBEE_MOMENTUM_BURST', 'PEAD',
              'TREND_PULLBACK_RECLAIM', 'RELATIVE_STRENGTH_LEADER')
DEFAULT_CFG = {'min_dollar_volume': 50_000_000, 'min_atr_pct': 1.0,
               'max_atr_pct': 8.0, 'min_technical_score': 5,
               'shortlist_limit': 25, 'ai_candidate_limit': 6}
ARMS = [('BASELINE', True, ())]
ARMS += [(strategy + '_ONLY', False, (strategy,)) for strategy in STRATEGIES]
ARMS += [('BASELINE_PLUS_' + strategy, True, (strategy,)) for strategy in STRATEGIES]
ARMS += [('BASELINE_PLUS_ALL', True, STRATEGIES)]


def instant(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('timestamp_required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp_timezone_required')
    return parsed.astimezone(UTC)


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path, expected_hash=None):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('input_size_bound')
    digest = hashlib.sha256(raw).hexdigest()
    if expected_hash and digest != expected_hash:
        raise ValueError('frozen_source_hash_mismatch')
    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
    return value, digest


@contextmanager
def offline_only():
    """Reject accidental network/subprocess/database calls from pure helpers."""
    def deny(*args, **kwargs):
        raise RuntimeError('comparison_forbids_network_database_subprocess')
    import requests
    import yfinance as yf
    from curl_cffi import requests as curl_requests
    patched = []
    for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                      (socket.socket, 'sendto'), (socket, 'create_connection'),
                      (subprocess, 'Popen'), (subprocess, 'run'),
                      (requests.Session, 'request'), (curl_requests.Session, 'request'),
                      (yf, 'download'), (yf.Ticker, 'history')):
        patched.append((obj, name, getattr(obj, name)))
        setattr(obj, name, deny)
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    import database
    for name in ('get_db_connection', 'begin_write_transaction', 'init_database'):
        if hasattr(database, name):
            patched.append((database, name, getattr(database, name)))
            setattr(database, name, deny)
    try:
        yield
    finally:
        for obj, name, original in reversed(patched):
            setattr(obj, name, original)


def frame_from_observation(observation, decision, *, market_cutoff=None):
    import pandas as pd
    observed = instant(observation['source_observed_at'])
    bars = observation.get('bars')
    if not isinstance(bars, list) or len(bars) > MAX_BARS:
        raise ValueError('invalid_or_oversized_history')
    selected = []
    excluded = 0
    for row in bars:
        day = datetime.fromisoformat(str(row['date'])).date()
        available = datetime.combine(day, time(16, 5), ET).astimezone(UTC)
        if row.get('available_at'):
            available = max(available, instant(row['available_at']))
        if available > min(observed, decision) or (market_cutoff is not None and day > market_cutoff):
            excluded += 1
            continue
        item = {'date': day.isoformat()}
        for name in ('Open', 'High', 'Low', 'Close', 'Volume'):
            value = row.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('invalid_numeric_history')
            item[name] = float(value)
        # Per-bar completion/availability floor, not an invented first_seen.
        # The independently recorded global source clock remains authoritative.
        item['available_at'] = available.isoformat()
        selected.append(item)
    if observed > decision:
        # The whole source, not just its last candle, was unavailable. Retain
        # its original clock in diagnostics but expose no data to either arm.
        selected, excluded = [], len(bars)
    dates = [r['date'] for r in selected]
    if dates != sorted(set(dates)):
        raise ValueError('nonchronological_or_duplicate_history')
    frame = pd.DataFrame(selected, columns=['date', 'Open', 'High', 'Low', 'Close', 'Volume', 'available_at'])
    frame.index = pd.to_datetime(frame['date'])
    frame.attrs['history_fetched_at'] = observed.timestamp()
    return frame, {'consumed_source_sha256': sha(selected), 'completed_bars': len(selected),
                   'excluded_future_or_unavailable_bars': excluded,
                   'source_observed_at': observed.isoformat(),
                   'source_after_decision': observed > decision}


def prepare_snapshot(snapshot):
    decision = instant(snapshot['decision_at'])
    observations = snapshot.get('observations')
    if not isinstance(observations, list) or not observations or len(observations) > MAX_OBSERVATIONS:
        raise ValueError('invalid_observation_count')
    histories, universe, contexts, clocks = {}, {}, {}, {}
    for observation in observations:
        ticker = observation['ticker']
        if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,15}', ticker):
            raise ValueError('invalid_symbol')
        if ticker in histories:
            raise ValueError('duplicate_symbol_in_snapshot')
        cutoff = instant(snapshot['calculation_at']).astimezone(ET).date() if snapshot.get('calculation_at') else None
        if observation.get('source_unavailable_reason'):
            frame = None
            info = {'source_observed_at': observation.get('source_observed_at'),
                    'source_unavailable_reason': observation['source_unavailable_reason'], 'completed_bars': 0}
        else:
            frame, info = frame_from_observation(observation, decision, market_cutoff=cutoff)
        histories[ticker] = frame
        universe[ticker] = {'symbol': ticker, 'company': observation.get('company') or ticker}
        context = deepcopy(observation.get('context') or {})
        if observation.get('detector_bars') is not None and frame is not None:
            detector, detector_info = frame_from_observation(dict(observation, bars=observation['detector_bars']),
                                                            decision, market_cutoff=cutoff)
            context['history_frame'] = detector
            info['independent_frame'] = detector_info
            info['baseline_window'] = 'EXPLICIT_SEPARATE_6_CALENDAR_MONTH_FRAME'
        for prefix in ('benchmark', 'sector'):
            bars = context.pop(prefix + '_bars', None)
            if bars is not None:
                source = context.get(prefix + '_observed_at')
                linked, _ = frame_from_observation({'bars': bars, 'source_observed_at': source}, decision,
                                                    market_cutoff=cutoff)
                context[prefix + '_frame'] = linked
        contexts[ticker] = context
        clocks[ticker] = info
    context = deepcopy(snapshot.get('context') or {})
    context['by_ticker'] = contexts
    return histories, universe, context, clocks


def expanded_acquisition_dataset(path, *, comparison_decision_at=None):
    """Frozen108 cohort: real observation clocks, eight NONEXECUTABLE prefixes.

    The separate calculation clock never substitutes for first_seen/availability.
    Baseline/common metrics receive six calendar months; detectors receive the
    longer prefix. Failed/unavailable symbols remain in every denominator.
    """
    import pandas as pd
    acquisition, digest = read_json(path)
    manifest, _ = read_json(Path(path).parent / 'manifest.json', acquisition['manifest_sha256'])
    benchmark, benchmark_hash = read_json(manifest['benchmark_artifact'], manifest['benchmark_artifact_sha256'])
    packets, statuses, receipts = {}, {}, []
    for row in acquisition['rows']:
        ticker = row['symbol']
        statuses[ticker] = row['status']
        if row['status'] not in {'ACQUIRED_VALIDATED', 'REUSED_VALIDATED'}:
            continue
        packet, packet_hash = read_json(row['artifact_path'], row['artifact_sha256'])
        if packet['symbol'] != ticker or packet['metadata'].get('symbol') != ticker:
            raise ValueError('expanded_exact_mapping_mismatch')
        packets[ticker] = packet
        receipts.append({'symbol': ticker, 'artifact_sha256': packet_hash,
                         'source_observed_at': packet['source_observed_at']})
    if [r['symbol'] for r in acquisition['rows']] != manifest['symbols']:
        raise ValueError('expanded_frozen_cohort_order_mismatch')
    decision = instant(comparison_decision_at) if comparison_decision_at else datetime.now(UTC)
    source_max = max([instant(benchmark['source_observed_at'])] +
                     [instant(p['source_observed_at']) for p in packets.values()])
    if decision < source_max:
        raise ValueError('comparison_before_actual_sources')
    sessions = [(day, True) for day in manifest['cutoff_sessions']]
    sessions.append((max(r['date'] for r in benchmark['adjusted_rows']), False))
    snapshots = []
    for day, component in sessions:
        calculation = datetime.combine(datetime.fromisoformat(day).date(), time(16, 10), ET).astimezone(UTC)
        if not component:
            calculation = decision
        window_start = (pd.Timestamp(calculation.astimezone(ET).date()) - pd.DateOffset(months=6)).date().isoformat()
        observations = []
        for ticker in manifest['symbols']:
            packet = packets.get(ticker)
            if packet is None:
                observations.append({'ticker': ticker, 'source_unavailable_reason': statuses[ticker],
                                     'bars': [], 'context': {'expected_session': day}})
                continue
            prefix = [row for row in packet['adjusted_rows'] if row['date'] <= day]
            observations.append({'ticker': ticker, 'bars': [row for row in prefix if row['date'] >= window_start],
                'detector_bars': prefix, 'source_observed_at': packet['source_observed_at'],
                'context': {'expected_session': day,
                    'benchmark_bars': [row for row in benchmark['adjusted_rows'] if row['date'] <= day],
                    'benchmark_observed_at': benchmark['source_observed_at']}})
        snapshot = {'snapshot_id': ('component_' if component else 'actual_current_') + day,
                    'decision_at': decision.isoformat(), 'market_cutoff': day,
                    'evidence_scope': 'RETROSPECTIVE_NONEXECUTABLE_COMPONENT' if component else 'CURRENT_OBSERVED_DISCOVERY',
                    'observations': observations}
        if component:
            snapshot['calculation_at'] = calculation.isoformat()
        snapshots.append(snapshot)
    return {'version': 1, 'synthetic': False,
        'kind': 'CURRENT_OBSERVED_AND_NONEXECUTABLE_RETROSPECTIVE_COMPONENTS',
        'input_receipt_sha256': digest, 'manifest_sha256': acquisition['manifest_sha256'],
        'source_receipts': receipts, 'acquisition_status_counts': acquisition['status_counts'],
        'benchmark_receipt': {'symbol': 'SPY', 'artifact_sha256': benchmark_hash,
                              'source_observed_at': benchmark['source_observed_at']},
        'cfg': DEFAULT_CFG, 'snapshots': snapshots, 'limitations': manifest['limits_of_inference'] + [
            'Eight prefix snapshots are retrospective component calculations observed today, not historical eligible decisions/PIT/OOS.',
            'The latest historical cutoff and current snapshot share a market session; they are not independent trading opportunities.',
            'Baseline6mo window is distinct from2y detector prefix; no reseeding baseline with long history.',
            'Missing actual earnings release facts remain UNKNOWN; no historical AI, quote, entry, fill or outcome generated.']}


def causal_value(value):
    """Complete causal research-cache key, including frame values/index/attrs."""
    if hasattr(value, 'to_dict') and hasattr(value, 'index') and hasattr(value, 'attrs'):
        return {'frame_index': [str(x) for x in value.index], 'columns': list(value.columns),
                'values': causal_value(value.to_dict(orient='records')), 'attrs': causal_value(value.attrs)}
    if isinstance(value, dict):
        return {str(k): causal_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [causal_value(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, 'item'):
        return value.item()
    raise ValueError('unsupported_causal_cache_type:' + type(value).__name__)


@contextmanager
def research_memoization(enabled):
    """Research-process-only, bounded/deep-copy cache of exact application calls.

    All5 independent detectors are evaluated together once, then selected without
    changing their formulas. No application runtime/cache/DB state is modified.
    QA independently repeats an unmemoized subset.
    """
    if not enabled:
        yield
        return
    import stock_scanner
    import entry_strategies
    original_analyze, original_detect = stock_scanner.analyze_history, entry_strategies.detect_all
    cache = {}
    def cached(kind, material, calculate):
        key = (kind, sha(causal_value(material)))
        if key not in cache:
            if len(cache) >= 6000:
                raise ValueError('research_memoization_bound')
            cache[key] = deepcopy(calculate())
        return deepcopy(cache[key])
    def analyze(*args, **kwargs):
        material_args = list(args)
        # The actual analyzer does not read entry_strategy_ids; that key only
        # selects independent OR routes in the caller. Preserve every other
        # supplied config value, the filter switch, data, attrs and both clocks.
        if len(material_args) >= 4 and isinstance(material_args[3], dict):
            material_args[3] = {key: value for key, value in material_args[3].items()
                                if key != 'entry_strategy_ids'}
        return cached('analyze', [material_args, kwargs], lambda: original_analyze(*args, **kwargs))
    def detect(frame, *, decision_at, source_observed_at, enabled_ids=None, context=None):
        requested = tuple(entry_strategies.STRATEGY_IDS if enabled_ids is None else enabled_ids)
        # A disabled strategy's malformed override must not contaminate another
        # arm. Custom configurations use the exact requested-ID helper without
        # this default-config bulk optimization. Preserve empty/invalid-ID API
        # validation semantics as well.
        if (not requested or len(requested) != len(set(requested)) or
                set(requested) - set(entry_strategies.STRATEGY_IDS) or (context or {}).get('configs')):
            return original_detect(frame, decision_at=decision_at, source_observed_at=source_observed_at,
                                   enabled_ids=requested, context=context)
        material = [frame, decision_at, source_observed_at, context, entry_strategies.DEFAULT_CONFIGS]
        all_results = cached('detect', material, lambda: original_detect(frame, decision_at=decision_at,
            source_observed_at=source_observed_at, context=context))
        return {key: deepcopy(all_results[key]) for key in requested}
    stock_scanner.analyze_history, entry_strategies.detect_all = analyze, detect
    try:
        yield
    finally:
        stock_scanner.analyze_history, entry_strategies.detect_all = original_analyze, original_detect


def acquisition_dataset(path, benchmark_artifact=None, *, comparison_decision_at=None):
    """Read explicit frozen private20-symbol artifacts; no new provider fetch."""
    acquisition, digest = read_json(path)
    parent = Path(path).resolve().parent
    rows = acquisition.get('rows') or []
    observations, decisions = [], []
    for row in rows:
        if row.get('status') != 'ACQUIRED_AND_EVALUATED':
            raise ValueError('acquisition_incomplete_no_success_only_subset')
        filename = row['artifact']
        artifact_path = (parent / filename).resolve()
        if artifact_path.parent != parent:
            raise ValueError('artifact_not_in_frozen_directory')
        artifact, _ = read_json(artifact_path, row['artifact_sha256'])
        if artifact['symbol'] != row['symbol']:
            raise ValueError('symbol_mapping_mismatch')
        observations.append({'ticker': row['symbol'], 'bars': artifact['adjusted_rows'],
                             'source_observed_at': artifact['source_observed_at'],
                             'context': {'expected_session': artifact['expected_session']}})
        decisions.append(instant(artifact['decision_at']))
    if not decisions or len(rows) > MAX_OBSERVATIONS:
        raise ValueError('empty_or_oversized_acquisition')
    benchmark_context = {}
    benchmark_receipt = None
    if benchmark_artifact:
        benchmark, benchmark_hash = read_json(benchmark_artifact)
        if benchmark.get('symbol') != 'SPY':
            raise ValueError('research_benchmark_must_be_explicit_SPY_packet')
        benchmark_observed = instant(benchmark['source_observed_at'])
        benchmark_decision = instant(benchmark['decision_at'])
        if benchmark_observed > benchmark_decision:
            raise ValueError('benchmark_not_available_at_recorded_decision')
        decisions.append(benchmark_decision)
        # The later benchmark creates a NEW actual observed-now comparison,
        # never a retroactive source injected into the earlier stock decisions.
        actual_comparison = instant(comparison_decision_at) if comparison_decision_at else datetime.now(UTC)
        if actual_comparison < max(decisions):
            raise ValueError('comparison_before_actual_sources')
        decisions.append(actual_comparison)
        benchmark_context = {'benchmark_bars': benchmark['adjusted_rows'],
                             'benchmark_observed_at': benchmark_observed.isoformat()}
        for observation in observations:
            observation['context'].update(deepcopy(benchmark_context))
        benchmark_receipt = {'symbol': 'SPY', 'artifact_sha256': benchmark_hash,
                             'source_observed_at': benchmark_observed.isoformat(),
                             'recorded_decision_at': benchmark_decision.isoformat()}
    elif comparison_decision_at:
        requested = instant(comparison_decision_at)
        if requested < max(decisions):
            raise ValueError('comparison_before_actual_sources')
        decisions.append(requested)
    return {'version': 1, 'synthetic': False,
            'kind': 'CURRENT_OBSERVED_RETROSPECTIVE_VENDOR_DATA',
            'input_receipt_sha256': digest, 'benchmark_receipt': benchmark_receipt, 'cfg': DEFAULT_CFG,
            'snapshots': [{'snapshot_id': 'frozen_public20_current_observation',
                           'decision_at': max(decisions).isoformat(), 'observations': observations}],
            'limitations': ['Downloaded18October2026; not historical system availability or a PIT universe.',
                            'Yahoo auto_adjust OHLC from raw*AdjClose/Close; volume untouched by helper.',
                            'No verified earnings facts, verified optional sector, AI, executable quotes or trade outcomes supplied.',
                            'SPY packet, if provided, was acquired later: use a new current decision after all actual sources; never insert it into the earlier18:18 decision.']}


def performance_unavailable():
    return {'status': 'DATA_INSUFFICIENT', 'win_rate': None, 'net_expectancy_R': None,
            'profit_factor': None, 'maximum_drawdown': None,
            'why': 'No immutable matched actual AI/order/legal-entry/partial-exit/fee ledger or independent holdout. Discovery labels and mock outcomes are not performance.'}


def code_fingerprint(path):
    """Hash canonical Git-style LF code, not Windows checkout EOL bytes.

    Do not use this helper for immutable vendor data/receipt hashes: those keep
    their exact original bytes in read_json/acquisition_dataset.
    """
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def implementation_hashes():
    files = ('entry_discovery.py', 'entry_strategies.py', 'stock_scanner.py', 'scanner_targets.py',
             'entry_strategy_execution.py', 'single_target_policy.py', 'single_breakout_policy.py',
             'vendor/entry_discovery/vcp_pattern_calculator.py', 'vendor/entry_discovery/stockbee.py')
    return {name: code_fingerprint(SERVER / name)
            for name in files if (SERVER / name).is_file()}


def component_reference_probe(candidate, decision):
    """Diagnostic at actual recorded daily close, never an executable quote.

    The original pure BUY/SINGLE builder is called without capture/AI/HTTP. A
    successful calculation is only a structural component result; it does not
    pass session/quote/news/confidence/budget/exposure or generate an order.
    """
    if candidate['technical_direction'] != 'BUY':
        return {'structural': 'NOT_PROBED_BASELINE_SELL', 'branch': 'NOT_PROBED_BASELINE_SELL'}
    from single_target_policy import build
    from single_breakout_policy import build as breakout_build
    from entry_strategy_execution import branches_from_discovery
    price = candidate['entry']
    source = candidate.get('single_target_source') or {
        'atr': candidate['atr'], 'zones': candidate.get('price_zones', []),
        'data_as_of': candidate.get('price_as_of', '')}
    try:
        try:
            plan = build(price, source['atr'], source['zones'], source['data_as_of'], decision.isoformat())
        except ValueError as exc:
            if str(exc) != 'no_forward_zone':
                raise
            plan = breakout_build(price, source['atr'], source['zones'], source['data_as_of'],
                                  decision.isoformat(), candidate.get('recent_high_20d'))
        structural = 'REFERENCE_COMPONENT_' + plan['policy_version']
    except ValueError as exc:
        structural = 'REFERENCE_BLOCK:' + str(exc)
    package = candidate.get('entry_discovery')
    if not package:
        branch = 'BASELINE_ORIGINAL_GATES_NO_NEW_BRANCH'
    else:
        try:
            branches = branches_from_discovery(package, allow_component=True)
            if not branches:
                branch = 'BASELINE_ORIGINAL_GATES_NO_NEW_BRANCH'
            elif any(row['support'] < price <= row['ceiling'] for row in branches):
                branch = 'REFERENCE_INSIDE_NECESSARY_BRANCH_INTERVAL_NOT_ENTRY'
            elif all(price <= row['support'] for row in branches):
                branch = 'REFERENCE_BELOW_SUPPORT'
            elif all(price > row['ceiling'] for row in branches):
                branch = 'REFERENCE_ABOVE_CHASE'
            else:
                branch = 'REFERENCE_OUTSIDE_ALL_NECESSARY_BRANCH_INTERVALS'
        except ValueError as exc:
            branch = 'REFERENCE_PROJECTION_BLOCK:' + str(exc)
    return {'structural': structural, 'branch': branch,
            'reference_kind': 'COMPLETED_DAILY_CLOSE_NOT_EXECUTABLE',
            'price': price, 'reference_at': candidate.get('price_as_of')}


def compare(dataset, *, discover=None, rank=None, include_details=True, memoize=False, reference_probes=False):
    with research_memoization(memoize):
        return _compare(dataset, discover=discover, rank=rank, include_details=include_details,
                        reference_probes=reference_probes)


def _compare(dataset, *, discover=None, rank=None, include_details=True, reference_probes=False):
    source_before = implementation_hashes()
    if dataset.get('version') != 1 or not isinstance(dataset.get('synthetic'), bool):
        raise ValueError('dataset_version_or_evidence_class_required')
    snapshots = dataset.get('snapshots')
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= MAX_SNAPSHOTS:
        raise ValueError('invalid_snapshot_count')
    if len({s['snapshot_id'] for s in snapshots}) != len(snapshots):
        raise ValueError('duplicate_snapshot_id')
    cfg = dict(DEFAULT_CFG, **(dataset.get('cfg') or {}))
    if cfg['shortlist_limit'] != 25 or cfg['ai_candidate_limit'] != 6:
        raise ValueError('comparison_requires_frozen_shared_25_6_caps')
    cursor = int(dataset.get('cursor', 0))
    if discover is None or rank is None:
        from entry_discovery import discover_candidates, rank_candidates
        discover = discover or discover_candidates
        rank = rank or rank_candidates
    matrix, details, opportunity_sets, ai_sets = [], {}, {}, {}
    all_probes = {}
    prepared = [(snapshot, prepare_snapshot(snapshot)) for snapshot in snapshots]
    for arm_name, baseline, ids in ARMS:
        opportunities, shortlist_keys, planned_ai, source_configurations, market_directions = set(), set(), set(), set(), set()
        reasons, states = Counter(), Counter()
        strategy_counts = Counter()
        arm_details, snapshot_rows = [], []
        structural, branches = Counter(), Counter()
        mock_counts = Counter()
        for snapshot, (histories, universe, context, clocks) in prepared:
            arm_cfg = dict(cfg, entry_strategy_ids=list(ids))
            arguments = dict(decision_at=instant(snapshot['decision_at']),
                             context=deepcopy(context), include_baseline=baseline)
            if snapshot.get('calculation_at'):
                arguments['calculation_at'] = instant(snapshot['calculation_at'])
            candidates, observations = discover(deepcopy(histories), deepcopy(universe), arm_cfg, **arguments)
            if len({c['ticker'] for c in candidates}) != len(candidates):
                raise AssertionError('application_returned_duplicate_ticker_candidates')
            ordered = rank(candidates, cursor=cursor)
            if {c['ticker'] for c in ordered} != {c['ticker'] for c in candidates} or len(ordered) != len(candidates):
                raise AssertionError('ranking_lost_or_duplicated_candidates')
            shortlist = ordered[:cfg['shortlist_limit']]
            planned = shortlist[:cfg['ai_candidate_limit']]
            key = lambda c: (snapshot['snapshot_id'], c['ticker'], c['technical_direction'])
            opportunities.update(key(c) for c in candidates)
            shortlist_keys.update(key(c) for c in shortlist)
            planned_ai.update(key(c) for c in planned)
            market_directions.update((snapshot.get('market_cutoff', snapshot['snapshot_id']),
                c['ticker'], c['technical_direction']) for c in candidates)
            source_configurations.update((c['ticker'], c['technical_direction'],
                clocks[c['ticker']].get('consumed_source_sha256'),
                clocks[c['ticker']].get('independent_frame', {}).get('consumed_source_sha256')) for c in candidates)
            snapshot_structural, snapshot_branches = Counter(), Counter()
            if reference_probes:
                for candidate in candidates:
                    probe_key = sha([candidate, snapshot['decision_at']])
                    if probe_key not in all_probes:
                        all_probes[probe_key] = component_reference_probe(candidate, instant(snapshot['decision_at']))
                    probe = all_probes[probe_key]
                    snapshot_structural[probe['structural']] += 1
                    snapshot_branches[probe['branch']] += 1
                structural.update(snapshot_structural)
                branches.update(snapshot_branches)
            for candidate in candidates:
                for strategy_id in set(candidate['strategy_ids']):
                    strategy_counts[strategy_id] += 1
            for observation in observations:
                reasons.update('common:' + value for value in observation['common_reasons'])
                for strategy_id in ids:
                    record = observation['strategy_results'].get(strategy_id)
                    if record is None:
                        states[strategy_id + ':NOT_EVALUATED_COMMON_GATES'] += 1
                    else:
                        states[strategy_id + ':' + record['state']] += 1
                        reasons.update(strategy_id + ':' + value for value in record.get('reasons', []))
            mocked = {o['ticker']: o.get('mock_outcome') for o in snapshot['observations'] if o.get('mock_outcome')}
            if mocked and not dataset['synthetic']:
                raise ValueError('mock_outcomes_forbidden_for_real_dataset')
            for candidate in planned:
                outcome = mocked.get(candidate['ticker'])
                if outcome:
                    for field in ('ai_reviewed', 'ai_approved', 'signal', 'order', 'entry'):
                        mock_counts[field] += int(outcome.get(field) is True)
            snapshot_rows.append({'snapshot_id': snapshot['snapshot_id'],
                'evidence_scope': snapshot.get('evidence_scope', dataset.get('kind')),
                'market_cutoff': snapshot.get('market_cutoff'), 'calculation_at': snapshot.get('calculation_at'),
                'candidate_count': len(candidates), 'planned_shortlist_count': len(shortlist),
                'planned_shared_AI_slot_count': len(planned),
                'candidate_directions': dict(Counter(c['technical_direction'] for c in candidates)),
                'candidate_tickers': sorted(c['ticker'] for c in candidates),
                'planned_AI_slot_tickers': [c['ticker'] for c in planned],
                'reference_structural_components': dict(snapshot_structural),
                'reference_branch_intervals': dict(snapshot_branches)})
            if include_details:
                arm_details.append({'snapshot_id': snapshot['snapshot_id'],
                                    'decision_at': snapshot['decision_at'], 'source_clocks': clocks,
                                    'calculation_at': snapshot.get('calculation_at'),
                                    'candidate_tickers': [c['ticker'] for c in candidates],
                                    'ordered_tickers': [c['ticker'] for c in ordered],
                                    'planned_shortlist_tickers': [c['ticker'] for c in shortlist],
                                    'planned_AI_slot_tickers': [c['ticker'] for c in planned],
                                    'observations': observations})
        opportunity_sets[arm_name] = opportunities
        ai_sets[arm_name] = planned_ai
        matrix.append({'arm': arm_name, 'include_baseline': baseline, 'enabled_ids': list(ids),
                       'opportunity_observations': len(opportunities),
                       'unique_candidate_symbols': len({key[1] for key in opportunities}),
                       'unique_market_source_configurations': len(source_configurations),
                       'unique_market_symbol_direction_observations': len(market_directions),
                       'candidate_directions': dict(Counter(key[2] for key in opportunities)),
                       'strategy_attributions_nonexclusive': dict(strategy_counts),
                       'planned_shortlist_observations': len(shortlist_keys),
                       'planned_max_shared_AI_slots': len(planned_ai),
                       'planned_AI_slot_directions': dict(Counter(key[2] for key in planned_ai)),
                       'actual_AI_reviews': None, 'actual_AI_approvals': None,
                       'actual_signals': None, 'actual_orders': None, 'actual_entries': None,
                       'actual_outcome_status': 'NOT_VERIFIED_NO_IMMUTABLE_MATCHED_OUTCOMES',
                       'synthetic_mock_outcomes': dict(mock_counts) if dataset['synthetic'] else None,
                       'states': dict(states), 'block_reasons': dict(reasons),
                       'snapshot_results': snapshot_rows,
                       'nonexecutable_reference_structural_components': dict(structural),
                       'nonexecutable_reference_branch_intervals': dict(branches),
                       'performance': performance_unavailable()})
        if include_details:
            details[arm_name] = arm_details
    baseline_set = opportunity_sets['BASELINE']
    for row in matrix:
        arm_set = opportunity_sets[row['arm']]
        row['overlap_vs_baseline'] = {'shared_opportunity_observations': len(arm_set & baseline_set),
                                      'additional_to_baseline': len(arm_set - baseline_set),
                                      'baseline_not_in_this_arm': len(baseline_set - arm_set)}
        row['planned_AI_competition_vs_baseline'] = {
            'retained_baseline_slots': len(ai_sets[row['arm']] & ai_sets['BASELINE']),
            'different_selected_slots': len(ai_sets[row['arm']] - ai_sets['BASELINE']),
            'baseline_slots_displaced': len(ai_sets['BASELINE'] - ai_sets[row['arm']])}
    result = {'version': 1, 'scope': 'PAIRED_OFFLINE_DISCOVERY_ONLY_NOT_PAPER_BACKTEST',
              'evidence_class': dataset.get('kind'), 'synthetic': dataset['synthetic'],
              'dataset_content_sha256': sha(dataset), 'snapshot_count': len(snapshots),
              'source_snapshot_clocks': [{'snapshot_id': s['snapshot_id'], 'decision_at': s['decision_at'],
                  'calculation_at': s.get('calculation_at'), 'market_cutoff': s.get('market_cutoff'),
                  'source_observed_at_min': min((o['source_observed_at'] for o in s['observations'] if o.get('source_observed_at')), default=None),
                  'source_observed_at_max': max((o['source_observed_at'] for o in s['observations'] if o.get('source_observed_at')), default=None)} for s in snapshots],
              'input_receipt_sha256': dataset.get('input_receipt_sha256'),
              'benchmark_receipt': dataset.get('benchmark_receipt'),
              'manifest_sha256': dataset.get('manifest_sha256'),
              'source_receipts': dataset.get('source_receipts'),
              'acquisition_status_counts': dataset.get('acquisition_status_counts'),
              'implementation_sha256': source_before,
              'implementation_stable_during_comparison': source_before == implementation_hashes(),
              'code_hash_newline_policy': 'LF',
              'comparator_sha256': code_fingerprint(__file__),
              'fixture_source_sha256': dataset.get('fixture_source_sha256'),
              'input_observations': sum(len(s['observations']) for s in snapshots),
              'unique_input_symbols': len({o['ticker'] for s in snapshots for o in s['observations']}),
              'shared_caps_per_snapshot': {'shortlist': 25, 'max_AI': 6, 'cursor': cursor},
              'matrix': matrix, 'comparison_limits': [
                  'Discovery candidates/planned slots are not AI approvals, accepted signals, orders or legal entries.',
                  'No quote/session/news/confidence/risk/target/entry gate is declared passed by this comparison.',
                  'Actual strategy records and ranking helper reused; no bonus per additional label or multiplied AI cap.',
                  'Source availability and bar completion respected in both arms; retrospective vendor revisions or universe selection are not PIT proof.',
                  'No price-touch/intrabar fill, historical AI, WR/PF/expectancy/drawdown or independent OOS outcome invented.'],
              'component_reference_probe_scope': 'DAILY_CLOSE_STRUCTURAL_AND_NECESSARY_INTERVAL_ONLY_NOT_ADMISSION' if reference_probes else 'NOT_RUN',
              'input_limitations': dataset.get('limitations', []),
              'safety': {'network_calls': 0, 'application_DB_calls': 0, 'AI_calls': 0,
                         'Telegram_calls': 0, 'orders_fills_created': 0, 'Production_calls': 0}}
    if include_details:
        result['details'] = details
    return result


def fixture_dataset():
    path = REPO / 'research' / 'fixtures' / 'entry_strategy_dataset.py'
    spec = importlib.util.spec_from_file_location('entry_strategy_research_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_dataset()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dataset')
    group.add_argument('--acquisition-result')
    group.add_argument('--expanded-acquisition-result')
    group.add_argument('--synthetic-fixture', action='store_true')
    parser.add_argument('--benchmark-artifact')
    parser.add_argument('--comparison-decision-at', help='Replay an explicitly recorded actual comparison clock, never before source observations.')
    parser.add_argument('--summary-only', action='store_true')
    parser.add_argument('--memoize', action='store_true', help='Bounded research-only exact causal helper cache; QA must replay an unmemoized subset.')
    parser.add_argument('--reference-probes', action='store_true', help='Nonexecutable actual daily-close structural/interval components only.')
    args = parser.parse_args()
    if (args.benchmark_artifact or args.comparison_decision_at) and not (args.acquisition_result or args.expanded_acquisition_result):
        parser.error('benchmark/recorded comparison clock require --acquisition-result')
    with offline_only():
        if args.expanded_acquisition_result:
            dataset = expanded_acquisition_dataset(args.expanded_acquisition_result,
                comparison_decision_at=args.comparison_decision_at)
        elif args.acquisition_result:
            dataset = acquisition_dataset(args.acquisition_result, args.benchmark_artifact,
                                           comparison_decision_at=args.comparison_decision_at)
        elif args.dataset:
            dataset, _ = read_json(args.dataset)
        else:
            dataset = fixture_dataset()
        result = compare(dataset, include_details=not args.summary_only, memoize=args.memoize,
                         reference_probes=args.reference_probes)
    print(json.dumps(result, sort_keys=True, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
