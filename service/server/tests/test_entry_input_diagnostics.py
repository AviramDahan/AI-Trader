from datetime import datetime, timezone
import json
import pytest

from entry_input_diagnostics import history_failure_metadata

NOW = datetime(2026, 10, 20, 14, tzinfo=timezone.utc)


def row(**values):
    return dict(date='2026-10-19', available_at='2026-10-19T20:05:00+00:00',
        open=10., high=11., low=9., close=10., volume=100., **values)


def capture(rows):
    return history_failure_metadata(rows, decision_at=NOW, source_observed_at=NOW, predicate='invalid_ohlcv')


def test_causal_fingerprint_is_stable_nonfinite_json_without_raw_values():
    item = row(); item['close'] = float('nan')
    evidence = capture([item])
    assert evidence == capture([item])
    assert evidence['consumed_rows'] == 1
    assert evidence['first_offending_session'] == '2026-10-19'
    assert evidence['reconstructible'] is False
    assert 'NaN' not in json.dumps(evidence, allow_nan=False)
    assert 'volume' not in evidence and 'close' not in evidence
    other = row(); other['close'] = float('inf')
    assert capture([other])['consumed_prefix_sha256'] != evidence['consumed_prefix_sha256']


def test_future_data_or_unbounded_input_cannot_be_diagnostic_evidence():
    item = row(); item['available_at'] = '2026-10-21T20:05:00+00:00'
    with pytest.raises(ValueError, match='future_row'): capture([item])
    with pytest.raises(ValueError, match='invalid_input'): capture([row()] * 1025)
    with pytest.raises(ValueError):
        history_failure_metadata([], decision_at=NOW, source_observed_at=NOW, predicate='raw secret exception')


def test_extra_attributes_are_not_exported_or_hashed():
    item = row(); item['secret'] = 'must not leave input'
    assert capture([item]) == capture([row()])
