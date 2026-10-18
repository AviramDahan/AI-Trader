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


def frame_from_observation(observation, decision):
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
        if available > min(observed, decision):
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
        frame, info = frame_from_observation(observation, decision)
        histories[ticker] = frame
        universe[ticker] = {'symbol': ticker, 'company': observation.get('company') or ticker}
        context = deepcopy(observation.get('context') or {})
        for prefix in ('benchmark', 'sector'):
            bars = context.pop(prefix + '_bars', None)
            if bars is not None:
                source = context.get(prefix + '_observed_at')
                linked, _ = frame_from_observation({'bars': bars, 'source_observed_at': source}, decision)
                context[prefix + '_frame'] = linked
        contexts[ticker] = context
        clocks[ticker] = info
    context = deepcopy(snapshot.get('context') or {})
    context['by_ticker'] = contexts
    return histories, universe, context, clocks


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
             'vendor/entry_discovery/vcp_pattern_calculator.py', 'vendor/entry_discovery/stockbee.py')
    return {name: code_fingerprint(SERVER / name)
            for name in files if (SERVER / name).is_file()}


def compare(dataset, *, discover=None, rank=None, include_details=True):
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
    matrix, details, opportunity_sets = [], {}, {}
    prepared = [(snapshot, prepare_snapshot(snapshot)) for snapshot in snapshots]
    for arm_name, baseline, ids in ARMS:
        opportunities, shortlist_keys, planned_ai = set(), set(), set()
        reasons, states = Counter(), Counter()
        strategy_counts = Counter()
        arm_details = []
        mock_counts = Counter()
        for snapshot, (histories, universe, context, clocks) in prepared:
            arm_cfg = dict(cfg, entry_strategy_ids=list(ids))
            candidates, observations = discover(deepcopy(histories), deepcopy(universe), arm_cfg,
                                                decision_at=instant(snapshot['decision_at']),
                                                context=deepcopy(context), include_baseline=baseline)
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
            if include_details:
                arm_details.append({'snapshot_id': snapshot['snapshot_id'],
                                    'decision_at': snapshot['decision_at'], 'source_clocks': clocks,
                                    'candidate_tickers': [c['ticker'] for c in candidates],
                                    'ordered_tickers': [c['ticker'] for c in ordered],
                                    'planned_shortlist_tickers': [c['ticker'] for c in shortlist],
                                    'planned_AI_slot_tickers': [c['ticker'] for c in planned],
                                    'observations': observations})
        opportunity_sets[arm_name] = opportunities
        matrix.append({'arm': arm_name, 'include_baseline': baseline, 'enabled_ids': list(ids),
                       'opportunity_observations': len(opportunities),
                       'unique_candidate_symbols': len({key[1] for key in opportunities}),
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
                       'performance': performance_unavailable()})
        if include_details:
            details[arm_name] = arm_details
    baseline_set = opportunity_sets['BASELINE']
    for row in matrix:
        arm_set = opportunity_sets[row['arm']]
        row['overlap_vs_baseline'] = {'shared_opportunity_observations': len(arm_set & baseline_set),
                                      'additional_to_baseline': len(arm_set - baseline_set),
                                      'baseline_not_in_this_arm': len(baseline_set - arm_set)}
    result = {'version': 1, 'scope': 'PAIRED_OFFLINE_DISCOVERY_ONLY_NOT_PAPER_BACKTEST',
              'evidence_class': dataset.get('kind'), 'synthetic': dataset['synthetic'],
              'dataset_content_sha256': sha(dataset), 'snapshot_count': len(snapshots),
              'source_snapshot_clocks': [{'snapshot_id': s['snapshot_id'], 'decision_at': s['decision_at'],
                  'source_observed_at_min': min(o['source_observed_at'] for o in s['observations']),
                  'source_observed_at_max': max(o['source_observed_at'] for o in s['observations'])} for s in snapshots],
              'input_receipt_sha256': dataset.get('input_receipt_sha256'),
              'benchmark_receipt': dataset.get('benchmark_receipt'),
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
    group.add_argument('--synthetic-fixture', action='store_true')
    parser.add_argument('--benchmark-artifact')
    parser.add_argument('--comparison-decision-at', help='Replay an explicitly recorded actual comparison clock, never before source observations.')
    parser.add_argument('--summary-only', action='store_true')
    args = parser.parse_args()
    if (args.benchmark_artifact or args.comparison_decision_at) and not args.acquisition_result:
        parser.error('benchmark/recorded comparison clock require --acquisition-result')
    with offline_only():
        if args.acquisition_result:
            dataset = acquisition_dataset(args.acquisition_result, args.benchmark_artifact,
                                           comparison_decision_at=args.comparison_decision_at)
        elif args.dataset:
            dataset, _ = read_json(args.dataset)
        else:
            dataset = fixture_dataset()
        result = compare(dataset, include_details=not args.summary_only)
    print(json.dumps(result, sort_keys=True, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
