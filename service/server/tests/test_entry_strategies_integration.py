"""Independent OR discovery/admission checks; only invented market evidence.

The shared fixture starts with each implementer's causal detector positive, then
adds independently confirmed chart anchors for the unchanged structural planner.
No state is forced to DETECTED and no target-plan builder is mocked.
"""
import copy
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import entry_discovery as discovery
import entry_strategies as strategies
import scanner_engine as engine
import stock_scanner as scanner
from test_entry_strategies import fixture_case, DECISION, OBSERVED
from test_signal_admission_chain import prepare, rows
from test_signal_inputs import clock, db

ACTUAL_ANALYZER = scanner.analyze_history
ACTUAL_AI_REVIEW = scanner.ai_review
IDS = strategies.STRATEGY_IDS


@pytest.fixture(autouse=True)
def no_external_entry_io(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Independent entry tests forbid external IO')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)


def route_case(strategy_id, *, executable_structure=False):
    frame, context, decision, observed = fixture_case(strategy_id)
    frame, context = frame.copy(deep=True), copy.deepcopy(context)
    context['symbol'] = 'TEST'
    for event in context.get('earnings_events', []):
        event['symbol'] = 'TEST'
    if executable_structure:
        # Keep global ATR eligibility. These are source candles, not invented
        # target-plan prices. The overhead pivot is outside VCP's120-bar base
        # but inside the original126-bar structural lookback and fully confirmed.
        frame['High'] += .65
        frame['Low'] -= .65
        frame['Volume'] *= 2
        frame.iloc[129, frame.columns.get_loc('High')] = 140
        if strategy_id == 'RELATIVE_STRENGTH_LEADER':
            frame.iloc[-6, frame.columns.get_loc('Low')] -= 1
        if strategy_id == 'TREND_PULLBACK_RECLAIM':
            # A shallow prior pullback, followed by reclaim above its old high;
            # the original fixture is correctly blocked by nearby resistance.
            close = [70 + (103-70)*i/241 for i in range(242)] + [
                103-(103-100.5)*i/9 for i in range(10)] + [104]
            frame.loc[:, 'Open'] = [value-.05 for value in close]
            frame.loc[:, 'High'] = [value+.85 for value in close]
            frame.loc[:, 'Low'] = [value-.85 for value in close]
            frame.loc[:, 'Close'] = close
            frame.iloc[129, frame.columns.get_loc('High')] = 140
            frame.iloc[-1] = [101, 104.2, 100.8, 104, 3_000_000]
    frame.attrs['history_fetched_at'] = observed.timestamp()
    return frame, context, decision, observed


def actual_detection(strategy_id, *, executable_structure=False):
    frame, context, decision, observed = route_case(strategy_id,
        executable_structure=executable_structure)
    result = strategies.detect_all(frame, decision_at=decision,
        source_observed_at=observed, enabled_ids=[strategy_id], context=context)[strategy_id]
    return result, frame, context


def missed_case(strategy_id):
    """Explicit synthetic disagreements with unchanged default baseline rules.

    Changes are candle fixtures, not a threshold sweep or strategy optimization.
    These discovery controls need not also pass structural order admission.
    """
    frame, context, decision, observed = route_case(strategy_id, executable_structure=True)
    if strategy_id == 'STOCKBEE_MOMENTUM_BURST':
        for index in range(232):
            close = 70 + 35*index/231
            frame.iloc[index, :4] = [close-.05, close+.85, close-.85, close]
        frame.iloc[129, frame.columns.get_loc('High')] = 140
        frame.iloc[-21, :4] = [101.5, 101.8, 101.2, 101.5]
        frame.iloc[-1] = [97, 103.7, 96.8, 103.5, 4_000_000]
    elif strategy_id == 'PEAD':
        frame.iloc[-21, :4] = [104.95, 105.85, 104.15, 105]
        frame.iloc[-10, frame.columns.get_loc('High')] = 115
    elif strategy_id == 'TREND_PULLBACK_RECLAIM':
        frame.iloc[-4, frame.columns.get_loc('High')] = 108
    elif strategy_id == 'RELATIVE_STRENGTH_LEADER':
        frame.iloc[-21:-1, :4] = [100, 100.85, 99.15, 100]
        frame.iloc[-1] = [100, 101.2, 99.9, 101, 4_000_000]
    return frame, context, decision, observed


@pytest.mark.parametrize('strategy_id', IDS)
def test_independent_executable_fixture_still_computes_actual_detection(strategy_id):
    record, _, _ = actual_detection(strategy_id, executable_structure=True)
    assert record['state'] == 'DETECTED', record


@pytest.mark.parametrize('strategy_id', IDS)
def test_each_actual_detector_is_composed_before_original_detector_none(strategy_id, monkeypatch):
    frame, context, decision, _ = route_case(strategy_id, executable_structure=True)
    order = []
    original = strategies.detect_all
    def detect(*args, **kwargs):
        order.append('new')
        return original(*args, **kwargs)
    def missed_baseline(*args):
        order.append('baseline-none')
        assert order[0] == 'new'
        return None
    monkeypatch.setattr(strategies, 'detect_all', detect)
    cfg = scanner.settings() | {'entry_strategy_ids': [strategy_id]}
    candidates, observations = discovery.discover_candidates({'TEST': frame},
        {'TEST': {'company': 'Synthetic Corporation', 'indexes': ['synthetic']}}, cfg,
        decision_at=decision, context=context, baseline_detector=missed_baseline)
    assert len(candidates) == 1, observations
    assert candidates[0]['strategy_ids'] == [strategy_id]
    assert observations[0]['baseline_detected'] is False
    assert observations[0]['candidate_strategy_ids'] == [strategy_id]
    assert order == ['new', 'baseline-none']
    assert candidates[0]['entry_discovery']['detections'][0]['source_pin'] == strategies.SOURCE_PIN


def test_source_pin_survives_actual_detection_attribution():
    record, _, _ = actual_detection('PEAD')
    assert record['state'] == 'DETECTED'
    package = discovery.attribution([record], DECISION)
    assert package['detections'][0]['source_pin'] == strategies.SOURCE_PIN
    assert package == discovery.validate_attribution(package)


@pytest.mark.parametrize('strategy_id', IDS)
def test_each_route_finds_a_default_baseline_actual_miss(strategy_id):
    frame, context, decision, observed = missed_case(strategy_id)
    cfg = scanner.settings() | {'entry_strategy_ids': [strategy_id]}
    cfg['min_technical_score'] = 5  # Existing documented default, not raised to force a miss.
    original = ACTUAL_ANALYZER('TEST', 'Synthetic', frame, cfg, decision_at=decision)
    assert original is None, original
    record = strategies.detect_all(frame, decision_at=decision, source_observed_at=observed,
        enabled_ids=[strategy_id], context=context)[strategy_id]
    assert record['state'] == 'DETECTED', record
    candidates, observations = discovery.discover_candidates({'TEST': frame},
        {'TEST': {'company': 'Synthetic'}}, cfg, decision_at=decision, context=context)
    assert len(candidates) == 1, observations
    assert candidates[0]['strategy_ids'] == [strategy_id]
    assert observations[0]['baseline_detected'] is False


def test_pead_latest_known_unverified_revision_cannot_revive_old_release():
    frame, context, decision, observed = route_case('PEAD')
    old = context['earnings_events'][0]
    newer = copy.deepcopy(old)
    known = datetime.fromisoformat(old['effective_available_at']) + timedelta(minutes=5)
    newer.update(verified=False, source_observed_at=known.isoformat(),
        processed_at=known.isoformat(), effective_available_at=known.isoformat())
    context['earnings_events'] = [old, newer]
    record = strategies.detect_all(frame, decision_at=decision,
        source_observed_at=observed, enabled_ids=['PEAD'], context=context)['PEAD']
    assert record['state'] == 'UNKNOWN', record


def test_default_off_does_not_invoke_new_detector(monkeypatch):
    for flag in discovery.FLAGS.values():
        monkeypatch.delenv(flag, raising=False)
    assert discovery.enabled_ids() == ()
    monkeypatch.setattr(strategies, 'detect_all', Mock(side_effect=AssertionError('OFF detector called')))
    frame, context, decision, _ = route_case('STOCKBEE_MOMENTUM_BURST', executable_structure=True)
    candidates, _ = discovery.discover_candidates({'TEST': frame}, {'TEST': {'company': 'Synthetic'}},
        scanner.settings() | {'entry_strategy_ids': []}, decision_at=decision,
        context=context, baseline_detector=lambda *args: None)
    assert candidates == []


def prepare_route(monkeypatch, clock, strategy_id, *, multi=False):
    _, review, session = prepare(monkeypatch, clock)
    clock.instant = DECISION
    frame, context, _, _ = route_case(strategy_id, executable_structure=True)
    if multi:
        # Both real routes require a strong close; preserve PEAD but do not
        # falsely call its original .685 close-location a Stockbee positive.
        frame.iloc[-1, frame.columns.get_loc('High')] = 106.4
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    monkeypatch.setenv(discovery.FLAGS[strategy_id], 'true')
    if multi:
        monkeypatch.setenv(discovery.FLAGS['STOCKBEE_MOMENTUM_BURST'], 'true')
    for flag in ('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED',
                 'STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED',
                 'STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED',
                 'STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED'):
        monkeypatch.setenv(flag, 'true')
    monkeypatch.setattr(scanner, 'load_historical_data',
        lambda *args, **kwargs: ({'TEST': frame}, {'status': 'synthetic-independent'}))
    # The old route misses; all common calculations remain the actual code.
    # A separate five-case test above proves actual default-baseline misses.
    def baseline_miss(*args, **kwargs):
        if kwargs.get('baseline_filter') is False:
            return ACTUAL_ANALYZER(*args, **kwargs)
        return None
    monkeypatch.setattr(scanner, 'analyze_history', baseline_miss)
    import entry_strategy_inputs
    context_io = Mock(return_value=context)
    monkeypatch.setattr(entry_strategy_inputs, 'load_context', context_io)
    quote = {'VCP_BASE_CONTRACTION': 101.3, 'STOCKBEE_MOMENTUM_BURST': 101,
             'PEAD': 106, 'TREND_PULLBACK_RECLAIM': 104,
             'RELATIVE_STRENGTH_LEADER': 102}[strategy_id]
    monkeypatch.setattr(scanner, 'current_intraday_quote', lambda *args: (quote, clock.instant.isoformat()))
    engine.initialize_runtime()
    return frame, context, quote, review, session, context_io


@pytest.mark.parametrize('strategy_id', IDS)
def test_each_real_discovery_signal_pending_fullbar_exit_restart(db, clock, monkeypatch, strategy_id):
    frame, context, quote, review, session, context_io = prepare_route(monkeypatch, clock, strategy_id)
    actual = strategies.detect_all(frame, decision_at=DECISION, source_observed_at=OBSERVED,
        enabled_ids=[strategy_id], context=context)[strategy_id]
    assert actual['state'] == 'DETECTED'
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    result = scanner.run_scan()
    assert result['signals_published'] == review.call_count == 1, result
    assert context_io.call_count == 1
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    assert not rows('SELECT id FROM scanner_trades') and not rows('SELECT id FROM scanner_fills')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    technical = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
    package = technical['entry_discovery']
    assert package['strategy_ids'] == [strategy_id]
    order = rows('SELECT * FROM scanner_orders')[0]
    contract = json.loads(order['plan_json'])
    assert contract['entry_discovery'] == package
    plan = contract['target_plan']
    assert plan['minimum_rr'] == 2 and plan['rr'][0] >= 2
    assert 'entry_discovery' not in plan
    frozen_contract = copy.deepcopy(contract)

    # Flags govern new creation, never execution or exits of saved contracts.
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    for flag in ('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED',
                 'STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED',
                 'STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED',
                 'STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED'):
        monkeypatch.setenv(flag, 'false')
    premature = dict(at='2026-10-06T14:00:00Z', open=quote, high=quote+.2, low=quote-.1, close=quote)
    entry = dict(at='2026-10-06T14:05:00Z', open=quote, high=quote+.2, low=quote-.1, close=quote)
    clock.instant = datetime(2026, 10, 6, 14, 7, tzinfo=timezone.utc)
    engine.process_bar('TEST', premature)
    engine.process_bar('TEST', entry)
    assert not rows('SELECT id FROM scanner_fills')
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', entry)
    engine.initialize_runtime()
    engine.process_bar('TEST', entry)
    assert len(rows('SELECT id FROM scanner_fills')) == 1
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'filled'}]
    assert len(rows('SELECT id FROM scanner_trades')) == 1
    assert json.loads(rows('SELECT settings_json FROM scanner_trades')[0]['settings_json'])['entry_discovery'] == package
    assert json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']) == frozen_contract

    target = plan['active_target']
    exit_bar = dict(at='2026-10-06T14:10:00Z', open=target, high=target+.2, low=target-.2, close=target)
    clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
    engine.process_bar('TEST', exit_bar)
    after = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    engine.initialize_runtime()
    for bar in (premature, entry, exit_bar):
        engine.process_bar('TEST', bar)
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == after
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [{'status': 'closed', 'remaining_quantity': 0}]
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    monkeypatch.setenv(discovery.FLAGS[strategy_id], 'true')
    scanner.run_scan()
    assert review.call_count == 1 and len(rows('SELECT id FROM scanner_orders')) == 1
    assert all(call.args[0] == 'POST' and call.args[1].endswith('/signals/strategy')
               for call in session.request.call_args_list)


