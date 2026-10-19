"""Optional strategy input adapters and audit boundary; no live providers."""
import copy
import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import entry_discovery as discovery
import entry_strategy_inputs as inputs
import entry_strategies as strategies
import stock_scanner as scanner
from test_entry_strategies import fixture_case, DECISION, OBSERVED


def typed_row():
    _, context, _, _ = fixture_case('PEAD')
    event = dict(context['earnings_events'][0], symbol='TEST')
    return dict(ticker='TEST', source_kind='official_earnings_release', headline_only=0,
        verified_tickers_json='["TEST"]', source_facts_json=json.dumps({'earnings_events': [event]}),
        collected_at=event['source_observed_at'], analyzed_at=event['processed_at'])


def test_off_input_context_does_not_read_db_or_download(monkeypatch):
    monkeypatch.setattr(inputs, 'load_long_histories', Mock(side_effect=AssertionError('download')))
    monkeypatch.setattr(inputs, 'load_verified_earnings', Mock(side_effect=AssertionError('DB')))
    assert inputs.load_context(['TEST'], {}, {}, {'entry_strategy_ids': []}) == {}


def test_typed_release_projection_preserves_true_clocks():
    row = typed_row()
    projected = inputs.verified_earnings_from_rows([row], ['TEST'], DECISION)['TEST'][0]
    original = json.loads(row['source_facts_json'])['earnings_events'][0]
    assert projected['released_at'] == original['released_at']
    assert discovery.instant(projected['source_observed_at']) == discovery.instant(row['collected_at'])
    assert projected['symbol'] == 'TEST'


@pytest.mark.parametrize('change', [
    {'source_kind': 'earnings_schedule'}, {'source_kind': 'SEC_8K'},
    {'headline_only': 1}, {'verified_tickers_json': '["OTHER"]'},
    {'source_facts_json': '{"title":"earnings tomorrow"}'},
    {'source_facts_json': 'broken'}, {'ticker': 'OTHER'},
])
def test_schedule_headline_acceptance_or_wrong_identity_is_not_a_release(change):
    assert inputs.verified_earnings_from_rows([dict(typed_row(), **change)], ['TEST'], DECISION) == {}


def test_processing_after_decision_does_not_backfill_earlier_decision():
    row = typed_row()
    row['analyzed_at'] = (DECISION + timedelta(seconds=1)).isoformat()
    assert inputs.verified_earnings_from_rows([row], ['TEST'], DECISION) == {}


def test_unverified_correction_is_preserved_not_silently_discarded():
    row = typed_row()
    fact = json.loads(row['source_facts_json'])['earnings_events'][0]
    fact.update(verified=False, retracted=True)
    row['source_facts_json'] = json.dumps({'earnings_events': [fact]})
    projected = inputs.verified_earnings_from_rows([row], ['TEST'], DECISION)['TEST'][0]
    assert projected['verified'] is False and projected['retracted'] is True


def test_long_history_cache_separate_from_baseline_and_has_actual_observation(monkeypatch, tmp_path):
    frame, _, _, _ = fixture_case('VCP_BASE_CONTRACTION')
    monkeypatch.setattr(scanner, 'ROOT', tmp_path)
    monkeypatch.setattr(scanner, '_read_history_cache', Mock(return_value=({}, 0)))
    download = Mock(return_value={'TEST': frame})
    writer = Mock()
    monkeypatch.setattr(scanner, '_download_history', download)
    monkeypatch.setattr(scanner, '_write_history_cache', writer)
    result, coverage = inputs.load_long_histories(['TEST'], {'history_cache_ttl': 1800}, decision_at=DECISION)
    download.assert_called_once_with(['TEST'], period='2y')
    assert writer.call_args.kwargs['cache_path'] == tmp_path / '.runtime' / 'entry-strategy-history.json.gz'
    assert result['TEST'].attrs['history_fetched_at'] > DECISION.timestamp()
    assert coverage['status'] == 'ready'


def test_each_enabled_route_has_same_discovery_frame_independent_of_vcp_flag(monkeypatch):
    frame, _, _, _ = fixture_case('VCP_BASE_CONTRACTION')
    loader = Mock(return_value=({'TEST': frame}, {'status': 'ready'}))
    monkeypatch.setattr(inputs, 'load_long_histories', loader)
    for ids in (['STOCKBEE_MOMENTUM_BURST'], ['VCP_BASE_CONTRACTION', 'STOCKBEE_MOMENTUM_BURST']):
        context = inputs.load_context(['TEST'], {}, {}, {'entry_strategy_ids': ids})
        assert context['by_ticker']['TEST']['history_frame'] is frame
    assert loader.call_count == 2


def test_failed_long_source_never_reseeds_discovery_with_baseline_frame(monkeypatch):
    monkeypatch.setattr(inputs, 'load_long_histories', Mock(return_value=({}, {'status': 'degraded'})))
    baseline, _, _, _ = fixture_case('STOCKBEE_MOMENTUM_BURST')
    context = inputs.load_context(['TEST'], {'TEST': baseline}, {},
        {'entry_strategy_ids': ['STOCKBEE_MOMENTUM_BURST']})
    assert context['by_ticker']['TEST']['history_frame'] is None


def detected_package(strategy_id='PEAD'):
    frame, context, _, _ = fixture_case(strategy_id)
    result = strategies.detect_all(frame, decision_at=DECISION, source_observed_at=OBSERVED,
        enabled_ids=[strategy_id], context=context)[strategy_id]
    assert result['state'] == 'DETECTED'
    return discovery.attribution([result], DECISION)


@pytest.mark.parametrize('field', ['source_observed_at', 'effective_available_at', 'source_data_at'])
def test_attribution_rejects_future_input_clock(field):
    package = detected_package()
    package['detections'][0]['source_times'][field] = (DECISION + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='discovery_invalid_attribution'):
        discovery.validate_attribution(package)


def test_review_projection_preserves_facts_without_redundant_configuration():
    package = detected_package()
    before = copy.deepcopy(package)
    projected = discovery.review_projection(package)
    assert projected['detections'][0]['features'] == package['detections'][0]['features']
    assert projected['detections'][0]['trigger'] == package['detections'][0]['trigger']
    assert 'config' not in projected['detections'][0]
    assert package == before


def test_creation_kill_switch_does_not_use_a_disabled_route_trigger():
    package = detected_package()
    level = package['detections'][0]['trigger']['level']
    candidate = {'entry_discovery': package}
    with pytest.raises(ValueError, match='no_detection'):
        discovery.validate_candidate_trigger(candidate, level*1.001, DECISION, DECISION, allowed_ids=[])
    assert discovery.validate_candidate_trigger(candidate, level*1.001, DECISION, DECISION,
        allowed_ids=['PEAD']) == package
