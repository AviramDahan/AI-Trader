"""Reviewer-owned real scanner/engine proof with invented, causal source data.

Only provider IO, the final model response and the API projection are doubles.
Detectors, RVOL arithmetic, target planning, admission, fills and exits are real.
This is not a natural market observation or a profitability experiment.
"""
import copy
import json
import socket
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

import database
import entry_discovery as discovery
import entry_intraday as intraday
import entry_strategy_execution as execution
import intraday_volume as volume
import scanner_engine as engine
import stock_scanner as scanner
from review_evidence import ObservedQuote, completed_observation
from test_entry_intraday import prior_case, DECISION, OBSERVED, IDS
from test_signal_admission_chain import prepare, rows
from test_signal_inputs import db, clock

ACTUAL_ANALYZER = scanner.analyze_history
ACTUAL_COLLECTOR = scanner._ScanVolumeEvidence
UTC = timezone.utc


@pytest.fixture(autouse=True)
def external_io_forbidden(monkeypatch):
    def denied(*a, **k):
        raise AssertionError('Independent lifecycle QA forbids external IO')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', denied)


def source(interval):
    return dict(provider='yahoo', interval=interval, auto_adjust=True,
                actions=True, volume_basis='reported_shares_unscaled')


def setup_pipeline(monkeypatch, clock, sid, *, low_volume=False):
    _, review, session = prepare(monkeypatch, clock)
    clock.instant = DECISION
    # These are explicitly invented news fixtures. Move their original clocks
    # before this invented decision, not a real article's availability time.
    with database.get_db_connection() as conn:
        row = conn.execute("SELECT body_json FROM ne_events WHERE event_id='company-story'").fetchone()
        conn.execute("UPDATE ne_events SET body_json=?,created_at=?,updated_at=? WHERE event_id='company-story'",
            (row['body_json'].replace('2026-10-05', '2026-10-04'),
             '2026-10-04T18:01:00+00:00', '2026-10-04T18:01:00+00:00'))
        conn.commit()
    frame, context = prior_case(sid)
    # A real confirmed structural anchor outside the VCP120-day base but
    # within the unchanged126-day planner; no planner or threshold is mocked.
    frame.iloc[129, frame.columns.get_loc('High')] = 140.
    if sid in {'TREND_PULLBACK_RECLAIM', 'RELATIVE_STRENGTH_LEADER'}:
        # Their monotone original bases have no confirmed recent swing low.
        # Add an invented trough with five later completed sessions, rather
        # than bypassing the planner's correct missing-stop rejection.
        frame.iloc[-6, frame.columns.get_loc('Low')] -= 2.
    frame.attrs['price_basis'] = intraday.PRICE_BASIS
    context['symbol'] = 'TEST'
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    monkeypatch.setenv(discovery.FLAGS[sid], 'true')
    monkeypatch.setenv(intraday.FLAG, 'true')
    for flag in ('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED',
                 'STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED',
                 'STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED',
                 'STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED'):
        monkeypatch.setenv(flag, 'true')
    monkeypatch.setattr(scanner, 'analyze_history', ACTUAL_ANALYZER)
    monkeypatch.setattr(scanner, 'load_historical_data',
        lambda *a, **k: ({'TEST': frame}, {'status': 'invented-causal-prior-daily'}))
    import entry_strategy_inputs
    monkeypatch.setattr(entry_strategy_inputs, 'load_context', lambda *a, **k: context)
    cfg = scanner.settings()
    assert ACTUAL_ANALYZER('TEST', 'Synthetic Corporation', frame, cfg, decision_at=DECISION) is None
    setups = intraday.prepare_setups(frame, decision_at=DECISION,
        source_observed_at=OBSERVED, enabled_ids=[sid], context=context)
    setup = setups[sid]
    assert setup['state'] == 'FORMING', setup
    level = setup['trigger']['level']
    # Pullback's prior high is just below its frozen3% chase cap. Use an
    # invented quote above that high, still inside the unchanged entry band.
    quote = level*(1.0296 if sid == 'TREND_PULLBACK_RECLAIM' else 1.029)
    end = DECISION.replace(second=0, microsecond=0)
    current = pd.DataFrame(dict(Open=level*.999, High=level*1.0295,
        Low=level*.998, Close=level*1.028, Volume=100000., **{'Stock Splits': 0.}),
        index=pd.date_range('2026-10-05T13:30Z', end, freq='min'))
    current.iloc[-1, current.columns.get_loc('Close')] = quote
    prior_dates = pd.bdate_range('2026-09-21', '2026-10-02')
    assert len(prior_dates) == 10
    history = pd.concat([pd.DataFrame(dict(Open=100., High=101., Low=99.,
        Close=100., Volume=250000. if not low_volume else 1000000., **{'Stock Splits': 0.}),
        index=pd.date_range(day.strftime('%Y-%m-%d')+'T13:30Z',
            day.strftime('%Y-%m-%d')+'T20:00Z', freq='5min', inclusive='left'))
        for day in prior_dates])
    provider = Mock(return_value=history)
    monkeypatch.setattr(scanner, '_intraday_history', provider)
    cache = volume.HistoryCache(clock=lambda: clock.instant)
    monkeypatch.setattr(scanner, '_ScanVolumeEvidence',
        lambda **kw: ACTUAL_COLLECTOR(history_cache=cache, **kw))
    def current_quote(*a):
        observed = DECISION-timedelta(seconds=2)
        evidence = completed_observation(current, observed_at=observed, completed_before=end)
        evidence['price_basis'] = intraday.PRICE_BASIS
        return ObservedQuote(quote, end.isoformat(), evidence, volume_frame=current,
            source_observed_at=observed, completed_before=end, volume_source=source('1m'))
    monkeypatch.setattr(scanner, 'current_intraday_quote', current_quote)
    engine.initialize_runtime()
    return frame, setup, quote, review, provider, current_quote