def test_all_routes_are_or_and_unknown_pead_or_rs_do_not_veto_momentum():
    frame, context, decision, _ = route_case('STOCKBEE_MOMENTUM_BURST', executable_structure=True)
    candidates, observations = discovery.discover_candidates({'TEST': frame},
        {'TEST': {'company': 'Synthetic'}}, scanner.settings() | {'entry_strategy_ids': list(IDS)},
        decision_at=decision, context=context, baseline_detector=lambda *args: None)
    assert len(candidates) == 1
    assert 'STOCKBEE_MOMENTUM_BURST' in candidates[0]['strategy_ids']
    results = observations[0]['strategy_results']
    assert results['PEAD']['state'] == results['RELATIVE_STRENGTH_LEADER']['state'] == 'UNKNOWN'


def test_rank_fairness_deduplicates_without_increasing_shared_six_slots():
    population = []
    for rank, strategy_id in enumerate((discovery.BASELINE, *IDS)):
        for item in range(4):
            population.append(dict(ticker=f'Q{rank}{item}', strategy_ids=[strategy_id],
                discovery_score=1 if rank == 0 else .1, technical_score=7-rank/10,
                average_dollar_volume=100_000_000))
    output = discovery.rank_candidates(population)
    assert len(output) == len({row['ticker'] for row in output}) == 24
    assert {row['strategy_ids'][0] for row in output[:6]} == {discovery.BASELINE, *IDS}
    # With a one-slot operator cap, persistent rotation must expose every queue.
    first = [discovery.rank_candidates(population, cursor=cursor)[0]['strategy_ids'][0]
             for cursor in range(6)]
    assert len(set(first)) == 6


