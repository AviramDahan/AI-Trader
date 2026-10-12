"""Frozen-clock synthetic evidence; no live providers, paid models or orders."""
import copy
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pandas as pd
import pytest

import stock_scanner as scanner
from test_signal_inputs import clock, db

def candidate():
    return dict(ticker='TEST',company='Synthetic',technical_direction='BUY',entry=110,
        quote_at='2026-10-12T14:09:00Z',daily_reference_close=105,
        daily_reference_as_of='2026-10-09',price_as_of='2026-10-09',
        volume_ratio=.61,rsi14=68,ema20=102,ema50=99,atr=2)

def held():
    return dict(action='HOLD',confidence=.84,news_sentiment=.2,news_relevance=.8,
                time_horizon='1-4 weeks',reason='Synthetic HOLD remains valid.')

def reviewed(monkeypatch,clock,c=None):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    transport=Mock(return_value=held())
    monkeypatch.setattr(scanner.final_ai,'review',transport)
    row=c or candidate(); original=copy.deepcopy(row)
    result=scanner.ai_review(row,[],{})
    assert result['action']=='HOLD' and row==original and transport.call_count==1
    return json.loads(transport.call_args.args[0][1]['content']),transport

def test_daily_volume_is_not_a_current_breakout_volume_field(monkeypatch,clock):
    payload,_=reviewed(monkeypatch,clock)
    assert 'volume_ratio' not in payload['candidate']
    daily=payload['review_evidence_context']['completed_daily']
    assert daily['metrics']['volume_ratio']==.61
    assert daily['as_of']=='2026-10-09'
    assert daily['current_session_volume_available'] is False

def test_current_entry_has_its_own_time_not_the_previous_daily_date(monkeypatch,clock):
    payload,_=reviewed(monkeypatch,clock)
    assert 'price_as_of' not in payload['candidate']
    context=payload['review_evidence_context']
    assert context['entry_quote']['as_of']=='2026-10-12T14:09:00+00:00'
    assert context['completed_daily']['coverage']=='LATEST_COMPLETED_SESSION'
    assert context['completed_daily']['expected_session']=='2026-10-09'
    assert context['intraday']['status']=='UNKNOWN_NO_OBSERVATION'

def minutes(day='2026-10-12',price=110):
    idx=pd.date_range(day+'T13:30:00Z',day+'T14:12:00Z',freq='min')
    return pd.DataFrame(dict(Open=price,High=price+1,Low=price-1,Close=price,Volume=10),index=idx)

NOW=datetime(2026,10,12,14,10,37,tzinfo=timezone.utc)

def test_uses_six_complete_bars_and_excludes_unfinished_and_future_minutes():
    from review_evidence import completed_observation
    f=minutes();f.loc[f.index>=pd.Timestamp('2026-10-12T14:10:00Z'),'High']=9999
    result=completed_observation(f,NOW)
    assert result['status']=='COMPLETED_BARS' and result['fresh']
    assert len(result['bars'])==6 and result['complete_window']
    assert result['bars'][-1]==dict(start_at='2026-10-12T14:05:00+00:00',
        end_at='2026-10-12T14:10:00+00:00',open=110.,high=111.,low=109.,close=110.,volume=50.)
    assert result['same_time_of_day_relative_volume'] is None

@pytest.mark.parametrize('damage',['missing_minute','nan','negative_volume','invalid_ohlc'])
def test_missing_or_invalid_minute_is_not_a_complete_bar(damage):
    from review_evidence import completed_observation
    f=minutes();at=pd.Timestamp('2026-10-12T14:07:00Z')
    if damage=='missing_minute':f=f.drop(at)
    if damage=='nan':f.loc[at,'Open']=float('nan')
    if damage=='negative_volume':f.loc[at,'Volume']=-1
    if damage=='invalid_ohlc':f.loc[at,'Low']=115
    result=completed_observation(f,NOW)
    assert result['status']=='COMPLETED_BARS_WITH_GAPS'
    assert result['gap_buckets']==1 and not result['complete_window']
    assert len(result['bars'])==5
    assert all(b['start_at']!='2026-10-12T14:05:00+00:00' for b in result['bars'])

@pytest.mark.parametrize('damage',['naive','duplicates','missing_volume','previous_session','weekend','oversize'])
def test_unsupported_data_is_unknown_not_confirmation(damage):
    from review_evidence import completed_observation
    f=minutes();at=NOW
    if damage=='naive':f.index=f.index.tz_localize(None)
    if damage=='duplicates':f=pd.concat([f,f.iloc[-1:]])
    if damage=='missing_volume':f=f.drop(columns=['Volume'])
    if damage=='previous_session':f.index=f.index-pd.Timedelta(days=3)
    if damage=='weekend':at=datetime(2026,10,10,14,10,37,tzinfo=timezone.utc)
    if damage=='oversize':f=pd.concat([f]*15)
    result=completed_observation(f,at)
    assert result['bars']==[] and not result['fresh'] and result['status'].startswith('UNKNOWN_')