@pytest.mark.parametrize('sid', IDS)
@pytest.mark.parametrize('exit_kind', ['target', 'stop'])
def test_real_intraday_scan_admission_fill_paused_exit_restart(db, clock, monkeypatch, sid, exit_kind):
    _, _, quote, review, provider, _ = setup_pipeline(monkeypatch, clock, sid)
    before = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    result = scanner.run_scan()
    assert result['signals_published'] == review.call_count == 1, json.dumps({
        key: result.get(key) for key in ('rejected', 'selection', 'discovery', 'errors')}, default=str)
    assert provider.call_count == 1
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
    assert not rows('SELECT id FROM scanner_trades') and not rows('SELECT id FROM scanner_fills')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == before
    order = rows('SELECT * FROM scanner_orders')[0]
    contract = json.loads(order['plan_json'])
    package = contract['entry_discovery']
    assert package['version'] == discovery.INTRADAY_VERSION
    assert package['strategy_ids'] == [sid]
    assert package['detections'][0]['state'] == 'DETECTED'
    assert contract[execution.KEY]['version'] == execution.INTRADAY_VERSION
    plan = contract['target_plan']
    assert plan['minimum_rr'] == 2 and plan['rr'][0] >= 2
    frozen = copy.deepcopy(contract)
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    monkeypatch.setenv(intraday.FLAG, 'false')
    import entry_discovery_capabilities
    monkeypatch.setattr(entry_discovery_capabilities, 'BUILD_ROLE', 'bridge')
    entry = dict(at='2026-10-05T14:05:00Z', open=quote, high=quote+.02,
                 low=quote-.02, close=quote)
    clock.instant = datetime(2026, 10, 5, 14, 10, tzinfo=UTC)
    engine.process_bar('TEST', entry)
    engine.initialize_runtime()
    engine.process_bar('TEST', entry)
    assert len(rows('SELECT id FROM scanner_trades')) == 1, rows('SELECT status,plan_json FROM scanner_orders')
    assert len(rows('SELECT id FROM scanner_fills')) == 1
    assert rows('SELECT status FROM scanner_orders') == [{'status': 'filled'}]
    assert json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']) == frozen
    import entry_emergency
    paused = entry_emergency.set_paused(True, 0, now=clock.instant)
    assert paused['paused'] is True
    # Emergency9 plus saved intraday10 must stay format10; no actual restore.
    import active_snapshot, recovery_state
    snapshot = active_snapshot.export_data(db/'isolated.db')
    sanitized = recovery_state.sanitize(snapshot)
    assert sanitized['recovery_format'] == sanitized['version'] == 10
    recovery_state.validate(sanitized)
    value = plan['active_target'] if exit_kind == 'target' else plan['stop']
    exit_bar = dict(at='2026-10-05T14:10:00Z', open=value, high=value+.02,
                    low=value-.02, close=value)
    clock.instant = datetime(2026, 10, 5, 14, 15, tzinfo=UTC)
    engine.process_bar('TEST', exit_bar)
    after = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    engine.initialize_runtime()
    for bar in (entry, exit_bar):
        engine.process_bar('TEST', bar)
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == after
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [
        {'status': 'closed', 'remaining_quantity': 0}]
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