GATES = ('news', 'hold', 'confidence', 'relevance', 'sentiment', 'quote',
         'session', 'rr', 'cash', 'exposure', 'quote_after_ai', 'budget')


@pytest.mark.parametrize('strategy_id', IDS)
@pytest.mark.parametrize('block', GATES)
def test_each_route_preserves_all_original_admission_gates(db, clock, monkeypatch, strategy_id, block):
    frame, _, quote, review, _, _ = prepare_route(monkeypatch, clock, strategy_id)
    if block == 'news':
        monkeypatch.setattr('signal_news.existing_news', lambda *args, **kwargs: {})
    if block == 'hold':
        review.return_value['action'] = 'HOLD'
    if block == 'confidence':
        review.return_value['confidence'] = .79
    if block == 'relevance':
        review.return_value['news_relevance'] = .59
    if block == 'sentiment':
        review.return_value['news_sentiment'] = -.11
    if block == 'quote':
        monkeypatch.setattr(scanner, 'current_intraday_quote', lambda *args: None)
    if block == 'session':
        monkeypatch.setattr(scanner, 'regular_session_open', lambda: False)
    if block == 'rr':
        # The SAME real structural planner must block a nearby confirmed wall.
        frame.iloc[129, frame.columns.get_loc('High')] = quote + 1
    if block == 'cash':
        with database.get_db_connection() as conn:
            conn.execute('UPDATE scanner_accounts SET cash=0')
            conn.commit()
    if block == 'exposure':
        monkeypatch.setenv('STOCK_SCANNER_MAX_TOTAL_EXPOSURE', '100')
        monkeypatch.setenv('STOCK_SCANNER_PAPER_NOTIONAL', '200')
    if block == 'quote_after_ai':
        monkeypatch.setattr(scanner, 'current_intraday_quote',
            lambda *args: (quote*1.05 if review.called else quote, clock.instant.isoformat()))
    if block == 'budget':
        monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER', 'openrouter')
        monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_MODEL', 'synthetic-test-model')
        monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-noncredential-for-budget-block-only')
        budget_check = Mock(side_effect=RuntimeError('synthetic budget block'))
        monkeypatch.setattr('ai_budget.check', budget_check)
        provider_transport = Mock(side_effect=AssertionError('Budget must block transport'))
        monkeypatch.setattr(requests, 'post', provider_transport)
        # Budget is inside the actual final review; do not bypass it with the
        # synthetic approved-response Mock used by other lifecycle controls.
        review = Mock(wraps=ACTUAL_AI_REVIEW)
        monkeypatch.setattr(scanner, 'ai_review', review)
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    result = scanner.run_scan()
    assert not rows('SELECT id FROM scanner_orders'), result
    assert not rows('SELECT id FROM scanner_trades') and not rows('SELECT id FROM scanner_fills')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    if block in {'news', 'quote', 'session', 'rr'}:
        review.assert_not_called()
    if block == 'budget':
        assert review.call_count == budget_check.call_count == 1
        provider_transport.assert_not_called()
    if block == 'rr':
        assert any('nearest_resistance_below_2r' in row['reason'] or
                   'entry_inside_unresolved_price_zone' in row['reason'] or
                   'invalid_rounded_levels' in row['reason'] for row in result['rejected']), result
    if block == 'quote_after_ai':
        assert review.call_count == 1
        assert any('discovery_trigger_not_valid' in row['reason'] for row in result['rejected']), result