def test_opening_minutes_and_zero_volume_do_not_invent_prior_bars():
    from review_evidence import completed_observation
    f=minutes();f['Volume']=0
    result=completed_observation(f,datetime(2026,10,12,13,32,tzinfo=timezone.utc))
    assert result['bars']==[]
    result=completed_observation(f,datetime(2026,10,12,13,35,tzinfo=timezone.utc))
    assert len(result['bars'])==1 and result['bars'][0]['volume']==0
    assert result['same_time_of_day_relative_volume'] is None

def test_existing_quote_signature_and_one_provider_request(monkeypatch,clock):
    from review_evidence import ObservedQuote
    clock.instant=NOW
    ticker=Mock(history=Mock(return_value=minutes().loc[:pd.Timestamp('2026-10-12T14:10:00Z')]))
    factory=Mock(return_value=ticker);monkeypatch.setattr(scanner.yf,'Ticker',factory)
    quote=scanner.current_intraday_quote('TEST')
    assert isinstance(quote,ObservedQuote) and quote==(110.,'2026-10-12T14:10:00+00:00')
    assert len(quote.evidence['bars'])==6
    factory.assert_called_once_with('TEST');ticker.history.assert_called_once()
    assert ticker.history.call_args.kwargs['interval']=='1m'

def test_a_close_only_quote_keeps_existing_quote_gate_but_evidence_unknown(monkeypatch,clock):
    clock.instant=NOW
    ticker=Mock(history=Mock(return_value=minutes().loc[:pd.Timestamp('2026-10-12T14:10:00Z'),['Close']]))
    monkeypatch.setattr(scanner.yf,'Ticker',Mock(return_value=ticker))
    quote=scanner.current_intraday_quote('TEST')
    assert quote[0]==110 and quote.evidence['status']=='UNKNOWN_MISSING_OHLCV'

def test_capture_time_cannot_cross_boundary_and_complete_a_forming_bar(monkeypatch):
    before=datetime(2026,10,12,14,4,59,900000,tzinfo=timezone.utc)
    after=datetime(2026,10,12,14,5,0,100000,tzinfo=timezone.utc)
    timer=Mock(now=Mock(side_effect=[before,after]));monkeypatch.setattr(scanner,'datetime',timer)
    f=minutes().loc[:pd.Timestamp('2026-10-12T14:04:00Z')]
    monkeypatch.setattr(scanner.yf,'Ticker',Mock(return_value=Mock(history=Mock(return_value=f))))
    quote=scanner.current_intraday_quote('TEST')
    assert quote.evidence['latest_completed_at']=='2026-10-12T14:00:00+00:00'
    assert quote.evidence['observed_at']==after.isoformat()
    assert quote.evidence['completed_through']==before.isoformat()
    assert timer.now.call_count==2

@pytest.mark.parametrize('damage',['stale','future','zero','nan'])
def test_context_does_not_relax_the_existing_quote_gate(monkeypatch,clock,damage):
    clock.instant=NOW
    f=minutes().loc[:pd.Timestamp('2026-10-12T14:10:00Z')]
    if damage=='stale':f.index-=pd.Timedelta(hours=1)
    if damage=='future':f.index+=pd.Timedelta(minutes=2)
    if damage=='zero':f['Close']=0
    if damage=='nan':f['Close']=float('nan')
    monkeypatch.setattr(scanner.yf,'Ticker',Mock(return_value=Mock(history=Mock(return_value=f))))
    assert scanner.current_intraday_quote('TEST') is None

def test_actual_completed_price_action_is_supplied_without_auto_buy(monkeypatch,clock):
    from review_evidence import completed_observation
    c=candidate();c['_intraday_evidence']=completed_observation(minutes(),NOW)
    c['validated_target_plan']=dict(policy_version='single_breakout_v1',completed_high=108,
                                  completed_high_sessions=20,target_kind='projected_2r_not_confirmed_resistance')
    clock.instant=NOW
    transport=Mock(return_value=held());monkeypatch.setattr(scanner.final_ai,'review',transport)
    assert scanner.ai_review(c,[],{})['action']=='HOLD'
    payload=json.loads(transport.call_args.args[0][1]['content'])
    proof=payload['review_evidence_context']
    assert all(b['close_above_completed_20d_high'] for b in proof['intraday']['bars'])
    assert proof['target_policy']['target_kind']=='projected_2r_not_confirmed_resistance'
    assert '_intraday_evidence' not in payload['candidate']
    assert 'NOT current-session breakout volume' in transport.call_args.args[0][0]['content']

