"""Independent VCP selection and existing paper lifecycle; isolated DB/IO only."""
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
import database
import scanner_engine as engine
import stock_scanner as scanner
import vcp_breakout as vcp
from test_signal_admission_chain import prepare, rows
from test_signal_inputs import clock, db
from test_single_target_v2 import zone

FLAG = 'STOCK_SCANNER_VCP_BREAKOUT_POC_ENABLED'
DECISION = datetime(2026, 10, 6, 14, 0, 37, tzinfo=timezone.utc)
OBSERVED = datetime(2026, 10, 5, 20, 10, tzinfo=timezone.utc)
ACTUAL_AI_REVIEW = scanner.ai_review
ACTUAL_ANALYZER = scanner.analyze_history


def confirmed_history():
    """Three explicit contractions followed by a separate completed trigger.

    This invented path is a calculation fixture, never historical performance.
    The final ten base volumes are 200k; the previous forty are 1m. Thus the
    prior-fifty reference is 840k, independently of the trigger's volume.
    """
    tail = np.interp(np.arange(120), [0, 20, 40, 55, 70, 82, 104, 119],
                     [100, 80, 99, 90, 99.2, 95, 99.2, 99.2])
    close = np.r_[np.linspace(70, 90, 132), tail]
    scale = 100 / 102.4
    dates = [stamp for stamp in pd.bdate_range(end='2026-10-02', periods=300)
             if engine.market_session_state(stamp.to_pydatetime().replace(
                 hour=12, tzinfo=engine.ET))['is_trading_day']][-252:]
    frame = pd.DataFrame({
        'Open': close * scale, 'High': (close + .65) * scale,
        'Low': (close - .65) * scale, 'Close': close * scale,
        'Volume': [1_000_000] * 242 + [200_000] * 10,
    }, index=pd.DatetimeIndex(dates))
    frame.loc[pd.Timestamp('2026-10-05')] = [
        99.2 * scale, 102.2 * scale, 99.1 * scale, 102 * scale, 2_000_000]
    frame.attrs['history_fetched_at'] = OBSERVED.timestamp()
    return frame


def prepare_vcp(monkeypatch, clock):
    candidate, review, session = prepare(monkeypatch, clock)
    clock.instant = DECISION
    for key in ('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED',
                'STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED',
                'STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED', FLAG):
        monkeypatch.setenv(key, 'true')
    monkeypatch.setenv('STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED', 'true')
    candidate['price_zones'] = [zone(98, 98.4)]
    candidate['recent_high_20d'] = float(confirmed_history()['High'].tail(20).max())
    candidate['vcp_breakout'] = vcp.evaluate(
        confirmed_history(), decision_at=DECISION, expected_session='2026-10-05')
    engine.initialize_runtime()
    return candidate, review, session