def test_two_real_detections_merge_one_ai_one_order_all_attribution(db, clock, monkeypatch):
    frame, context, _, review, _, _ = prepare_route(monkeypatch, clock, 'PEAD', multi=True)
    records = strategies.detect_all(frame, decision_at=DECISION, source_observed_at=OBSERVED,
        enabled_ids=['PEAD', 'STOCKBEE_MOMENTUM_BURST'], context=context)
    assert {key for key, value in records.items() if value['state'] == 'DETECTED'} == {
        'PEAD', 'STOCKBEE_MOMENTUM_BURST'}
    result = scanner.run_scan()
    assert result['signals_published'] == review.call_count == 1
    assert len(rows('SELECT id FROM scanner_orders')) == len(rows('SELECT id FROM scanner_signals')) == 1
    technical = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
    assert set(technical['entry_discovery']['strategy_ids']) == {'PEAD', 'STOCKBEE_MOMENTUM_BURST'}
    assert technical['discovery_score'] == max(value['score'] for value in records.values())
    scanner.run_scan()
    assert review.call_count == 1 and len(rows('SELECT id FROM scanner_orders')) == 1


def test_wrong_company_release_does_not_apply_pead_to_another_ticker():
    frame, context, decision, _ = route_case('PEAD', executable_structure=True)
    context['earnings_events'][0]['symbol'] = 'OTHER'
    candidates, observations = discovery.discover_candidates({'TEST': frame},
        {'TEST': {'company': 'Synthetic'}}, scanner.settings() | {'entry_strategy_ids': ['PEAD']},
        decision_at=decision, context=context, baseline_detector=lambda *args: None)
    assert not candidates
    assert observations[0]['strategy_results']['PEAD']['state'] == 'UNKNOWN'


def seed_close_hold(monkeypatch, clock):
    """Open one attributed long, then retain a separately attributed SELL hold."""
    frame, _, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    entry = dict(at='2026-10-06T14:05:00Z', open=quote, high=quote+.2, low=quote-.1, close=quote)
    engine.process_bar('TEST', entry)
    entry_package = json.loads(rows('SELECT settings_json FROM scanner_trades')[0]['settings_json'])['entry_discovery']
    closing_candidate = ACTUAL_ANALYZER('TEST', 'Synthetic Corporation', frame,
        scanner.settings(), baseline_filter=False, decision_at=clock.instant)
    closing_candidate.update(technical_direction='SELL', technical_score=7)
    record = discovery._baseline_evidence(closing_candidate, clock.instant, OBSERVED)
    closing_package = discovery.attribution([record], clock.instant)
    closing_candidate['entry_discovery'] = closing_package
    signal = dict(ticker='TEST', company='Synthetic Corporation', action='SELL', entry=quote,
        stop_loss=quote+4, confidence=.91, time_horizon='1-4 weeks', reason='Synthetic close association',
        relevant_news=[])
    close = engine.record_signal(signal, closing_candidate, {}, {}, 'synthetic-close-association')
    assert close['status'] == 'PENDING_CLOSE'
    with database.get_db_connection() as conn:
        conn.execute("UPDATE scanner_orders SET status='recovery_uncertain' WHERE signal_id=?", (close['id'],))
        conn.execute("UPDATE scanner_signals SET status='RECOVERY_UNCERTAIN' WHERE id=?", (close['id'],))
        conn.commit()
    return entry_package, closing_package, entry, quote


def test_close_long_attribution_matches_closing_signal_not_original_entry(db, clock, monkeypatch):
    from single_target_recovery import validate_snapshot
    entry_package, closing_package, _, _ = seed_close_hold(monkeypatch, clock)
    assert entry_package != closing_package
    order = rows("SELECT * FROM scanner_orders WHERE purpose='close_long'")[0]
    assert json.loads(order['plan_json']) == {'entry_discovery': closing_package}
    snapshot = {'version': 8, 'tables': {name: rows('SELECT * FROM '+name) for name in
        ('scanner_signals', 'scanner_orders', 'scanner_trades')}}
    validate_snapshot(snapshot)
    assert json.loads(rows('SELECT settings_json FROM scanner_trades')[0]['settings_json'])['entry_discovery'] == entry_package


def test_forged_future_attribution_blocks_creation_before_any_signal(db, clock, monkeypatch):
    frame, context, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    candidates, _ = discovery.discover_candidates({'TEST': frame},
        {'TEST': {'company': 'Synthetic'}}, scanner.settings() | {'entry_strategy_ids': ['PEAD']},
        decision_at=DECISION, context=context, baseline_detector=lambda *args: None)
    candidate = candidates[0]
    plan = scanner._candidate_target_plan(candidate, 'BUY', quote, scanner.settings(), quote_at=DECISION.isoformat())
    signal = dict(ticker='TEST', company='Synthetic', action='BUY', entry=quote, stop_loss=plan['stop'],
        target_plan=plan, confidence=.91, time_horizon='1-4 weeks', reason='Synthetic future block', relevant_news=[])
    future = DECISION + timedelta(seconds=1)
    candidate['entry_discovery']['detected_at'] = future.isoformat()
    candidate['entry_discovery']['detections'][0]['source_times']['decision_at'] = future.isoformat()
    with pytest.raises(ValueError, match='future|attribution'):
        engine.record_signal(signal, candidate, {}, {}, 'synthetic-future-attribution')
    assert not rows('SELECT id FROM scanner_signals') and not rows('SELECT id FROM scanner_orders')


