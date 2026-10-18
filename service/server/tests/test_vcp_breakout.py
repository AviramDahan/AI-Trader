"""Actual pure donor calculations with controlled as-of data; no provider IO."""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vcp_breakout as vcp

DECISION = '2026-10-06T14:00:37Z'
OBSERVED = '2026-10-06T13:59:00Z'


def history():
    """A fixed synthetic3-contraction prior base, then a separate trigger bar."""
    prior = np.concatenate([np.linspace(70, 90, 132), np.interp(np.arange(120),
        [0, 20, 40, 55, 70, 82, 104, 119], [100, 80, 99, 90, 99.2, 95, 99.2, 99.2])])
    scale = 100 / 100.9
    from scanner_engine import market_session_state
    sessions = [d for d in pd.bdate_range(end='2026-10-02', periods=400)
                if market_session_state(d.to_pydatetime().replace(hour=12, tzinfo=vcp.ET))['is_trading_day']][-252:]
    frame = pd.DataFrame(dict(Open=prior, High=prior + .2, Low=prior - .2,
        Close=prior, Volume=[1_000_000] * 242 + [200_000] * 10),
        index=sessions)
    frame.loc[pd.Timestamp('2026-10-05')] = [99.2, 100.6, 99.1, 100.4, 2_000_000]
    frame[['Open', 'High', 'Low', 'Close']] *= scale
    frame.attrs['history_fetched_at'] = datetime.fromisoformat(OBSERVED.replace('Z', '+00:00')).timestamp()
    return frame


def evidence(frame=None, **kwargs):
    return vcp.evaluate(history() if frame is None else frame, decision_at=DECISION, **kwargs)


def freeze_scanner(monkeypatch):
    import stock_scanner as scanner
    class Frozen(datetime):
        @staticmethod
        def now(tz=None):
            return datetime.fromisoformat(DECISION.replace('Z', '+00:00')).astimezone(tz or timezone.utc)
    monkeypatch.setattr(scanner, 'datetime', Frozen)
    monkeypatch.setattr('scanner_engine.lifecycle_settings', lambda: {'active_strategy': 'single'})
    for flag in ('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED', 'STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED',
                 'STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED'):
        monkeypatch.setenv(flag, 'true')
    return scanner


def candidate():
    from test_single_target_v2 import zone
    return dict(ticker='TEST', company='Synthetic', technical_direction='BUY', entry=100., atr=1.,
        technical_score=7, average_dollar_volume=1e9, price_as_of='2026-10-05',
        price_zones=[zone(98, 98.4)], recent_high_20d=99.8,
        vcp_breakout=evidence())


def test_real_four_calculators_prior_base_volume_pivot_and_current_trigger():
    result = evidence()
    assert result['state'] == 'CONFIRMED', result
    features = result['features']
    assert features['num_contractions'] == 3 and features['pattern_valid']
    assert features['avg_prior_volume_50'] == 840_000
    assert features['avg_prior_volume_10'] == 200_000
    assert features['dry_up_ratio'] == pytest.approx(200_000 / 840_000)
    assert features['trigger_volume_ratio'] == pytest.approx(2_000_000 / 840_000)
    assert features['pivot_price'] == pytest.approx(99.4 * (100 / 100.9))
    assert features['pivot_price'] != round(features['pivot_price'], 2)
    assert result['pivot_confirmed_at'] < result['source_data_at'] <= result['effective_available_at'] <= result['decision_at']
    accepted = vcp.validate_trigger(result, 100., '2026-10-06T14:00:00Z', DECISION)
    assert accepted['state'] == 'CONFIRMED' and accepted['entry_price'] == 100.
    assert 'stop_loss_price' not in json.dumps(accepted)
    assert len(json.dumps(accepted).encode()) < 4096


def test_trigger_price_and_volume_never_redefine_prior_pivot_or_dry_up():
    frame = history()
    first = evidence(frame)
    frame.iloc[-1, frame.columns.get_loc('Volume')] = 20_000_000
    second = evidence(frame)
    for key in ('pivot_price', 'last_contraction_low', 'num_contractions', 'pattern_score',
                'dry_up_ratio', 'avg_prior_volume_50', 'avg_prior_volume_10'):
        assert first['features'][key] == second['features'][key]
    assert first['features']['trigger_volume_ratio'] != second['features']['trigger_volume_ratio']