@pytest.mark.parametrize('damage',['future','duplicate','future_observation','previous_day','stale'])
def test_context_does_not_relabel_unavailable_evidence_as_current(damage):
    from review_evidence import completed_observation,context
    c=candidate();c['_intraday_evidence']=completed_observation(minutes(),NOW)
    at=NOW
    if damage=='future':c['_intraday_evidence']['bars'][-1]['end_at']='2026-10-12T15:00:00Z'
    if damage=='duplicate':c['_intraday_evidence']['bars'].append(c['_intraday_evidence']['bars'][-1])
    if damage=='future_observation':c['_intraday_evidence']['observed_at']='2026-10-12T14:11:00Z'
    if damage=='previous_day':at=datetime(2026,10,13,14,10,37,tzinfo=timezone.utc)
    if damage=='stale':at=datetime(2026,10,12,14,25,tzinfo=timezone.utc)
    proof=context(c,at,'2026-10-09')['intraday']
    assert not proof['fresh']
    if damage!='stale':assert proof['bars']==[] and proof['status'].startswith('UNKNOWN_')
    else:assert proof['status']=='STALE_COMPLETED_BARS'

@pytest.mark.parametrize('action',['BUY','HOLD','ERROR'])
def test_actual_scanner_persists_input_before_ai_and_preserves_lifecycle(db,clock,monkeypatch,action):
    from review_evidence import ObservedQuote,completed_observation
    from test_signal_admission_chain import prepare,rows
    from test_single_target_v2 import zone
    import scanner_engine as engine
    c,_,_=prepare(monkeypatch,clock)
    c.update(price_zones=[zone(98,98.4)],recent_high_20d=99,volume_ratio=.61)
    clock.instant=datetime(2026,10,6,14,0,37,tzinfo=timezone.utc)
    for flag in ('STOCK_SCANNER_SINGLE_BREAKOUT_ENABLED','STOCK_SCANNER_FULL_BAR_ENTRY_ENABLED'):
        monkeypatch.setenv(flag,'true')
    monkeypatch.setattr(scanner,'current_intraday_quote',lambda *a:ObservedQuote(100,clock.instant.isoformat(),
        completed_observation(minutes('2026-10-06',100),clock.instant)))
    monkeypatch.setattr(scanner,'ai_review',scanner_review)
    def model(messages,validator):
        payload=json.loads(messages[1]['content'])
        check=json.loads(rows("SELECT metrics_json FROM scanner_candidates WHERE stage='target_check'")[0]['metrics_json'])
        assert check['review_evidence_context']==payload['review_evidence_context']
        assert check['review_evidence_context']['completed_daily']['metrics']['volume_ratio']==.61
        assert not rows('SELECT id FROM scanner_orders')
        if action=='ERROR':
            from ai_budget import BudgetUnavailable
            raise BudgetUnavailable('synthetic verification failure')
        return validator(dict(held(),action=action,confidence=.91))
    transport=Mock(side_effect=model);monkeypatch.setattr(scanner.final_ai,'review',transport)
    result=scanner.run_scan();assert transport.call_count==1
    assert result['signals_published']==int(action=='BUY')
    if action!='BUY':
        assert not rows('SELECT id FROM scanner_orders') and not rows('SELECT id FROM scanner_trades')
        return
    assert rows('SELECT status FROM scanner_orders')==[{'status':'pending'}]
    assert not rows('SELECT id FROM scanner_trades')
    clock.instant=datetime(2026,10,6,14,10,tzinfo=timezone.utc)
    entry=dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100)
    engine.process_bar('TEST',entry)
    assert rows('SELECT status FROM scanner_orders')==[{'status':'filled'}]
    clock.instant=datetime(2026,10,6,14,15,tzinfo=timezone.utc)
    exit_bar=dict(at='2026-10-06T14:10:00Z',open=104.5,high=105,low=104,close=104.5)
    engine.process_bar('TEST',exit_bar);engine.initialize_runtime()
    engine.process_bar('TEST',entry);engine.process_bar('TEST',exit_bar)
    assert len(rows('SELECT id FROM scanner_orders'))==1 and len(rows('SELECT id FROM scanner_fills'))==2
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

scanner_review=scanner.ai_review

def test_optional_evidence_capture_failure_never_changes_trading(monkeypatch):
    import target_evidence
    original={'phase':'pre_ai','outcome':'PASS'}
    trace={'target_checks':{'pre_ai':copy.deepcopy(original)}}
    assert target_evidence.attach_review_context(trace,{'version':'x','oversize':'x'*9000}) is False
    assert trace['target_checks']['pre_ai']==original
    monkeypatch.setattr(target_evidence,'MAX_BYTES',1)
    assert target_evidence.attach_review_context(trace,{'version':'x'}) is False
    assert trace['target_checks']['pre_ai']==original