def test_creation_disabled_does_not_accept_retained_new_route_as_new_signal(db, clock, monkeypatch):
    frame, context, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    candidates, _ = discovery.discover_candidates({'TEST': frame},
        {'TEST': {'company': 'Synthetic'}}, scanner.settings() | {'entry_strategy_ids': ['PEAD']},
        decision_at=DECISION, context=context, baseline_detector=lambda *args: None)
    candidate = candidates[0]
    plan = scanner._candidate_target_plan(candidate, 'BUY', quote, scanner.settings(), quote_at=DECISION.isoformat())
    monkeypatch.setenv(discovery.FLAGS['PEAD'], 'false')
    signal = dict(ticker='TEST', company='Synthetic', action='BUY', entry=quote, stop_loss=plan['stop'],
        target_plan=plan, confidence=.91, time_horizon='1-4 weeks', reason='Synthetic flag block', relevant_news=[])
    with pytest.raises(ValueError, match='new_entry_discovery_disabled'):
        engine.record_signal(signal, candidate, {}, {}, 'synthetic-creation-disabled')
    assert not rows('SELECT id FROM scanner_signals') and not rows('SELECT id FROM scanner_orders')


def retain_204_audit_only_fixture():
    """Fixture conversion BEFORE execution, not a data migration or app policy."""
    with database.get_db_connection() as conn:
        for table, field in (('scanner_signals', 'technical_json'), ('scanner_orders', 'plan_json')):
            row = rows(f'SELECT id,{field} FROM {table}')[0]
            material = json.loads(row[field])
            assert material.pop('entry_strategy_execution')['version'] == 'independent_entry_execution_v1'
            conn.execute(f'UPDATE {table} SET {field}=? WHERE id=?', (json.dumps(material), row['id']))
        conn.commit()


def test_completed_setup_discovery_keeps_existing_passive_limit_gap_semantics(db, clock, monkeypatch):
    """Retained204 audit-only contracts must NOT acquire the new fill policy.

    Explicitly remove the newly generated executable node from signal/order,
    reproducing the historical204 audit-only shape before processing ANY bar.
    No executable contract is removed from a live or previously filled order.
    """
    import single_target_policy
    prepare_route(monkeypatch, clock, 'RELATIVE_STRENGTH_LEADER')
    assert scanner.run_scan()['signals_published'] == 1
    retain_204_audit_only_fixture()
    contract = json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    frozen = copy.deepcopy(contract)
    pivot = contract['entry_discovery']['detections'][0]['trigger']['level']
    plan = contract['target_plan']
    assert pivot == pytest.approx(100.85) and plan['entry'] == 102
    assert 100.8 < pivot and single_target_policy.validate_fill(plan, 100.8) >= 2
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    bar = dict(at='2026-10-06T14:05:00Z', open=100.8, high=101, low=100.6, close=100.8)
    engine.process_bar('TEST', bar)
    trades = rows('SELECT entry_price,original_stop,tp1,status FROM scanner_trades')
    assert len(trades) == 1 and trades[0]['status'] == 'open'
    assert trades[0]['entry_price'] < pivot
    assert trades[0]['original_stop'] == plan['stop'] and trades[0]['tp1'] == plan['active_target']
    assert json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']) == frozen
    engine.initialize_runtime()
    engine.process_bar('TEST', bar)
    assert len(rows('SELECT id FROM scanner_fills')) == 1


def test_recovery_rejects_future_audit_even_when_all_three_nodes_match(db, clock, monkeypatch):
    import active_snapshot
    import entry_strategy_execution as execution
    import single_target_recovery
    _, _, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    scanner.run_scan()
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=quote,
        high=quote+.2, low=quote-.1, close=quote))
    data = active_snapshot.export_data(database._SQLITE_DB_PATH)
    future = (DECISION + timedelta(seconds=1)).isoformat()
    for table, field in (('scanner_signals', 'technical_json'), ('scanner_orders', 'plan_json'),
                         ('scanner_trades', 'settings_json')):
        for row in data['tables'][table]:
            material = json.loads(row[field])
            assert execution.KEY in material
            assert material[execution.KEY]['version'] == execution.VERSION
            package = material['entry_discovery']
            package['detected_at'] = future
            for record in package['detections']:
                record['source_times']['decision_at'] = future
            row[field] = json.dumps(material)
    # The new frozen audit digest/creation association rejects this mutation
    # before the later standalone future-attribution check is reached.
    with pytest.raises(ValueError, match='^entry_strategy_execution_contract_invalid$'):
        single_target_recovery.validate_snapshot(data)


def test_opposing_baseline_sell_is_explicit_conflict_not_false_buy_attribution():
    frame, context, decision, _ = route_case('STOCKBEE_MOMENTUM_BURST', executable_structure=True)
    cfg = scanner.settings() | {'entry_strategy_ids': ['STOCKBEE_MOMENTUM_BURST']}
    baseline = ACTUAL_ANALYZER('TEST', 'Synthetic', frame, cfg,
        baseline_filter=False, decision_at=decision)
    baseline.update(technical_direction='SELL', technical_score=6)
    candidates, observations = discovery.discover_candidates({'TEST': frame},
        {'TEST': {'company': 'Synthetic'}}, cfg, decision_at=decision, context=context,
        baseline_detector=lambda *args: copy.deepcopy(baseline))
    assert len(candidates) == 1 and candidates[0]['technical_direction'] == 'SELL'
    assert candidates[0]['strategy_ids'] == [discovery.BASELINE]
    assert all(record['direction'] == 'SELL' for record in candidates[0]['entry_discovery']['detections'])
    assert observations[0]['strategy_results']['STOCKBEE_MOMENTUM_BURST']['state'] == 'DETECTED'
    assert observations[0]['common_reasons'] == ['opposing_baseline_direction']