def test_future_unfinished_rows_and_poison_do_not_change_completed_features():
    frame = history()
    expected = evidence(frame)
    frame.loc[pd.Timestamp('2026-10-06')] = [float('nan'), 1e12, .01, 1e12, 1e12]
    frame.loc[pd.Timestamp('2026-10-07')] = [float('nan'), 1e15, .01, 1e15, 1e15]
    actual = evidence(frame)
    assert actual == expected


def test_short_history_is_unknown_not_forming_or_positive():
    result = evidence(history().tail(252))
    assert result['state'] == 'UNKNOWN' and result['reasons'] == ['vcp_insufficient_history']
    with pytest.raises(ValueError, match='^vcp_insufficient_history$'):
        vcp.validate_trigger(result, 100., '2026-10-06T14:00:00Z', DECISION)


def test_missing_and_future_availability_are_unknown():
    frame = history()
    frame.attrs.clear()
    assert evidence(frame)['reasons'] == ['vcp_availability_unknown']
    assert evidence(frame, source_observed_at='2026-10-07T14:00:00Z')['reasons'] == ['vcp_future_availability']
    assert evidence(expected_session='2026-10-02')['reasons'] == ['vcp_history_not_current']


def test_nontrading_source_row_cannot_count_toward_warmup_or_volume():
    frame = history()
    frame.loc[pd.Timestamp('2026-10-03')] = [100., 101., 99., 100., 1_000_000]
    assert evidence(frame.sort_index())['reasons'] == ['vcp_invalid_data']


def test_unavailable_past_nontrading_poison_is_ignored_before_validation():
    frame = history()
    frame['available_at'] = [vcp._market_available(i.date()).isoformat() for i in frame.index]
    expected = evidence(frame)
    frame.loc[pd.Timestamp('2026-10-03')] = [float('nan'), 1., 4., -1., -1., '2026-10-07T12:00:00Z']
    assert evidence(frame.sort_index()) == expected


def test_unconfirmed_delayed_pivot_input_cannot_become_a_prior_trigger():
    frame = history()
    frame['available_at'] = [vcp._market_available(i.date()).isoformat() for i in frame.index]
    frame.iloc[-5, frame.columns.get_loc('available_at')] = '2026-10-06T12:00:00Z'
    assert evidence(frame)['reasons'] == ['vcp_pivot_unconfirmed']


def test_quote_before_download_completion_can_still_be_available_by_decision():
    result = vcp.evaluate(history(), decision_at='2026-10-06T14:00:05Z',
                          source_observed_at='2026-10-06T14:00:02Z')
    assert vcp.validate_trigger(result, 100., '2026-10-06T14:00:00Z',
                               '2026-10-06T14:00:05Z')['state'] == 'CONFIRMED'


@pytest.mark.parametrize('price,at,reason', [(110., '2026-10-06T14:00:00Z', 'vcp_overextended'),
    (98., '2026-10-06T14:00:00Z', 'vcp_trigger_not_confirmed'),
    (100., '2026-10-06T13:48:00Z', 'vcp_quote_not_fresh'),
    (100., '2026-10-06T14:00:38Z', 'vcp_quote_not_fresh'),
    (100., None, 'vcp_evidence_invalid')])
def test_actual_quote_rechecks_exact_safe_failure(price, at, reason):
    with pytest.raises(ValueError, match='^'+reason+'$'):
        vcp.validate_trigger(evidence(), price, at, DECISION)


def test_no_pattern_and_missing_pivot_are_never_buy_ready():
    frame = history()
    for key in ('Open', 'Close'):
        frame[key] = 100.
    frame['High'], frame['Low'] = 100.2, 99.8
    assert evidence(frame)['state'] != 'CONFIRMED'


@pytest.mark.parametrize('kind', ['nested_text', 'nonfinite', 'wrong_pin', 'unknown_reason', 'huge'])
def test_audit_projection_never_retains_unallowlisted_nested_data(kind):
    value = evidence()
    if kind == 'nested_text': value['features']['prompt'] = 'untrusted secret text'
    if kind == 'nonfinite': value['features']['dry_up_ratio'] = float('nan')
    if kind == 'wrong_pin': value['source_pin'] = 'unreviewed'
    if kind == 'unknown_reason': value['reasons'] = ['raw error with URL']
    if kind == 'huge': value['coverage']['raw'] = 'x' * 5000
    assert vcp.public_evidence(value) is None


