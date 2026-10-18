"""Research controls, not trading performance or a live connection proof."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'service' / 'server'))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare = load('entry_comparison_controls', 'research/scripts/compare_entry_strategies.py')
fixtures = load('entry_dataset_controls', 'research/fixtures/entry_strategy_dataset.py')


@pytest.fixture(scope='module')
def actual_fixture_result():
    with compare.offline_only():
        return compare.compare(fixtures.build_dataset())


@pytest.mark.parametrize('strategy_id', compare.STRATEGIES)
def test_each_actual_strategy_has_common_eligible_baseline_missed_control(strategy_id):
    import entry_strategies
    import stock_scanner
    frame, context, decision, observed = fixtures.positive_baseline_miss(strategy_id)
    with compare.offline_only():
        result = entry_strategies.detect_all(frame, decision_at=decision, source_observed_at=observed,
            enabled_ids=[strategy_id], context=context)[strategy_id]
        assert result['state'] == 'DETECTED', result
        assert stock_scanner.analyze_history('SYNTH', 'Synthetic', frame, compare.DEFAULT_CFG,
                                            decision_at=decision) is None
        common = stock_scanner.analyze_history('SYNTH', 'Synthetic', frame, compare.DEFAULT_CFG,
                                               baseline_filter=False, decision_at=decision)
        assert common is not None
        assert common['baseline_buy_score'] < compare.DEFAULT_CFG['min_technical_score']
        assert common['baseline_sell_score'] < compare.DEFAULT_CFG['min_technical_score']


def test_matrix_has_exact12_arms_and_all_actual_paths_add_missed_candidates(actual_fixture_result):
    matrix = {row['arm']: row for row in actual_fixture_result['matrix']}
    assert len(matrix) == 12
    assert matrix['BASELINE']['opportunity_observations'] == 1
    for strategy_id in compare.STRATEGIES:
        assert matrix[strategy_id + '_ONLY']['opportunity_observations'] >= 1
        assert matrix['BASELINE_PLUS_' + strategy_id]['overlap_vs_baseline']['additional_to_baseline'] >= 1
    assert matrix['BASELINE_PLUS_ALL']['opportunity_observations'] == 6
    assert matrix['BASELINE_PLUS_ALL']['planned_max_shared_AI_slots'] == 6


def test_overlap_is_attribution_not_duplicate_opportunity_or_extra_AI(actual_fixture_result):
    all_row = actual_fixture_result['matrix'][-1]
    assert sum(all_row['strategy_attributions_nonexclusive'].values()) > all_row['opportunity_observations']
    detail = actual_fixture_result['details']['BASELINE_PLUS_ALL'][0]
    assert len(detail['ordered_tickers']) == len(set(detail['ordered_tickers'])) == 6


def test_declared_mock_pending_orders_are_not_actual_positions_or_returns(actual_fixture_result):
    all_row = actual_fixture_result['matrix'][-1]
    assert all_row['synthetic_mock_outcomes']['order'] == 5
    assert all_row['synthetic_mock_outcomes']['entry'] == 0
    for row in actual_fixture_result['matrix']:
        assert row['actual_AI_approvals'] is row['actual_orders'] is row['actual_entries'] is None
        assert row['performance']['status'] == 'DATA_INSUFFICIENT'
        assert row['performance']['win_rate'] is row['performance']['profit_factor'] is None


def test_same_asof_source_hash_excludes_future_and_late_processed_rows():
    dataset = fixtures.build_dataset()
    snapshot = dataset['snapshots'][0]
    observation = snapshot['observations'][0]
    decision = compare.instant(snapshot['decision_at'])
    _, original = compare.frame_from_observation(observation, decision)
    poisoned = copy.deepcopy(observation)
    poisoned['bars'].append({'date': '2026-10-06', 'Open': -1, 'High': -1,
        'Low': -1, 'Close': -1, 'Volume': -1, 'available_at': '2026-10-09T20:05:00Z'})
    _, later = compare.frame_from_observation(poisoned, decision)
    assert later['consumed_source_sha256'] == original['consumed_source_sha256']
    assert later['excluded_future_or_unavailable_bars'] == 1


def test_future_source_is_not_historical_first_seen():
    dataset = fixtures.build_dataset()
    snapshot = dataset['snapshots'][0]
    observation = copy.deepcopy(snapshot['observations'][0])
    observation['source_observed_at'] = '2026-10-07T00:00:00Z'
    frame, info = compare.frame_from_observation(observation, compare.instant(snapshot['decision_at']))
    assert frame.empty
    assert info['source_after_decision'] is True
    assert info['source_observed_at'] == '2026-10-07T00:00:00+00:00'


def test_pead_unknown_without_verified_release_and_RS_unknown_without_benchmark():
    import entry_strategies
    for strategy_id, missing in (('PEAD', 'earnings_events'),
                                 ('RELATIVE_STRENGTH_LEADER', 'benchmark_frame')):
        frame, context, decision, observed = fixtures.positive_baseline_miss(strategy_id)
        context.pop(missing)
        with compare.offline_only():
            result = entry_strategies.detect_all(frame, decision_at=decision,
                source_observed_at=observed, enabled_ids=[strategy_id], context=context)[strategy_id]
        assert result['state'] == 'UNKNOWN'


def test_zero_or_missing_outcomes_never_manufacture_performance(actual_fixture_result):
    assert actual_fixture_result['safety']['AI_calls'] == 0
    assert actual_fixture_result['safety']['orders_fills_created'] == 0
    assert all(row['performance']['maximum_drawdown'] is None for row in actual_fixture_result['matrix'])


def plumbing_dataset(count=40):
    strategies = ('BASELINE', *compare.STRATEGIES)
    bars = [{'date': '2026-10-05', 'Open': 100., 'High': 102., 'Low': 99., 'Close': 101., 'Volume': 1_000_000.}]
    observations = [{'ticker': f'T{i:03d}', 'company': strategies[i % len(strategies)],
        'bars': copy.deepcopy(bars), 'source_observed_at': '2026-10-06T14:00:00Z'} for i in range(count)]
    return {'version': 1, 'synthetic': True, 'kind': 'MOCK_DISCOVERY_PLUMBING_ONLY',
            'snapshots': [{'snapshot_id': 'plumbing_only', 'decision_at': '2026-10-06T14:00:37Z',
                           'observations': observations}]}


def mock_discover(histories, universe, cfg, *, decision_at, context, include_baseline):
    candidates, observations = [], []
    for ticker, member in universe.items():
        tags = member['company'].split('|')
        chosen = [tag for tag in tags if tag in cfg['entry_strategy_ids'] or tag == 'BASELINE' and include_baseline]
        results = {strategy: {'state': 'DETECTED' if strategy in tags else 'REJECTED', 'reasons': []}
                   for strategy in cfg['entry_strategy_ids']}
        observations.append({'ticker': ticker, 'baseline_detected': 'BASELINE' in tags,
                             'strategy_results': results, 'common_reasons': [], 'candidate_strategy_ids': chosen})
        if chosen:
            candidates.append({'ticker': ticker, 'technical_direction': 'BUY', 'technical_score': 4,
                               'strategy_ids': chosen, 'discovery_score': .7, 'average_dollar_volume': 50_000_000})
    return candidates, observations


def test_shared_caps_and_actual_fair_rank_are_not_multiplied_by5():
    from entry_discovery import rank_candidates
    dataset = plumbing_dataset()
    result = compare.compare(dataset, discover=mock_discover, rank=rank_candidates)
    all_row = result['matrix'][-1]
    assert all_row['opportunity_observations'] == 40
    assert all_row['planned_shortlist_observations'] == 25
    assert all_row['planned_max_shared_AI_slots'] == 6
    selected = result['details']['BASELINE_PLUS_ALL'][0]['planned_AI_slot_tickers']
    by_ticker = {o['ticker']: o['company'] for o in dataset['snapshots'][0]['observations']}
    assert {by_ticker[ticker] for ticker in selected} == {'BASELINE', *compare.STRATEGIES}


def test_permuted_input_keeps_actual_rank_deterministic():
    from entry_discovery import rank_candidates
    dataset = plumbing_dataset()
    first = compare.compare(dataset, discover=mock_discover, rank=rank_candidates)
    dataset['snapshots'][0]['observations'].reverse()
    other = compare.compare(dataset, discover=mock_discover, rank=rank_candidates)
    assert first['matrix'] == other['matrix']
    assert first['details']['BASELINE_PLUS_ALL'][0]['ordered_tickers'] == other['details']['BASELINE_PLUS_ALL'][0]['ordered_tickers']


def test_duplicate_snapshot_and_duplicate_ticker_are_rejected():
    dataset = plumbing_dataset(1)
    dataset['snapshots'].append(copy.deepcopy(dataset['snapshots'][0]))
    with pytest.raises(ValueError, match='duplicate_snapshot'):
        compare.compare(dataset, discover=mock_discover, rank=lambda rows, **kwargs: rows)
    dataset = plumbing_dataset(1)
    dataset['snapshots'][0]['observations'].append(copy.deepcopy(dataset['snapshots'][0]['observations'][0]))
    with pytest.raises(ValueError, match='duplicate_symbol'):
        compare.prepare_snapshot(dataset['snapshots'][0])


def test_mock_outcomes_forbidden_in_real_data_and_different_caps_rejected():
    dataset = plumbing_dataset(1)
    dataset['synthetic'] = False
    dataset['snapshots'][0]['observations'][0]['mock_outcome'] = {'entry': True}
    with pytest.raises(ValueError, match='mock_outcomes_forbidden'):
        compare.compare(dataset, discover=mock_discover, rank=lambda rows, **kwargs: rows)
    dataset = plumbing_dataset(1)
    dataset['cfg'] = {'ai_candidate_limit': 30}
    with pytest.raises(ValueError, match='frozen_shared_25_6_caps'):
        compare.compare(dataset, discover=mock_discover, rank=lambda rows, **kwargs: rows)


def test_later_benchmark_uses_new_actual_decision_without_relabeling_old_sources(monkeypatch):
    stock_observed = '2026-10-18T18:18:25+00:00'
    benchmark_observed = '2026-10-18T20:08:24+00:00'
    stock = {'symbol': 'A', 'adjusted_rows': [], 'source_observed_at': stock_observed,
             'decision_at': '2026-10-18T18:18:26+00:00', 'expected_session': '2026-10-16'}
    benchmark = {'symbol': 'SPY', 'adjusted_rows': [], 'source_observed_at': benchmark_observed,
                 'decision_at': '2026-10-18T20:08:25+00:00'}
    acquisition = {'rows': [{'status': 'ACQUIRED_AND_EVALUATED', 'symbol': 'A',
                             'artifact': 'A.json', 'artifact_sha256': 'stock-hash'}]}
    def read(path, expected_hash=None):
        name = Path(path).name
        return {'receipt.json': (acquisition, 'receipt-hash'),
                'A.json': (stock, 'stock-hash'), 'SPY.json': (benchmark, 'benchmark-hash')}[name]
    monkeypatch.setattr(compare, 'read_json', read)
    dataset = compare.acquisition_dataset(REPO / 'receipt.json', REPO / 'SPY.json',
                                         comparison_decision_at='2026-10-18T20:09:00+00:00')
    snapshot = dataset['snapshots'][0]
    assert snapshot['decision_at'] == '2026-10-18T20:09:00+00:00'
    assert snapshot['observations'][0]['source_observed_at'] == stock_observed
    assert snapshot['observations'][0]['context']['benchmark_observed_at'] == benchmark_observed
    with pytest.raises(ValueError, match='comparison_before_actual_sources'):
        compare.acquisition_dataset(REPO / 'receipt.json', REPO / 'SPY.json',
                                     comparison_decision_at='2026-10-18T18:19:00+00:00')


def test_json_duplicate_keys_nonfinite_and_wrong_receipt_hash_rejected(tmp_path):
    path = tmp_path / 'input.json'
    path.write_text('{"version":1,"version":2}', encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate_json_key'):
        compare.read_json(path)
    path.write_text('{"value":NaN}', encoding='utf-8')
    with pytest.raises(ValueError, match='nonfinite_json'):
        compare.read_json(path)
    path.write_text('{"version":1}', encoding='utf-8')
    with pytest.raises(ValueError, match='frozen_source_hash_mismatch'):
        compare.read_json(path, '0' * 64)


def test_code_fingerprint_normalizes_CRLF_but_artifact_receipts_keep_exact_bytes(tmp_path):
    lf, crlf = tmp_path / 'lf.py', tmp_path / 'crlf.py'
    lf.write_bytes(b'def value():\n    return 1\n')
    crlf.write_bytes(b'def value():\r\n    return 1\r\n')
    assert compare.code_fingerprint(lf) == compare.code_fingerprint(crlf)
    assert lf.read_bytes() != crlf.read_bytes()
    lf_json, crlf_json = tmp_path / 'lf.json', tmp_path / 'crlf.json'
    lf_json.write_bytes(b'{\n  "version": 1\n}\n')
    crlf_json.write_bytes(b'{\r\n  "version": 1\r\n}\r\n')
    lf_value, lf_hash = compare.read_json(lf_json)
    crlf_value, crlf_hash = compare.read_json(crlf_json)
    assert lf_value == crlf_value
    assert lf_hash != crlf_hash  # Immutable data receipts must NOT normalize.


def test_fixture_code_receipt_paths_are_canonical_POSIX_on_every_platform():
    dataset = fixtures.build_dataset()
    assert set(dataset['fixture_source_sha256']) == {
        'research/fixtures/entry_strategy_dataset.py',
        'service/server/tests/test_entry_strategies.py'}
    assert all('\\' not in name for name in dataset['fixture_source_sha256'])