@pytest.mark.parametrize('exit_strategy', ('single', 'staged'))
def test_new_attribution_with_original_v1_exit_policy_sanitizes_without_policy_conversion(
        db, clock, monkeypatch, exit_strategy):
    import active_snapshot
    import recovery_state as recovery
    frame, _, quote, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    # Three genuinely confirmed source pivots feed the ORIGINAL V1 planner.
    # No V2 contract is forged, and global defaults are not changed in source.
    frame.iloc[133, frame.columns.get_loc('High')] = 150
    frame.iloc[137, frame.columns.get_loc('High')] = 160
    for flag in ('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED',
                 'STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED',
                 'STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED',
                 'STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED'):
        monkeypatch.setenv(flag, 'false')
    engine.set_active_strategy(exit_strategy)
    assert scanner.run_scan()['signals_published'] == 1
    order = json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    assert order['target_plan']['method'] == 'confirmed_daily_swing_zones_v1'
    assert order['execution_settings']['active_strategy'] == exit_strategy
    assert len(order['target_plan']['targets']) == 3
    package = order['entry_discovery']
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=quote,
        high=quote+.2, low=quote-.1, close=quote))
    assert {row['strategy'] for row in rows('SELECT strategy FROM scanner_trades')} == {'single', 'staged'}
    assert rows('SELECT strategy FROM scanner_trades WHERE is_shadow=0') == [{'strategy': exit_strategy}]
    raw = active_snapshot.export_data(database._SQLITE_DB_PATH)
    sanitized = recovery.sanitize(raw)
    assert sanitized['version'] == sanitized['recovery_format'] == 8
    recovery.validate(json.loads(json.dumps(sanitized)))
    assert all(set(json.loads(row['technical_json'])) == {
                   'entry_discovery', 'target_plan', 'entry_strategy_execution'}
               and json.loads(row['technical_json'])['entry_discovery'] == package
               for row in sanitized['tables']['scanner_signals'])
    assert all(json.loads(row['settings_json'])['entry_discovery'] == package
               and json.loads(row['settings_json'])['target_plan'] == order['target_plan']
               and json.loads(row['settings_json'])['entry_strategy_execution'] == order['entry_strategy_execution']
               for row in sanitized['tables']['scanner_trades'])
    assert json.loads(sanitized['tables']['scanner_orders'][0]['plan_json']) == order
    assert [(row['original_stop'], row['tp1'], row['tp2'], row['tp3'])
            for row in raw['tables']['scanner_trades']] == [
           (row['original_stop'], row['tp1'], row['tp2'], row['tp3'])
            for row in sanitized['tables']['scanner_trades']]


@pytest.mark.parametrize('strategy_id', ('RELATIVE_STRENGTH_LEADER', 'TREND_PULLBACK_RECLAIM'))
def test_new_frozen_support_declines_actual_gap_then_retries_without_level_moves(
        db, clock, monkeypatch, strategy_id):
    import single_target_policy
    import entry_strategy_execution as execution
    frame, _, quote, _, _, _ = prepare_route(monkeypatch, clock, strategy_id)
    if strategy_id == 'TREND_PULLBACK_RECLAIM':
        # The V2 fixture's gap crosses an old resistance and is correctly
        # declined by the ORIGINAL guard first. Exercise the new EMA boundary
        # independently under the supported original V1 policy, with real
        # source pivots and its unchanged three targets/native+shadow paths.
        frame.iloc[133, frame.columns.get_loc('High')] = 150
        frame.iloc[137, frame.columns.get_loc('High')] = 160
        monkeypatch.setenv('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED', 'false')
    assert scanner.run_scan()['signals_published'] == 1
    order = rows('SELECT * FROM scanner_orders')[0]
    contract = json.loads(order['plan_json'])
    saved, plan = contract[execution.KEY], contract['target_plan']
    assert saved == json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])[execution.KEY]
    support = saved['branches'][0]['support']
    # Engine applies the saved adverse slippage BEFORE checking support.
    gap = 100.8 if strategy_id == 'RELATIVE_STRENGTH_LEADER' else support - .2
    assert gap < support < quote
    if strategy_id == 'RELATIVE_STRENGTH_LEADER':
        assert single_target_policy.validate_fill(plan, gap) >= 2  # NEW rule, not old RR, blocks it.
    else:
        assert plan['method'] == 'confirmed_daily_swing_zones_v1' and plan['stop'] < gap < plan['targets'][0]
    account = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    bad = dict(at='2026-10-06T14:05:00Z', open=gap, high=gap+.1, low=gap-.1, close=gap)
    clock.instant = datetime(2026, 10, 6, 14, 7, tzinfo=timezone.utc)
    engine.process_bar('TEST', bad)
    assert json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']) == contract
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', bad)
    blocked = rows('SELECT * FROM scanner_orders')[0]
    observed = json.loads(blocked['plan_json'])
    assert blocked['status'] == 'pending' and execution.public_wait(blocked)['reason'] == 'strategy_fill_below_support'
    assert {k: v for k, v in observed.items() if k != execution.OBSERVATION_KEY} == contract
    assert not rows('SELECT id FROM scanner_fills') and not rows('SELECT id FROM scanner_trades')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == account
    engine.initialize_runtime()
    engine.process_bar('TEST', bad)
    assert rows('SELECT * FROM scanner_orders')[0] == blocked
    # A known rejected touch is NOT inferred as an uncertain fill on restart.
    engine._pending_recovery_check('TEST', [bad], datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc))
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    legal = dict(at='2026-10-06T14:10:00Z', open=quote, high=quote+.1, low=quote-.1, close=quote)
    clock.instant = datetime(2026, 10, 6, 14, 15, tzinfo=timezone.utc)
    engine.process_bar('TEST', legal)
    count = 2 if strategy_id == 'TREND_PULLBACK_RECLAIM' else 1
    assert len(rows('SELECT id FROM scanner_fills')) == count
    trade = rows('SELECT * FROM scanner_trades')[0]
    assert trade['entry_price'] > support and trade['original_stop'] == plan['stop'] and trade['tp1'] == plan['targets'][0]
    assert json.loads(trade['settings_json'])[execution.KEY] == saved
    engine.initialize_runtime()
    engine.process_bar('TEST', legal)
    assert len(rows('SELECT id FROM scanner_fills')) == count