def test_vcp_selection_preserves_contract_fullbar_exit_restart_and_cooldown(db, clock, monkeypatch):
    _, review, session = prepare_vcp(monkeypatch, clock)
    frame = confirmed_history()
    candidate = ACTUAL_ANALYZER('TEST', 'Synthetic Corporation', frame, scanner.settings())
    assert candidate is not None and candidate['vcp_breakout']['state'] == 'CONFIRMED'
    # Keep the actual analyzer and all four calculators in the positive chain.
    # Only the historical provider, news, quote, AI and projection IO are mocked.
    monkeypatch.setattr(scanner, 'analyze_history', ACTUAL_ANALYZER)
    monkeypatch.setattr(scanner, 'load_historical_data', lambda *_: ({'TEST': frame}, {'status': 'synthetic'}))
    monkeypatch.setenv(FLAG, 'false')
    baseline = scanner._candidate_target_plan(candidate, 'BUY', 100, scanner.settings(),
                                              quote_at=DECISION.isoformat())
    monkeypatch.setenv(FLAG, 'true')
    selected = scanner._candidate_target_plan(candidate, 'BUY', 100, scanner.settings(),
                                              quote_at=DECISION.isoformat())
    assert selected == baseline
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    result = scanner.run_scan()
    assert result['signals_published'] == review.call_count == 1
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    assert not rows('SELECT id FROM scanner_trades') and not rows('SELECT id FROM scanner_fills')
    order = rows('SELECT * FROM scanner_orders')[0]
    contract = json.loads(order['plan_json'])
    assert contract['target_plan'] == baseline
    assert 'vcp_breakout' not in contract
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    technical = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
    assert technical['vcp_breakout']['state'] == 'CONFIRMED'

    # Switching selection OFF must not change the already frozen execution.
    monkeypatch.setenv(FLAG, 'false')
    monkeypatch.setenv('STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED', 'false')
    monkeypatch.setenv('STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED', 'false')
    monkeypatch.setenv('STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED', 'false')
    premature = dict(at='2026-10-06T14:00:00Z', open=100, high=101, low=99.8, close=100)
    entry = dict(at='2026-10-06T14:05:00Z', open=100, high=101, low=99.8, close=100)
    clock.instant = datetime(2026, 10, 6, 14, 7, tzinfo=timezone.utc)
    engine.process_bar('TEST', premature)
    engine.process_bar('TEST', entry)  # Incomplete full bar cannot execute.
    assert not rows('SELECT id FROM scanner_fills')
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', entry)
    engine.initialize_runtime()
    engine.process_bar('TEST', entry)
    assert rows('SELECT status,filled_quantity,quantity FROM scanner_orders') == [
        {'status': 'filled', 'filled_quantity': order['quantity'], 'quantity': order['quantity']}]
    assert len(rows('SELECT id FROM scanner_fills')) == 1
    assert len(rows('SELECT id FROM scanner_trades')) == 1
    target = baseline['active_target']
    clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
    exit_bar = dict(at='2026-10-06T14:10:00Z', open=target, high=target+.2,
                    low=target-.2, close=target)
    engine.process_bar('TEST', exit_bar)
    after = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    engine.initialize_runtime()
    for bar in (premature, entry, exit_bar):
        engine.process_bar('TEST', bar)
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == after
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [
        {'status': 'closed', 'remaining_quantity': 0}]
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    scanner.run_scan()
    assert review.call_count == 1 and len(rows('SELECT id FROM scanner_orders')) == 1
    assert len({row['dedupe_key'] for row in rows('SELECT dedupe_key FROM scanner_telegram_outbox')}) == len(
        rows('SELECT id FROM scanner_telegram_outbox'))
    assert all(call.args[0] == 'POST' and call.args[1].endswith('/signals/strategy')
               for call in session.request.call_args_list)


@pytest.mark.parametrize('block', ['hold', 'confidence', 'relevance', 'sentiment', 'quote',
                                  'session', 'resistance', 'cash', 'exposure', 'unknown_vcp'])
def test_confirmed_vcp_does_not_bypass_existing_admission(db, clock, monkeypatch, block):
    candidate, review, _ = prepare_vcp(monkeypatch, clock)
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    if block == 'hold':
        review.return_value['action'] = 'HOLD'
    if block == 'confidence':
        review.return_value['confidence'] = .79
    if block == 'relevance':
        review.return_value['news_relevance'] = .59
    if block == 'sentiment':
        review.return_value['news_sentiment'] = -.11
    if block == 'quote':
        monkeypatch.setattr(scanner, 'current_intraday_quote', lambda *_: None)
    if block == 'session':
        monkeypatch.setattr(scanner, 'regular_session_open', lambda: False)
    if block == 'resistance':
        candidate['price_zones'].append(zone(102, 103))
    if block == 'cash':
        with database.get_db_connection() as conn:
            conn.execute('UPDATE scanner_accounts SET cash=0')
        before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    if block == 'exposure':
        monkeypatch.setenv('STOCK_SCANNER_MAX_TOTAL_EXPOSURE', '100')
        monkeypatch.setenv('STOCK_SCANNER_PAPER_NOTIONAL', '200')
    if block == 'unknown_vcp':
        candidate['vcp_breakout'] = vcp.evaluate(confirmed_history().tail(120),
            decision_at=DECISION, expected_session='2026-10-05')
    scanner.run_scan()
    assert not rows('SELECT id FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    if block in {'quote', 'session', 'resistance', 'unknown_vcp'}:
        review.assert_not_called()


def test_vcp_gate_is_only_after_successful_no_forward_zone_fallback(db, clock, monkeypatch):
    candidate, _, _ = prepare_vcp(monkeypatch, clock)
    poison = Mock(side_effect=AssertionError('VCP must not replace original structural authority'))
    monkeypatch.setattr(vcp, 'validate_trigger', poison)
    candidate['price_zones'].append(zone(104.65, 105))
    assert scanner._candidate_target_plan(candidate, 'BUY', 100, scanner.settings())['policy_version'] == 'single_target_v2'
    candidate['price_zones'] = [zone(98, 98.4), zone(102, 103)]
    with pytest.raises(ValueError):
        scanner._candidate_target_plan(candidate, 'BUY', 100, scanner.settings())
    candidate['price_zones'] = []
    with pytest.raises(ValueError):
        scanner._candidate_target_plan(candidate, 'BUY', 100, scanner.settings())
    poison.assert_not_called()


def test_confirmed_vcp_selection_never_changes_recovery_holds(db, clock, monkeypatch):
    _, _, _ = prepare_vcp(monkeypatch, clock)
    scanner.run_scan()
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
    engine._pending_recovery_check('TEST', [], clock.instant)
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'recovery_uncertain'}]
    monkeypatch.setenv(FLAG, 'false')
    engine.initialize_runtime()
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=100, high=101, low=99.8, close=100))
    assert not rows('SELECT id FROM scanner_fills')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


