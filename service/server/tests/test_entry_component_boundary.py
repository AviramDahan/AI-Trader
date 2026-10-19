"""Retrospective component calculations must never become executable evidence."""
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import entry_discovery as discovery
import entry_strategy_execution as execution
import scanner_engine as engine
import stock_scanner as scanner
from test_entry_strategies import fixture_case, DECISION, OBSERVED


CALCULATION = datetime(2026, 10, 5, 21, tzinfo=timezone.utc)


def compose(monkeypatch, *, component=True, source_clock=True):
    frame, context, _, _ = fixture_case('RELATIVE_STRENGTH_LEADER')
    frame.attrs['history_fetched_at'] = OBSERVED.timestamp()
    baseline = dict(ticker='TEST', technical_direction='BUY', technical_score=6, entry=102,
        price_as_of='2026-10-05T20:00:00+00:00', average_dollar_volume=100000000,
        baseline_buy_score=6)
    if source_clock:
        baseline['history_fetched_at'] = OBSERVED.timestamp()
    calls = []
    def analyzer(*args, **kwargs):
        calls.append(kwargs['decision_at'])
        return copy.deepcopy(baseline)
    monkeypatch.setattr(scanner, 'analyze_history', analyzer)
    rows, observations = discovery.discover_candidates({'TEST': frame}, {'TEST': {}},
        {'entry_strategy_ids': ['RELATIVE_STRENGTH_LEADER']}, decision_at=DECISION,
        context=context, calculation_at=CALCULATION if component else None)
    return rows, observations, calls


def test_distinct_historical_calculation_preserves_actual_observed_clocks(monkeypatch):
    rows, _, calls = compose(monkeypatch)
    package = rows[0]['entry_discovery']
    assert package['version'] == discovery.COMPONENT_VERSION
    assert package['calculation_at'] == CALCULATION.isoformat()
    assert package['detected_at'] == DECISION.isoformat()
    assert calls == [CALCULATION, CALCULATION]
    for record in package['detections']:
        assert discovery.instant(record['source_times']['source_observed_at']) == OBSERVED
        assert discovery.instant(record['source_times']['decision_at']) == DECISION
    assert discovery.validate_attribution(package, allow_component=True) == package
    assert discovery.rank_candidates(rows) == rows


def test_component_cannot_enter_ai_signal_execution_or_backup(monkeypatch):
    rows, _, _ = compose(monkeypatch)
    package = rows[0]['entry_discovery']
    for call in (lambda: discovery.validate_attribution(package),
                 lambda: discovery.review_projection(package),
                 lambda: execution.build(package, created_at=DECISION, valid_until=DECISION+timedelta(days=1),
                     limit_price=102, quote_at=DECISION),
                 lambda: engine.record_signal({'action': 'BUY'}, rows[0], {}, {}, 'non_executable_component')):
        with pytest.raises(ValueError, match='discovery_invalid_attribution'):
            call()


def test_component_future_calculation_and_true_future_source_rejected(monkeypatch):
    rows, _, _ = compose(monkeypatch)
    package = copy.deepcopy(rows[0]['entry_discovery'])
    package['calculation_at'] = (DECISION+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='invalid_attribution'):
        discovery.validate_attribution(package, allow_component=True)
    package = copy.deepcopy(rows[0]['entry_discovery'])
    package['detections'][0]['source_times']['source_observed_at'] = (DECISION+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='invalid_attribution'):
        discovery.validate_attribution(package, allow_component=True)


def test_normal_current_discovery_does_not_use_component_version(monkeypatch):
    rows, _, calls = compose(monkeypatch, component=False)
    assert rows[0]['entry_discovery']['version'] == discovery.VERSION
    assert 'calculation_at' not in rows[0]['entry_discovery']
    assert calls == [DECISION, DECISION]


def test_component_missing_source_clock_never_returns_executable_unattributed_baseline(monkeypatch):
    frame, _, _, _ = fixture_case('RELATIVE_STRENGTH_LEADER')
    monkeypatch.setattr(scanner, 'analyze_history', Mock(return_value=dict(ticker='TEST',
        technical_direction='BUY', technical_score=6, baseline_buy_score=6)))
    rows, observations = discovery.discover_candidates({'TEST': frame}, {'TEST': {}},
        {'entry_strategy_ids': []}, decision_at=DECISION, calculation_at=CALCULATION)
    assert rows == []
    assert 'component_source_clock_unavailable' in observations[0]['common_reasons']