def test_default_off_does_not_calculate_or_decorate_candidates(monkeypatch):
    scanner = freeze_scanner(monkeypatch)
    monkeypatch.delenv('STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED', raising=False)
    calculate = Mock(side_effect=AssertionError('OFF must not calculate'))
    monkeypatch.setattr(vcp, 'evaluate', calculate)
    cfg = dict(min_dollar_volume=1, min_atr_pct=0, max_atr_pct=100, min_technical_score=3)
    row = scanner.analyze_history('TEST', 'Synthetic', history(), cfg)
    assert row and row['technical_direction'] == 'BUY' and 'vcp_breakout' not in row
    calculate.assert_not_called()


def test_default_on_only_decorates_technical_buy(monkeypatch):
    scanner = freeze_scanner(monkeypatch)
    monkeypatch.setenv('STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED', 'true')
    cfg = dict(min_dollar_volume=1, min_atr_pct=0, max_atr_pct=100, min_technical_score=3)
    row = scanner.analyze_history('TEST', 'Synthetic', history(), cfg)
    assert row['vcp_breakout']['state'] == 'CONFIRMED'


def test_only_valid_no_forward_breakout_is_narrowed_and_plan_unchanged(monkeypatch):
    scanner = freeze_scanner(monkeypatch)
    c = candidate()
    cfg = dict(min_risk_reward=2)
    monkeypatch.setenv('STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED', 'false')
    baseline = scanner._candidate_target_plan(c, 'BUY', 100., cfg, quote_at='2026-10-06T14:00:00Z')
    monkeypatch.setenv('STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED', 'true')
    enhanced = scanner._candidate_target_plan(c, 'BUY', 100., cfg, quote_at='2026-10-06T14:00:00Z')
    assert enhanced == baseline and enhanced['policy_version'] == 'single_breakout_v1'
    c['vcp_breakout'] = evidence(history().tail(100))
    with pytest.raises(ValueError, match='^vcp_insufficient_history$'):
        scanner._candidate_target_plan(c, 'BUY', 100., cfg, quote_at='2026-10-06T14:00:00Z')
    from test_single_target_v2 import zone
    c['price_zones'].append(zone(102, 103))
    with pytest.raises(ValueError, match='^nearest_resistance_below_2r$'):
        scanner._candidate_target_plan(c, 'BUY', 100., cfg, quote_at='2026-10-06T14:00:00Z')
    c['price_zones'][-1] = zone(104.65, 105.)
    accepted = scanner._candidate_target_plan(c, 'BUY', 100., cfg, quote_at='2026-10-06T14:00:00Z')
    assert accepted['policy_version'] == 'single_target_v2'


def test_immutable_per_check_audit_survives_candidate_mutation_and_off_omits(monkeypatch):
    import target_evidence
    import final_ai
    c = candidate()
    trace = final_ai.new_trace('synthetic', 'TEST', 1)
    token = final_ai.TRACE.set(trace)
    monkeypatch.setenv('STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED', 'true')
    source = dict(atr=1., zones=c['price_zones'], data_as_of='2026-10-05')
    try:
        target_evidence.capture(c, 'BUY', 100., '2026-10-06T14:00:00Z', 'pre_ai',
            'single_breakout_v1', 'single', source, {'min_risk_reward': 2},
            decided_at=DECISION, rejection='vcp_insufficient_history')
        saved = copy.deepcopy(trace['target_checks']['pre_ai']['vcp_breakout'])
        c['vcp_breakout']['features']['pivot_price'] = 1.
        assert trace['target_checks']['pre_ai']['vcp_breakout'] == saved
        monkeypatch.setenv('STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED', 'false')
        target_evidence.capture(c, 'BUY', 100., '2026-10-06T14:00:00Z', 'post_ai',
            'single_breakout_v1', 'single', source, {'min_risk_reward': 2}, decided_at=DECISION)
        assert 'vcp_breakout' not in trace['target_checks']['post_ai']
    finally:
        final_ai.TRACE.reset(token)