def test_completed_point_in_time_result_ignores_future_suffix_and_preserves_input():
    frame = confirmed_history()
    before = frame.copy(deep=True)
    expected = vcp.evaluate(frame, decision_at=DECISION, expected_session='2026-10-05')
    assert expected['state'] == 'CONFIRMED'
    future = frame.copy(deep=True)
    future.loc[pd.Timestamp('2026-10-06')] = [1, 1_000_000, .01, 999_999, 1_000_000_000]
    future.loc[pd.Timestamp('2026-10-07')] = [500, 1_000_000, .01, 500, 1_000_000_000]
    assert vcp.evaluate(future, decision_at=DECISION, expected_session='2026-10-05') == expected
    pd.testing.assert_frame_equal(frame, before)
    assert frame.attrs == before.attrs


def test_selection_evidence_does_not_change_actual_ai_input(db, clock, monkeypatch):
    candidate, _, _ = prepare_vcp(monkeypatch, clock)
    transport = Mock(return_value={'action': 'HOLD'})
    monkeypatch.setattr(scanner.final_ai, 'review', transport)
    ACTUAL_AI_REVIEW(candidate, [], {})
    with_evidence = copy.deepcopy(transport.call_args.args[0])
    candidate.pop('vcp_breakout')
    ACTUAL_AI_REVIEW(candidate, [], {})
    assert transport.call_args.args[0] == with_evidence
    assert 'vcp_breakout' not in json.loads(with_evidence[1]['content'])['candidate']


def test_completed_volume_and_pivot_are_independent_of_trigger_volume():
    frame = confirmed_history()
    observed = vcp.evaluate(frame, decision_at=DECISION, expected_session='2026-10-05')
    features = observed['features']
    assert features['avg_prior_volume_50'] == 840_000
    assert features['avg_prior_volume_10'] == 200_000
    assert features['dry_up_ratio'] == pytest.approx(200_000 / 840_000)
    assert features['trigger_volume_ratio'] == pytest.approx(2_000_000 / 840_000)
    assert features['pivot_price'] == pytest.approx(99.85 * 100 / 102.4)
    assert features['sma200'] == pytest.approx(frame['Close'].iloc[-201:-1].mean())
    increased = frame.copy(deep=True)
    increased.loc[increased.index[-1], 'Volume'] = 100_000_000
    after = vcp.evaluate(increased, decision_at=DECISION, expected_session='2026-10-05')['features']
    for key in ('pivot_price', 'dry_up_ratio', 'avg_prior_volume_50', 'avg_prior_volume_10',
                'sma50', 'sma200', 'contraction_depths_pct'):
        assert after[key] == features[key]


def test_nontrading_day_row_cannot_count_as_a_completed_daily_session():
    frame = confirmed_history()
    frame.loc[pd.Timestamp('2026-10-03')] = [100, 101, 99, 100, 1_000_000]
    frame = frame.sort_index()
    observed = vcp.evaluate(frame, decision_at=DECISION, expected_session='2026-10-05')
    assert observed['state'] == 'UNKNOWN'
    assert observed['reasons'] == ['vcp_invalid_data']


def test_actual_analyzer_default_off_parity_and_on_completed_evidence(clock, monkeypatch):
    clock.instant = DECISION
    frame = confirmed_history()
    monkeypatch.delenv(FLAG, raising=False)
    baseline = scanner.analyze_history('TEST', 'Synthetic Corporation', frame, scanner.settings())
    assert baseline is not None and baseline['technical_direction'] == 'BUY'
    assert 'vcp_breakout' not in baseline
    monkeypatch.setenv(FLAG, 'false')
    assert scanner.analyze_history('TEST', 'Synthetic Corporation', frame, scanner.settings()) == baseline
    monkeypatch.setenv(FLAG, 'true')
    observed = scanner.analyze_history('TEST', 'Synthetic Corporation', frame, scanner.settings())
    assert observed['vcp_breakout']['state'] == 'CONFIRMED'
    evidence = observed.pop('vcp_breakout')
    assert observed == baseline
    assert evidence['source_data_at'] == '2026-10-05T20:05:00+00:00'
    assert evidence['source_observed_at'] == OBSERVED.isoformat()
    assert evidence['features']['pivot_price'] == pytest.approx(99.85 * 100 / 102.4)
