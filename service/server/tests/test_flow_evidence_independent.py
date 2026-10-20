"""Reviewer-owned synthetic edge cases; no live providers or trading evidence."""
import copy
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import socket

import pandas as pd
import pytest
import requests

import intraday_volume as rvol

NOW = datetime(2026, 10, 21, 14, 10, 37, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Independent evidence QA forbids external IO')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)


def source(interval):
    return dict(provider='yahoo', interval=interval, auto_adjust=True, actions=True,
                volume_basis='reported_shares_unscaled')


def bars(index, volume=20.):
    return pd.DataFrame(dict(Open=100., High=101., Low=99., Close=100.,
                             Volume=volume, **{'Stock Splits': 0.}), index=index)


def independent_frames():
    # Explicit invented regular sessions, not the implementation's fixture or
    # ratio calculator. All are ordinary NYSE dates in this fixed test window.
    current = bars(pd.date_range('2026-10-21T13:30Z', '2026-10-21T14:10Z', freq='min'))
    days = pd.bdate_range('2026-10-07', '2026-10-20')
    assert len(days) == 10
    history = pd.concat([
        bars(pd.date_range(day.strftime('%Y-%m-%d')+'T13:30Z',
                           day.strftime('%Y-%m-%d')+'T20:00Z',
                           freq='5min', inclusive='left'), 50.)
        for day in days
    ])
    return current, history


def evaluate(current, history, **changes):
    args = dict(decision_at=NOW, current_observed_at=NOW-timedelta(seconds=1),
                history_observed_at=NOW-timedelta(seconds=2),
                completed_before=NOW-timedelta(seconds=3),
                current_source=source('1m'), history_source=source('5m'))
    args.update(changes)
    return rvol.evaluate(current, history, **args)


def produce(current, history, *, enabled=True, monkeypatch=None):
    cache = rvol.HistoryCache(clock=lambda: NOW)
    fetcher = Mock(return_value=history)
    value = rvol.get_evidence('TEST', current, decision_at=NOW,
        current_observed_at=NOW-timedelta(seconds=1),
        completed_before=NOW-timedelta(seconds=3), enabled=enabled,
        current_source=source('1m'), history_cache=cache, fetcher=fetcher)
    return value, fetcher


def test_only_matching_prefix_not_prior_afternoon_volume_is_denominator():
    current, history = independent_frames()
    after_prefix = history.index.time >= datetime(2026, 1, 1, 14, 10).time()
    history.loc[after_prefix, 'Volume'] = 5_000_000.
    result = evaluate(current, history)
    assert result['status'] == 'VERIFIED'
    assert result['current_cumulative_volume'] == 800.
    assert result['prior_cumulative_mean'] == 400.
    assert result['same_time_of_day_relative_volume'] == 2.


def test_unfinished_preopen_and_future_suffix_cannot_change_causal_measurement():
    current, history = independent_frames()
    before = evaluate(current, history)
    current.loc[pd.Timestamp('2026-10-21T13:29Z')] = [1, 0, 2, 1, -1, 4]
    current.loc[pd.Timestamp('2026-10-21T14:10Z')] = [1, 0, 2, 1, -1, 4]
    future = bars(pd.date_range('2026-10-22T13:30Z', periods=4, freq='5min'))
    future['Stock Splits'] = 4.
    after = evaluate(current, pd.concat([history, future]))
    assert after['status'] == before['status'] == 'VERIFIED'
    assert after['same_time_of_day_relative_volume'] == before['same_time_of_day_relative_volume']
    assert after['sourcehash'] == before['sourcehash']


def test_prior_session_must_have_been_complete_by_history_observation():
    current, history = independent_frames()
    result = evaluate(current, history,
                      history_observed_at=datetime(2026, 10, 20, 19, tzinfo=timezone.utc))
    assert result['status'] == 'UNKNOWN'
    assert result['same_time_of_day_relative_volume'] is None


def test_missing_calendar_does_not_authorize_a_history_acquisition(monkeypatch):
    current, history = independent_frames()
    monkeypatch.setattr(rvol, 'session_schedule',
                        Mock(side_effect=ValueError('UNKNOWN_CALENDAR_UNAVAILABLE')))
    result, fetcher = produce(current, history)
    assert result['status'] == 'UNKNOWN'
    fetcher.assert_not_called()


@pytest.mark.parametrize('enabled', ['false', 1])
def test_nonboolean_enable_is_not_acquisition_authority(enabled):
    current, history = independent_frames()
    result, fetcher = produce(current, history, enabled=enabled)
    assert result['status'] == 'UNKNOWN'
    fetcher.assert_not_called()


def test_cache_acquisition_must_not_launder_boolean_volume_into_a_number():
    current, history = independent_frames()
    history['Volume'] = history['Volume'].astype(object)
    history.loc[history.index[0], 'Volume'] = True
    assert evaluate(current, history)['status'] == 'UNKNOWN'
    through_cache, _ = produce(current, history)
    assert through_cache['status'] == 'UNKNOWN'
    assert through_cache['same_time_of_day_relative_volume'] is None


@pytest.mark.parametrize('offset', [1, 59])
def test_calendar_bounds_cannot_truncate_extra_seconds_into_a_valid_session(offset):
    schedule = pd.DataFrame(dict(open=[pd.Timestamp('2026-10-21T13:30Z')],
        close=[pd.Timestamp('2026-10-21T20:00Z')+pd.Timedelta(seconds=offset)]),
        index=pd.DatetimeIndex(['2026-10-21']))
    schedule.attrs.update(calendar_id='XNYS', calendar_version='synthetic-invalid-boundary')
    with pytest.raises(ValueError):
        rvol.session_bounds('2026-10-21', schedule=schedule)


def confirmed_vcp():
    # Reuse only the owner's invented daily candles/witness builder. The real
    # setup and confirmation functions must actually produce DETECTED first.
    import entry_intraday as intraday
    from test_entry_intraday import prior_case, witness_for, DECISION, OBSERVED
    frame, context = prior_case('VCP_BASE_CONTRACTION')
    setup = intraday.prepare_setups(frame, decision_at=DECISION,
        source_observed_at=OBSERVED, enabled_ids=['VCP_BASE_CONTRACTION'],
        context=context)['VCP_BASE_CONTRACTION']
    evidence, price, quote_at = witness_for(setup)
    record = intraday.confirm_setup(setup, evidence, price=price,
                                   quote_at=quote_at, decision_at=DECISION)
    assert record['state'] == 'DETECTED', record
    return intraday, setup, evidence, price, quote_at, DECISION, record


def test_rvol_prefix_cannot_have_been_observed_before_its_completed_end():
    intraday, setup, evidence, price, quote_at, decision, _ = confirmed_vcp()
    evidence['relative_volume']['source_times']['current_observed_at'] = (
        intraday._instant(evidence['bars'][-1]['end_at'])-timedelta(seconds=1)).isoformat()
    result = intraday.confirm_setup(setup, evidence, price=price,
                                   quote_at=quote_at, decision_at=decision)
    assert result['state'] != 'DETECTED'


@pytest.mark.parametrize('damage', ['invalid_ohlc', 'future_volume_clock', 'unknown_volume_version'])
def test_cold_reader_checks_proof_semantics_not_only_recomputed_digest(damage):
    intraday, _, _, _, _, decision, original = confirmed_vcp()
    record = copy.deepcopy(original)
    if damage == 'invalid_ohlc':
        bar = record['features']['intraday_confirmation']
        bar['low'] = bar['high']+1
    if damage == 'future_volume_clock':
        record['features']['relative_volume']['source_times']['current_observed_at'] = (
            decision+timedelta(seconds=1)).isoformat()
    if damage == 'unknown_volume_version':
        record['features']['relative_volume']['version'] = 'unsupported_rvol_contract'
    record['sourcehash'] = intraday._hash(dict(
        daily=record['features']['daily_sourcehash'],
        confirmation=record['features']['intraday_confirmation'],
        volume=record['features']['relative_volume'],
        session=record['features']['regular_session']))
    record['evidence_ids'] = [intraday._hash({k: record[k] for k in
        ('version', 'strategy_id', 'sourcehash', 'config', 'features', 'trigger')})]
    with pytest.raises(ValueError):
        intraday.validate_record(record)


def test_valid_legacy_baseline_without_audit_clock_is_not_anded_with_pending_setup():
    import entry_discovery as discovery
    import stock_scanner as scanner
    from test_entry_intraday import prior_case, DECISION
    long_frame, context = prior_case('VCP_BASE_CONTRACTION')
    baseline_frame = long_frame.copy(deep=True)
    baseline_frame.attrs.clear()
    # Common liquidity/ATR remains genuine. Only the original Baseline input
    # has these wider invented candles; the qualified long setup is untouched.
    baseline_frame['High'] += .65
    baseline_frame['Low'] -= .65
    baseline_frame['Volume'] *= 2
    cfg = scanner.settings() | {'entry_strategy_ids': ['VCP_BASE_CONTRACTION'],
                                'independent_intraday_enabled': True}
    common = scanner.analyze_history('TEST', 'Synthetic', baseline_frame, cfg,
                                     baseline_filter=False, decision_at=DECISION)
    assert common is not None
    baseline = dict(common, technical_direction='BUY', technical_score=7,
                    history_fetched_at=None)
    context['by_ticker'] = {'TEST': {'history_frame': long_frame}}
    candidates, observations = discovery.discover_candidates(
        {'TEST': baseline_frame}, {'TEST': {'company': 'Synthetic'}}, cfg,
        decision_at=DECISION, context=context, baseline_detector=lambda *a: baseline)
    assert len(candidates) == 1, observations
    assert 'BASELINE' in discovery.strategy_ids(candidates[0])
    # No fabricated audit clock, and missing optional intraday evidence cannot
    # erase the independently valid legacy alternative.
    result = discovery.confirm_intraday_candidate(candidates[0], {}, price=100.,
        quote_at=DECISION.isoformat(), decision_at=DECISION)
    assert 'BASELINE' in discovery.strategy_ids(result)
    assert result.get('entry_discovery') is None


def test_cold_valid_record_does_not_require_current_calendar_installation(monkeypatch):
    intraday, _, _, _, _, _, record = confirmed_vcp()
    monkeypatch.setattr(rvol, 'session_bounds',
                        Mock(side_effect=ValueError('calendar unavailable after creation')))
    assert intraday.validate_record(record) == record


def test_scan_acquisition_budget_is_shared_across_repeated_and_post_ai_quotes(monkeypatch):
    import stock_scanner as scanner
    from review_evidence import ObservedQuote
    loaded, acquired = set(), []
    def measured(ticker, frame, *, acquire, **kwargs):
        if acquire:
            acquired.append(ticker)
            loaded.add(ticker)
        return ({'status': 'VERIFIED', 'reason': None,
                 'same_time_of_day_relative_volume': .5}
                if ticker in loaded else rvol.unknown('UNKNOWN_HISTORY_CACHE_MISS'))
    monkeypatch.setattr(rvol, 'get_evidence', measured)
    collector = scanner._ScanVolumeEvidence(enabled=True, fetcher=Mock())
    def quote():
        return ObservedQuote(100., NOW.isoformat(), {'status': 'SYNTHETIC'},
            volume_frame=independent_frames()[0], source_observed_at=NOW,
            completed_before=NOW, volume_source=source('1m'))
    for ticker in ('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'A', 'B'):
        collector.attach(ticker, quote())
    assert acquired == ['A', 'B', 'C', 'D', 'E', 'F']
    assert len(collector.acquired) == 6


def test_volume_collector_default_off_preserves_quote_without_helper_call(monkeypatch):
    import stock_scanner as scanner
    from review_evidence import ObservedQuote
    helper = Mock(side_effect=AssertionError('disabled collector called helper'))
    monkeypatch.setattr(rvol, 'get_evidence', helper)
    quote = ObservedQuote(100., NOW.isoformat(), {'status': 'UNCHANGED'})
    assert scanner._ScanVolumeEvidence().attach('TEST', quote) is quote
    assert quote.evidence == {'status': 'UNCHANGED'}
    helper.assert_not_called()


def test_actual_input_capture_cannot_copy_credential_patterns_from_allowed_text():
    import decision_input_facts as facts
    marker = 'Bearer syntheticcredential_not_a_real_token_0123456789'
    payload = {'candidate': {'ticker': 'TEST'}, 'recent_news': [
        {'title': marker, 'publisher': 'ordinary source',
         'published_at': '2026-10-21T13:00:00Z', 'relevance': .9}]}
    captured = facts.capture(payload, json.dumps(payload), observed_at=NOW.isoformat())
    assert marker not in json.dumps(captured)
    assert len(captured['initial_user_content_utf8_sha256']) == 64


def test_capture_source_identity_does_not_equate_json_true_with_number_one():
    import decision_input_facts as facts
    payload = {'candidate': {'price': True}}
    with pytest.raises(ValueError):
        facts.capture(payload, '{"candidate":{"price":1}}', observed_at=NOW.isoformat())


def test_stored_input_validator_does_not_skip_privacy_check_on_context_version():
    import decision_input_facts as facts
    value = facts.capture({'candidate': {'ticker': 'TEST'}},
        '{"candidate":{"ticker":"TEST"}}', observed_at=NOW.isoformat())
    value['facts']['context_version'] = 'Bearer syntheticcredential_not_real_0123456789'
    value['sanitized_projection_sha256'] = facts.digest(value['facts'])
    with pytest.raises(ValueError):
        facts.validate(value)


def test_oversized_input_is_refused_before_json_parser(monkeypatch):
    import decision_input_facts as facts
    parser = Mock(side_effect=AssertionError('oversized input reached JSON parser'))
    monkeypatch.setattr(facts.json, 'loads', parser)
    with pytest.raises(ValueError):
        facts.capture({}, ' '*262145, observed_at=NOW.isoformat())
    parser.assert_not_called()


@pytest.mark.parametrize('damage', ['ratio', 'boolean_count', 'future_clock', 'wrong_end', 'source_basis'])
def test_frozen_public_rvol_never_promotes_inconsistent_saved_measurement(damage):
    current, history = independent_frames()
    measurement = evaluate(current, history)
    assert measurement['status'] == 'VERIFIED'
    end = measurement['as_of']
    assert rvol.public_evidence(measurement, decision_at=NOW,
                                completed_through=end)['status'] == 'VERIFIED'
    if damage == 'ratio':
        measurement['same_time_of_day_relative_volume'] += .01
    elif damage == 'boolean_count':
        measurement['prior_session_count'] = True
    elif damage == 'future_clock':
        measurement['source_times']['history_observed_at'] = (NOW+timedelta(seconds=1)).isoformat()
    elif damage == 'wrong_end':
        measurement['completed_through'] = (NOW-timedelta(minutes=5)).isoformat()
    else:
        measurement['history_source']['auto_adjust'] = 1
    saved = rvol.public_evidence(measurement, decision_at=NOW, completed_through=end)
    assert saved['status'] == 'UNKNOWN'
    assert saved['same_time_of_day_relative_volume'] is None