def test_unconfirmed_setup_cannot_call_ai_or_create_order(db, clock, monkeypatch):
    _, _, _, review, provider, _ = setup_pipeline(monkeypatch, clock, IDS[0], low_volume=True)
    result = scanner.run_scan()
    assert result['signals_published'] == 0, result
    review.assert_not_called()
    assert provider.call_count == 1
    assert not rows('SELECT id FROM scanner_orders')


def test_direct_admission_rejects_provisional_before_signal_fields_or_db(monkeypatch):
    denied = Mock(side_effect=AssertionError('provisional reached the DB'))
    monkeypatch.setattr(engine, 'get_db_connection', denied)
    with pytest.raises(ValueError, match='^intraday_confirmation_not_valid$'):
        engine.record_signal({}, {'_intraday_provisional': True}, {}, {}, 'invented')
    denied.assert_not_called()


@pytest.mark.parametrize('gate', ['news', 'hold', 'confidence', 'risk'])
def test_confirmation_does_not_replace_news_or_final_ai_gates(db, clock, monkeypatch, gate):
    frame, _, quote, review, _, _ = setup_pipeline(monkeypatch, clock, IDS[0])
    if gate == 'news':
        monkeypatch.setattr('signal_news.existing_news', lambda *a, **k: {})
    elif gate == 'hold':
        review.return_value['action'] = 'HOLD'
    elif gate == 'confidence':
        review.return_value['confidence'] = .79
    else:
        # A confirmed resistance whose unchanged ATR buffer is below entry.
        # Detection may confirm, but the real target planner must reject it.
        frame.iloc[129, frame.columns.get_loc('High')] = quote+.1
    result = scanner.run_scan()
    assert result['signals_published'] == 0, result
    if gate in {'news', 'risk'}:
        review.assert_not_called()
    else:
        assert review.call_count == 1
    assert not rows('SELECT id FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_fills')


def test_paused_pending_new_contract_has_no_retrofill_after_resume(db, clock, monkeypatch):
    _, _, quote, review, _, _ = setup_pipeline(monkeypatch, clock, IDS[0])
    assert scanner.run_scan()['signals_published'] == review.call_count == 1
    before = json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    until = rows('SELECT valid_until FROM scanner_orders')[0]['valid_until']
    import entry_emergency
    entry_emergency.set_paused(True, 0, now=DECISION+timedelta(minutes=1))
    for flag in discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    monkeypatch.setenv(intraday.FLAG, 'false')
    def bar(minute):
        return dict(at=f'2026-10-05T14:{minute:02d}:00Z', open=quote,
                    high=quote+.02, low=quote-.02, close=quote)
    clock.instant = datetime(2026, 10, 5, 14, 10, tzinfo=UTC)
    engine.process_bar('TEST', bar(5))
    assert not rows('SELECT id FROM scanner_fills')
    entry_emergency.set_paused(False, 1, now=datetime(2026, 10, 5, 14, 12, tzinfo=UTC))
    clock.instant = datetime(2026, 10, 5, 14, 15, tzinfo=UTC)
    engine.initialize_runtime()
    engine.process_bar('TEST', bar(5))
    engine.process_bar('TEST', bar(10))  # straddles actual resume
    assert not rows('SELECT id FROM scanner_fills')
    clock.instant = datetime(2026, 10, 5, 14, 20, tzinfo=UTC)
    engine.process_bar('TEST', bar(15))
    assert len(rows('SELECT id FROM scanner_fills')) == 1
    assert rows('SELECT valid_until FROM scanner_orders') == [{'valid_until': until}]
    assert json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']) == before
    engine.initialize_runtime()
    engine.process_bar('TEST', bar(15))
    assert len(rows('SELECT id FROM scanner_fills')) == 1