@pytest.mark.parametrize('damage', ('version', 'support', 'signal_association', 'orphan_observation'))
def test_new_malformed_execution_becomes_uncertain_without_cash_or_fill(db, clock, monkeypatch, damage):
    import entry_strategy_execution as execution
    prepare_route(monkeypatch, clock, 'RELATIVE_STRENGTH_LEADER')
    assert scanner.run_scan()['signals_published'] == 1
    order = rows('SELECT * FROM scanner_orders')[0]
    contract = json.loads(order['plan_json'])
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    with database.get_db_connection() as conn:
        if damage == 'version':
            contract[execution.KEY]['version'] = 'future_unsupported'
        elif damage == 'support':
            contract[execution.KEY]['branches'][0]['support'] -= 10
        elif damage == 'signal_association':
            technical = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
            technical.pop(execution.KEY)
            conn.execute('UPDATE scanner_signals SET technical_json=?', (json.dumps(technical),))
        else:
            contract.pop(execution.KEY)
            contract[execution.OBSERVATION_KEY] = {}
        conn.execute('UPDATE scanner_orders SET plan_json=?', (json.dumps(contract),))
        conn.commit()
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=102, high=102.1, low=101.9, close=102))
    # Structural corruption is detected before entry. Signal association is
    # checked at admission-to-trade and terminally rejects this known touch.
    expected = 'invalid' if damage == 'signal_association' else 'recovery_uncertain'
    assert rows('SELECT status FROM scanner_orders') == [{'status': expected}]
    assert not rows('SELECT id FROM scanner_fills') and not rows('SELECT id FROM scanner_trades')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before


def test_bridge_role_cannot_create_even_with_flags_enabled(db, clock, monkeypatch):
    import entry_discovery_capabilities as capabilities
    prepare_route(monkeypatch, clock, 'PEAD')
    monkeypatch.setattr(capabilities, 'BUILD_ROLE', 'bridge')
    monkeypatch.setenv('ENTRY_DISCOVERY_ROLE', 'candidate')
    assert not capabilities.creation_allowed()
    result = scanner.run_scan()
    assert result['signals_published'] == 0
    assert not rows('SELECT id FROM scanner_orders') and not rows('SELECT id FROM scanner_fills')


RELEASE_URL = 'https://www.prnewswire.com/news-releases/synthetic-earnings-301000001.html'


def original_release_html(published, body=None):
    body = body or ('Synthetic Corporation (NASDAQ: TEST) today reported financial results '
                    'for the quarter ended September 30, 2026.')
    return (f'<html><head><meta property="article:published_time" content="{published}">'
            f'<link rel="canonical" href="{RELEASE_URL}"></head><body><p>{body}</p></body></html>').encode()


def parse_original_release(raw, *, previous=None):
    import earnings_releases as releases
    _, context, _, _ = route_case('PEAD')
    release = context['earnings_events'][0]['released_at']
    return releases.parse_release(raw, url=RELEASE_URL, provider='prnewswire',
        catalog={'TEST': {'cik': '123'}}, first_seen_at=release,
        observed_at=DECISION-timedelta(seconds=3), processed_at=OBSERVED, previous=previous)


@pytest.mark.parametrize('body', (
    'Synthetic Corporation (NASDAQ: TEST) announced that it will report financial results '
    'for the quarter ended September 30, 2026 next week.',
    'Synthetic Corporation (NASDAQ: TEST) announces a conference to discuss financial results '
    'for the quarter ended September 30, 2026 next week.',
    'Synthetic Corporation (NASDAQ: TEST) announced financial results for the quarter ended '
    'September 30, 2026 will be released next week.',
    'Synthetic Corporation (NASDAQ: TEST) has not reported financial results '
    'for the quarter ended September 30, 2026.',
))
def test_original_release_parser_does_not_turn_preview_into_published_results(body):
    _, context, _, _ = route_case('PEAD')
    fact = parse_original_release(original_release_html(context['earnings_events'][0]['released_at'], body))
    assert fact['verified'] is False, fact


def test_original_release_parser_same_url_retraction_cannot_remain_verified():
    _, context, _, _ = route_case('PEAD')
    stamp = context['earnings_events'][0]['released_at']
    prior = parse_original_release(original_release_html(stamp))
    assert prior['verified'] is True
    corrected = parse_original_release(original_release_html(stamp,
        'THIS RELEASE HAS BEEN RETRACTED. Synthetic Corporation (NASDAQ: TEST) today reported '
        'financial results for the quarter ended September 30, 2026.'), previous=prior)
    assert corrected['verified'] is False or corrected['retracted'] is True, corrected


def seed_original_release_source(raw, *, suffix='one', collected=None):
    _, context, _, _ = route_case('PEAD')
    collected = collected or context['earnings_events'][0]['released_at']
    source = dict(url=RELEASE_URL, title='Synthetic Corporation quarterly financial results',
        source_excerpt='Original quarterly earnings release', published_at='1999-01-01T00:00:00Z')
    with database.get_db_connection() as conn:
        conn.execute('INSERT INTO ne_events(event_id,body_json,evidence_version,status,reason,created_at,updated_at) '
                     'VALUES(?,?,?,?,?,?,?)', ('release-'+suffix, '{}', suffix, 'observed', None, collected, collected))
        conn.execute('INSERT INTO ne_sources(source_key,event_id,provider_id,content_hash,body_json,collected_at,source_id,active) '
                     'VALUES(?,?,?,?,?,?,?,1)', ('source-'+suffix, 'release-'+suffix, 'prnewswire', suffix,
                     json.dumps(source), collected, 'same-original-id'))
        conn.commit()


