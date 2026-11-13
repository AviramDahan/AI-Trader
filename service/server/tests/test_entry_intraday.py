"""Invented causal market inputs only; no live feed, model or performance proof."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys

import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import entry_discovery as discovery
import entry_strategies as daily
from scanner_engine import market_session_state
from test_entry_strategies import fixture_case, ET

UTC = timezone.utc
DECISION = datetime(2026, 10, 5, 14, 0, 37, tzinfo=UTC)
OBSERVED = DECISION - timedelta(seconds=60)
IDS = tuple(s for s in daily.STRATEGY_IDS if s != 'PEAD')


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Intraday unit tests forbid external IO')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)


def prior_case(strategy_id):
    """Remove the old fixture's trigger day: only prior completed daily base remains."""
    frame, context, _, _ = fixture_case(strategy_id)
    frame, context = frame.iloc[:-1].copy(deep=True), copy.deepcopy(context)
    # Keep the full253-bar warmup, without manufacturing today's daily candle.
    previous = frame.index[0].to_pydatetime() - timedelta(days=1)
    while not market_session_state(previous.replace(tzinfo=ET, hour=12))['is_trading_day']:
        previous -= timedelta(days=1)
    prefix = frame.iloc[:1].copy()
    prefix.index = pd.DatetimeIndex([previous])
    frame = pd.concat([prefix, frame])
    # Preserve the unchanged common ATR/liquidity minimums in composition tests.
    # These are synthetic source candles, not modified application thresholds.
    frame['High'] += .65
    frame['Low'] -= .65
    frame['Volume'] *= 2
    if strategy_id == 'TREND_PULLBACK_RECLAIM':
        # A shallower final pullback avoids an intentional opposing Baseline
        # SELL, while still below frozen EMA20 and before today's reclaim.
        frame.iloc[-1] = [99.95,100.85,99.15,100,2000000]
    frame.attrs['history_fetched_at'] = OBSERVED.timestamp()
    context.update(expected_session='2026-10-02', price_basis='yahoo_auto_adjusted_v1', symbol='FIX')
    if 'benchmark_frame' in context:
        benchmark = context['benchmark_frame'].iloc[:-1].copy()
        context.update(benchmark_frame=benchmark, benchmark_observed_at=OBSERVED,
                       benchmark_price_basis='yahoo_auto_adjusted_v1')
    return frame, context


@pytest.mark.parametrize('strategy_id', IDS)
def test_completed_intraday_can_confirm_without_todays_completed_daily_trigger(strategy_id):
    frame, context = prior_case(strategy_id)
    old = daily.detect_all(frame, decision_at=DECISION, source_observed_at=OBSERVED,
                          enabled_ids=[strategy_id], context=context)[strategy_id]
    assert old['state'] != 'DETECTED', old
    assert callable(getattr(discovery, 'confirm_intraday_candidate', None)), \
        'Missing separately versioned completed-intraday confirmation API'
    import entry_intraday as intraday
    setups = intraday.prepare_setups(frame, decision_at=DECISION,
        source_observed_at=OBSERVED, enabled_ids=[strategy_id], context=context)
    setup = setups[strategy_id]
    assert setup['state'] == 'FORMING', setup
    evidence, price, quote_at = witness_for(setup)
    result = intraday.confirm_setup(setup, evidence, price=price, quote_at=quote_at,
                                    decision_at=DECISION)
    assert result['state'] == 'DETECTED', result
    assert result['version'] == intraday.DETECTOR_VERSION
    assert result['source_times']['source_data_at'] == '2026-10-02T20:05:00+00:00'
    assert result['trigger']['confirmed_at'] == '2026-10-05T14:00:00+00:00'
    assert result['entry_reference']['kind'] == 'COMPLETED_REGULAR_5M_CLOSE_NOT_EXECUTABLE'
    assert frame.index[-1].date().isoformat() == '2026-10-02'


def witness_for(setup):
    import intraday_volume as rvol
    from test_intraday_volume import fixtures, source
    level = setup['trigger']['level']
    end = DECISION.replace(second=0, microsecond=0)
    bar = dict(start_at=(end-timedelta(minutes=5)).isoformat(), end_at=end.isoformat(),
               open=level*.999, high=level*1.012, low=level*.998,
               close=level*1.01, volume=500000.0)
    observation = DECISION-timedelta(seconds=2)
    current,history=fixtures(now=observation)
    elapsed=int((end-rvol.session_bounds(DECISION.astimezone(ET).date())['open']).total_seconds()/60)
    current['Volume']=1000000./elapsed
    history['Volume']=500000./(elapsed//5)
    measurement=rvol.evaluate(current,history,decision_at=observation,
        current_observed_at=observation,history_observed_at=OBSERVED,completed_before=end,
        current_source=source('1m'),history_source=source('5m'))
    assert measurement['status']=='VERIFIED',measurement
    evidence = dict(status='COMPLETED_BARS', bars=[bar], observed_at=observation.isoformat(),
        completed_through=end.isoformat(), complete_window=True, gap_buckets=0,
        price_basis='yahoo_auto_adjusted_v1', relative_volume=measurement)
    return evidence, level*1.011, end.isoformat()


def confirmed_case(strategy_id='VCP_BASE_CONTRACTION'):
    import entry_intraday as intraday
    frame, context=prior_case(strategy_id)
    setup=intraday.prepare_setups(frame,decision_at=DECISION,source_observed_at=OBSERVED,
        enabled_ids=[strategy_id],context=context)[strategy_id]
    assert setup['state']=='FORMING',setup
    evidence,price,quote=witness_for(setup)
    record=intraday.confirm_setup(setup,evidence,price=price,quote_at=quote,decision_at=DECISION)
    assert record['state']=='DETECTED',record
    return setup,evidence,price,quote,record


@pytest.mark.parametrize('sid',IDS)
def test_each_intraday_route_composes_after_actual_default_baseline_miss(sid):
    import stock_scanner as scanner
    import entry_intraday as intraday
    frame,context=prior_case(sid)
    cfg=scanner.settings()|{'entry_strategy_ids':[sid],'independent_intraday_enabled':True}
    cfg['min_technical_score']=5
    assert scanner.analyze_history('FIX','Synthetic',frame,cfg,decision_at=DECISION) is None
    assert scanner.analyze_history('FIX','Synthetic',frame,cfg,baseline_filter=False,decision_at=DECISION)
    candidates,observations=discovery.discover_candidates({'FIX':frame},
        {'FIX':{'company':'Synthetic'}},cfg,decision_at=DECISION,context=context)
    assert len(candidates)==1,observations
    candidate=candidates[0]
    assert candidate['_intraday_provisional'] is True
    assert 'entry_discovery' not in candidate and discovery.strategy_ids(candidate)==[]
    assert observations[0]['candidate_strategy_ids']==[]
    assert observations[0]['pending_intraday_setup_ids']==[sid]
    with pytest.raises(ValueError,match='intraday_confirmation_not_valid'):
        discovery.validate_candidate_trigger(candidate,1,DECISION,DECISION)
    evidence,price,quote=witness_for(candidate['_intraday_setups'][sid])
    assert discovery.needs_intraday_volume(candidate,evidence,price=price,quote_at=quote,decision_at=DECISION)
    actual=discovery.confirm_intraday_candidate(candidate,evidence,price=price,quote_at=quote,decision_at=DECISION)
    assert actual['strategy_ids']==[sid]
    assert actual['entry_discovery']['version']==discovery.INTRADAY_VERSION
    assert '_intraday_setups' not in actual and '_intraday_provisional' not in actual
    assert discovery.validate_attribution(actual['entry_discovery'])==actual['entry_discovery']
    assert discovery.validate_candidate_trigger(actual,price,quote,DECISION)


def test_off_never_prepares_intraday_or_calls_calendar(monkeypatch):
    import entry_intraday as intraday
    import intraday_volume
    import stock_scanner as scanner
    def forbidden(*a,**k):raise AssertionError('OFF invoked intraday work')
    monkeypatch.setattr(intraday,'prepare_setups',forbidden)
    monkeypatch.setattr(intraday_volume,'session_bounds',forbidden)
    frame,context=prior_case('VCP_BASE_CONTRACTION')
    cfg=scanner.settings()|{'entry_strategy_ids':['VCP_BASE_CONTRACTION'],'independent_intraday_enabled':False}
    candidates,observations=discovery.discover_candidates({'FIX':frame},{'FIX':{'company':'Synthetic'}},
        cfg,decision_at=DECISION,context=context)
    assert not candidates
    assert 'intraday_setup_results' not in observations[0]


@pytest.mark.parametrize('sid',IDS)
@pytest.mark.parametrize('bad',('missing','unknown','old_clock','low_ratio'))
def test_volume_missing_or_invalid_never_promotes(sid,bad):
    import entry_intraday as intraday
    setup,evidence,price,quote,_=confirmed_case(sid)
    if bad=='missing':evidence.pop('relative_volume')
    elif bad=='unknown':evidence['relative_volume']['status']='UNKNOWN'
    elif bad=='old_clock':
        evidence['relative_volume']['source_times']['current_observed_at']=(DECISION-timedelta(minutes=1)).isoformat()
    else:
        evidence['relative_volume']['same_time_of_day_relative_volume']=.5
        evidence['relative_volume']['prior_cumulative_mean']=2000000
    assert intraday.confirm_setup(setup,evidence,price=price,quote_at=quote,decision_at=DECISION)['state']!='DETECTED'


@pytest.mark.parametrize('bad',('future_observed','unfinished','gap','prior_session','zero_length','bad_ohlc','wrong_basis'))
def test_invalid_or_incomplete_price_witness_never_promotes(bad):
    import entry_intraday as intraday
    setup,evidence,price,quote,_=confirmed_case()
    bar=evidence['bars'][-1]
    if bad=='future_observed':evidence['observed_at']=(DECISION+timedelta(seconds=1)).isoformat()
    elif bad=='unfinished':bar['end_at']=(DECISION+timedelta(minutes=1)).isoformat()
    elif bad=='gap':evidence['complete_window']=False;evidence['gap_buckets']=1
    elif bad=='prior_session':
        bar['start_at']='2026-10-02T13:55:00+00:00';bar['end_at']='2026-10-02T14:00:00+00:00'
    elif bad=='zero_length':bar['start_at']=bar['end_at']
    elif bad=='bad_ohlc':bar['low']=bar['high']+1
    else:evidence['price_basis']='unadjusted'
    assert not intraday.eligible_for_volume(setup,evidence,price=price,quote_at=quote,decision_at=DECISION)
    assert intraday.confirm_setup(setup,evidence,price=price,quote_at=quote,decision_at=DECISION)['state']!='DETECTED'


def test_future_unfinished_daily_rows_cannot_change_prior_setup():
    import entry_intraday as intraday
    frame,context=prior_case('VCP_BASE_CONTRACTION')
    expected=intraday.prepare_setups(frame,decision_at=DECISION,source_observed_at=OBSERVED,
        enabled_ids=['VCP_BASE_CONTRACTION'],context=context)
    future=pd.DataFrame([dict(Open=-1,High=-1,Low=-1,Close=-1,Volume=-1)],index=[pd.Timestamp('2026-10-05')])
    combined=pd.concat([frame,future]);combined.attrs=frame.attrs.copy()
    assert intraday.prepare_setups(combined,decision_at=DECISION,source_observed_at=OBSERVED,
        enabled_ids=['VCP_BASE_CONTRACTION'],context=context)==expected


def test_chase_and_confirmation_expiry_do_not_move_frozen_levels():
    import entry_intraday as intraday
    setup,evidence,price,quote,record=confirmed_case()
    original=copy.deepcopy(record)
    rejected=intraday.confirm_setup(setup,evidence,price=setup['trigger']['max_entry_price']+.01,
                                    quote_at=quote,decision_at=DECISION)
    assert rejected['state']!='DETECTED'
    with pytest.raises(ValueError,match='quote_not_fresh'):
        daily.validate_trigger(record,price,DECISION+timedelta(minutes=13),DECISION+timedelta(minutes=13))
    assert record==original


def test_cold_reader_survives_missing_calendar_but_new_creation_stays_unknown(monkeypatch):
    import entry_intraday as intraday
    import intraday_volume
    setup,evidence,price,quote,record=confirmed_case()
    def unavailable(*a,**k):raise ImportError('isolated absent calendar')
    monkeypatch.setattr(intraday_volume,'session_bounds',unavailable)
    assert intraday.validate_record(record)==record
    assert daily.validate_trigger(record,price,quote,DECISION)
    assert intraday.confirm_setup(setup,evidence,price=price,quote_at=quote,decision_at=DECISION)['state']=='UNKNOWN'


def new_contract():
    import entry_strategy_execution as execution
    import entry_window
    import single_target_policy
    _,_,price,quote,record=confirmed_case()
    package=discovery.attribution([record],DECISION)
    until=(DECISION+timedelta(hours=24)).isoformat()
    window=entry_window.build(DECISION,until)
    saved=execution.build(package,created_at=DECISION,valid_until=until,limit_price=price,
        quote_at=quote,entry_execution=window)
    def zone(low,high):
        return dict(low=low,high=high,pivots=[dict(confirmed_at='2026-10-01T20:05:00+00:00')])
    plan=single_target_policy.build(price,1,[zone(price-3,price-2.8),zone(price+8,price+8.4)],
                                    '2026-10-02',DECISION.isoformat())
    contract=dict(entry_discovery=package,entry_strategy_execution=saved,target_plan=plan,
        execution_settings=dict(active_strategy='single',entry_order_type='limit',slippage_bps=0,
            commission_per_share=.005,minimum_commission=.25),entry_execution=window)
    order=dict(purpose='entry',side='buy',order_type='limit',limit_price=price,status='pending',
        created_at=DECISION.isoformat(),updated_at=DECISION.isoformat(),valid_until=until,
        plan_json=json.dumps(contract))
    return order,contract


def test_new_frozen_execution_reader_retry_restart_and_flag_off(monkeypatch):
    import entry_strategy_execution as execution
    import entry_discovery_capabilities as capabilities
    import intraday_volume
    order,contract=new_contract();saved=contract[execution.KEY]
    assert saved['version']==execution.INTRADAY_VERSION
    assert saved['valid_until']==(DECISION+timedelta(hours=24)).isoformat()
    support=saved['branches'][0]['support']
    with pytest.raises(ValueError,match='strategy_fill_below_support'):
        execution.validate_fill(saved,support)
    changed=execution.observe(order,contract,support,'2026-10-05T14:05:00+00:00',
        '2026-10-05T14:10:00+00:00','strategy_fill_below_support')
    retry_order=dict(order,updated_at='2026-10-05T14:10:00+00:00',plan_json=json.dumps(changed))
    assert execution.validate_order(retry_order,changed)
    frozen=json.loads(json.dumps(changed))
    monkeypatch.setenv('STOCK_SCANNER_INDEPENDENT_INTRADAY_ENABLED','false')
    monkeypatch.setattr(capabilities,'BUILD_ROLE','bridge')
    monkeypatch.setattr(intraday_volume,'session_bounds',lambda *a,**k:pytest.fail('cold calendar access'))
    assert execution.validate_order(retry_order,frozen)
    assert execution.validate_fill(saved,order['limit_price'])==['VCP_BASE_CONTRACTION']
    assert frozen['target_plan']==contract['target_plan']


def test_new_version_cannot_be_downgraded_to_daily_audit_or_execution():
    import entry_strategy_execution as execution
    order,contract=new_contract()
    wrong=copy.deepcopy(contract['entry_discovery']);wrong['version']=discovery.VERSION
    with pytest.raises(ValueError,match='invalid_attribution'):
        discovery.validate_attribution(wrong)
    wrong=copy.deepcopy(contract);wrong[execution.KEY]['version']=execution.VERSION
    with pytest.raises(ValueError,match='contract_invalid'):
        execution.validate_order(order,wrong)


@pytest.mark.parametrize('basis', [None, 'unadjusted', 'yahoo_auto_adjusted_v1'])
def test_loader_does_not_retroactively_stamp_old_cache_basis(monkeypatch,basis):
    import entry_strategy_inputs as inputs
    import entry_intraday as intraday
    import stock_scanner as scanner
    frame,_=prior_case('VCP_BASE_CONTRACTION')
    if basis is not None:frame.attrs['price_basis']=basis
    else:frame.attrs.pop('price_basis',None)
    monkeypatch.setattr(inputs,'load_long_histories',lambda *a,**k:({'FIX':frame},{'status':'ready'}))
    monkeypatch.setattr(scanner,'latest_completed_session',lambda *a:datetime(2026,10,2).date())
    cfg={'entry_strategy_ids':['VCP_BASE_CONTRACTION'],'independent_intraday_enabled':True}
    context=inputs.load_context(['FIX'],{}, {},cfg,decision_at=DECISION)
    assert 'price_basis' not in context
    assert context['by_ticker']['FIX']['price_basis']==basis
    result=intraday.prepare_setups(frame,decision_at=DECISION,source_observed_at=OBSERVED,
        enabled_ids=['VCP_BASE_CONTRACTION'],context=context|context['by_ticker']['FIX'])['VCP_BASE_CONTRACTION']
    if basis=='yahoo_auto_adjusted_v1':assert result['state']=='FORMING'
    else:
        assert result['state']=='UNKNOWN'
        assert result['reasons']==['intraday_price_basis_unknown']


def test_rs_requires_explicit_same_basis_benchmark_not_only_equity_stamp():
    import entry_intraday as intraday
    frame,context=prior_case('RELATIVE_STRENGTH_LEADER')
    context.pop('benchmark_price_basis')
    record=intraday.prepare_setups(frame,decision_at=DECISION,source_observed_at=OBSERVED,
        enabled_ids=['RELATIVE_STRENGTH_LEADER'],context=context)['RELATIVE_STRENGTH_LEADER']
    assert record['state']=='UNKNOWN'
    assert record['reasons']==['intraday_benchmark_price_basis_unknown']


def test_setup_from_an_earlier_session_cannot_be_reused_as_current_confirmation():
    import entry_intraday as intraday
    setup,evidence,price,quote,_=confirmed_case()
    setup['source_times']['decision_at']='2026-10-02T19:00:37+00:00'
    result=intraday.confirm_setup(setup,evidence,price=price,quote_at=quote,decision_at=DECISION)
    assert result['state']=='UNKNOWN'
    assert result['reasons']==['intraday_quote_not_fresh']


def test_failure_fingerprint_is_causal_prefix_and_projection_is_strictly_allowlisted():
    import entry_input_diagnostics as diagnostics
    frame,context=prior_case('VCP_BASE_CONTRACTION')
    frame.iloc[5,frame.columns.get_loc('Low')]=frame.iloc[5]['High']+1
    expected=daily.detect_all(frame,decision_at=DECISION,source_observed_at=OBSERVED,
        enabled_ids=['VCP_BASE_CONTRACTION'],context=context)['VCP_BASE_CONTRACTION']
    assert expected['state']=='UNKNOWN' and expected['reasons']==['invalid_ohlcv']
    metadata=expected['features']['input_failure']
    assert metadata['predicate']=='OHLC_ORDER' and metadata['consumed_rows']==6
    assert diagnostics.validate_metadata(metadata)==metadata
    changed=frame.copy(deep=True)
    changed.iloc[6:]=float('nan')
    actual=daily.detect_all(changed,decision_at=DECISION,source_observed_at=OBSERVED,
        enabled_ids=['VCP_BASE_CONTRACTION'],context=context)['VCP_BASE_CONTRACTION']
    assert actual==expected
    observation=dict(ticker='FIX',baseline_detected=False,common_reasons=[],candidate_strategy_ids=[],
        strategy_results={'VCP_BASE_CONTRACTION':expected})
    projected=discovery.observation_summary(observation)
    assert projected['strategy_results']['VCP_BASE_CONTRACTION']['features']=={'input_failure':metadata}
    bad=copy.deepcopy(observation)
    bad['strategy_results']['VCP_BASE_CONTRACTION']['features']['input_failure']['raw_secret']='must not persist'
    assert 'features' not in discovery.observation_summary(bad)['strategy_results']['VCP_BASE_CONTRACTION']


def temporal_price_case(now):
    """Re-date invented daily prices to actual prior calendar sessions only."""
    import entry_intraday as intraday
    import intraday_volume as rvol
    frame,context=prior_case('VCP_BASE_CONTRACTION')
    dates=[];probe=now.astimezone(ET).date()-timedelta(days=1)
    while len(dates)<len(frame):
        try:rvol.session_bounds(probe);dates.append(probe)
        except ValueError:pass
        probe-=timedelta(days=1)
    frame.index=pd.DatetimeIndex(sorted(dates))
    observed=now-timedelta(seconds=60)
    context['expected_session']=frame.index[-1].date().isoformat()
    frame.attrs['history_fetched_at']=observed.timestamp()
    setup=intraday.prepare_setups(frame,decision_at=now,source_observed_at=observed,
        enabled_ids=['VCP_BASE_CONTRACTION'],context=context)['VCP_BASE_CONTRACTION']
    assert setup['state']=='FORMING',setup
    level=setup['trigger']['level'];end=now.replace(second=0,microsecond=0)
    bar=dict(start_at=(end-timedelta(minutes=5)).isoformat(),end_at=end.isoformat(),
        open=level*.999,high=level*1.012,low=level*.998,close=level*1.01,volume=500000.)
    evidence=dict(bars=[bar],observed_at=(now-timedelta(seconds=1)).isoformat(),
        completed_through=end.isoformat(),complete_window=True,gap_buckets=0,
        price_basis=intraday.PRICE_BASIS)
    return setup,evidence,level*1.011,end.isoformat()


@pytest.mark.parametrize('now,price_ok', [
    (datetime(2026,11,27,17,55,37,tzinfo=UTC),True),  # real13:00ET half-day close
    (datetime(2026,11,27,18,0,37,tzinfo=UTC),False),
    (datetime(2026,11,3,15,0,37,tzinfo=UTC),True),   # EST, not a fixed UTC open
    (datetime(2026,11,26,15,0,37,tzinfo=UTC),False), # Thanksgiving
    (datetime(2026,11,28,15,0,37,tzinfo=UTC),False), # Saturday
])
def test_creation_obeys_actual_halfday_holiday_weekend_and_dst(now,price_ok):
    import entry_intraday as intraday
    setup,evidence,price,quote=temporal_price_case(now)
    assert intraday.eligible_for_volume(setup,evidence,price=price,quote_at=quote,decision_at=now) is price_ok
    # Price confirmation alone cannot invent the ten same-length RVOL sessions
    # which are normally unavailable in the bounded half-day history window.
    assert intraday.confirm_setup(setup,evidence,price=price,quote_at=quote,decision_at=now)['state']!='DETECTED'