def test_original_release_producer_to_reader_to_actual_pead_and_restart(db, clock, monkeypatch):
    import earnings_releases as releases
    import entry_strategy_inputs as inputs
    frame, context, _, _, _, _ = prepare_route(monkeypatch, clock, 'PEAD')
    published = context['earnings_events'][0]['released_at']
    raw = original_release_html(published)
    seed_original_release_source(raw)
    transport = Mock()
    transport.request.return_value = raw
    known = DECISION-timedelta(seconds=3)
    result = releases.produce(catalog={'TEST': {'cik': '123'}}, transport=transport,
        clock=lambda: known, enabled=True, approvals={'prnewswire'})
    assert result['processed'] == result['verified'] == 1 and transport.request.call_count == 1
    facts, coverage = inputs.load_verified_earnings(['TEST'], DECISION)
    assert coverage['status'] == 'ready' and len(facts['TEST']) == 1
    fact = facts['TEST'][0]
    assert fact['released_at'] == published and fact['released_at'] != '1999-01-01T00:00:00Z'
    assert fact['source_observed_at'] == fact['processed_at'] == fact['effective_available_at'] == known.isoformat()
    assert releases.read_facts(['TEST'], known-timedelta(microseconds=1))[0] == {}
    context['earnings_events'] = facts['TEST']
    actual = strategies.detect_all(frame, decision_at=DECISION, source_observed_at=OBSERVED,
        enabled_ids=['PEAD'], context=context)['PEAD']
    assert actual['state'] == 'DETECTED', actual
    expected = {key: fact[key] for key in ('revision', 'document_hash', 'parser_version',
        'issuer_cik', 'issuer_mapping_hash', 'source_url')}
    assert actual['features']['release_evidence'] == expected
    assert scanner.run_scan()['signals_published'] == 1
    saved = json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])['entry_discovery']
    assert saved['detections'][0]['sourcehash'] == actual['sourcehash']
    assert saved['detections'][0]['features']['release_evidence'] == expected
    frozen_decision = copy.deepcopy(saved)
    revised_context = copy.deepcopy(context)
    revised_context['earnings_events'][0]['document_hash'] = '0'*64
    revised = strategies.detect_all(frame, decision_at=DECISION, source_observed_at=OBSERVED,
        enabled_ids=['PEAD'], context=revised_context)['PEAD']
    assert revised['state'] == 'DETECTED' and revised['sourcehash'] != actual['sourcehash']
    retained = rows("SELECT scan_id,metrics_json FROM scanner_candidates WHERE stage='earnings_release'")
    result2 = releases.produce(catalog={'TEST': {'cik': '123'}}, transport=transport,
        clock=lambda: known+timedelta(seconds=1), enabled=True, approvals={'prnewswire'})
    assert result2['processed'] == 0 and transport.request.call_count == 1
    assert rows("SELECT scan_id,metrics_json FROM scanner_candidates WHERE stage='earnings_release'") == retained
    # A newly discovered same-original URL is retained as an UNKNOWN revision,
    # not a path to revive the old verified release after parsing fails.
    later = known+timedelta(seconds=1)
    seed_original_release_source(b'invalid', suffix='two', collected=later.isoformat())
    transport.request.return_value = b'<html><p>Publication timestamp removed on correction</p></html>'
    releases.produce(catalog={'TEST': {'cik': '123'}}, transport=transport,
        clock=lambda: later, enabled=True, approvals={'prnewswire'})
    current, _ = releases.read_facts(['TEST'], DECISION)
    assert len(current['TEST']) == 1 and current['TEST'][0]['verified'] is False
    assert json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])['entry_discovery'] == frozen_decision
    assert rows("SELECT scan_id,metrics_json FROM scanner_candidates WHERE stage='earnings_release' ORDER BY id")[:len(retained)] == retained
    context['earnings_events'] = current['TEST']
    assert strategies.detect_all(frame, decision_at=DECISION, source_observed_at=OBSERVED,
        enabled_ids=['PEAD'], context=context)['PEAD']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('role,enabled', (('candidate', False), ('bridge', True)))
def test_release_producer_off_or_bridge_never_touches_db_or_transport(monkeypatch, role, enabled):
    import earnings_releases as releases
    import entry_discovery_capabilities as capabilities
    monkeypatch.setattr(capabilities, 'BUILD_ROLE', role)
    db_connect = Mock(side_effect=AssertionError('OFF/bridge DB touched'))
    transport = Mock()
    assert releases.produce(connect=db_connect, transport=transport, enabled=enabled)['status'] == 'off'
    db_connect.assert_not_called()
    transport.request.assert_not_called()


def test_retained_audit_exports7_and_old_mislabelled_audit6_snapshot_is_explicitly_unsupported(db, clock, monkeypatch):
    import active_snapshot
    import recovery_state as recovery
    prepare_route(monkeypatch, clock, 'RELATIVE_STRENGTH_LEADER')
    assert scanner.run_scan()['signals_published'] == 1
    retain_204_audit_only_fixture()
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=102, high=102.1, low=101.9, close=102))
    data = recovery.sanitize(active_snapshot.export_data(database._SQLITE_DB_PATH))
    assert data['version'] == data['recovery_format'] == 7
    recovery.validate(data)
    previous204 = copy.deepcopy(data)
    previous204.update(version=6, recovery_format=6)
    previous204.pop('snapshot_id')
    previous204['snapshot_id'] = active_snapshot.digest(previous204)
    with pytest.raises(ValueError, match='discovery_snapshot_format_content_mismatch'):
        recovery.validate(previous204)


@pytest.mark.parametrize('evidence', ('touch_straddles_expiry', 'missing_bar'))
def test_new_frozen_window_expiry_or_gap_is_uncertain_not_fabricated_fill(db, clock, monkeypatch, evidence):
    prepare_route(monkeypatch, clock, 'RELATIVE_STRENGTH_LEADER')
    monkeypatch.setenv('STOCK_SCANNER_SIGNAL_VALIDITY_HOURS', '1')
    assert scanner.run_scan()['signals_published'] == 1
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    bars = [dict(at=f'2026-10-06T14:{minute:02d}:00Z', open=103, high=103.1, low=102.9, close=103)
            for minute in range(5, 60, 5)]
    straddle = dict(at='2026-10-06T15:00:00Z', open=102, high=102.1, low=101.9, close=102)
    clock.instant = datetime(2026, 10, 6, 15, 5, tzinfo=timezone.utc)
    available = bars+[straddle] if evidence == 'touch_straddles_expiry' else []
    # Exercise the ACTUAL monitor ordering: recovery classification precedes
    # replay/cursor advancement and expiry. Directly calling process_bar first
    # would incorrectly simulate an already-processed recovery cursor.
    monkeypatch.setattr(engine, 'datetime', clock)
    monkeypatch.setattr(engine, '_bar_dicts', lambda *args: available)
    engine.monitor_prices()
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'recovery_uncertain'}]
    assert not rows('SELECT id FROM scanner_fills') and not rows('SELECT id FROM scanner_trades')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    engine.initialize_runtime()
    engine._expire_recovered_orders('TEST', clock.instant+timedelta(days=3))
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'recovery_uncertain'}]
