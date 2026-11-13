"""Synthetic RVOL evidence only; no provider, DB, AI, Telegram or trades."""
import copy
import socket
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import requests

import intraday_volume as rvol

UTC = timezone.utc
NOW = datetime(2026, 10, 21, 14, 10, 37, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('external IO forbidden in RVOL tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(requests.sessions.Session, 'request', denied)
    try:
        import psycopg
        monkeypatch.setattr(psycopg, 'connect', denied)
    except ImportError:
        pass


def source(interval):
    return dict(provider='yahoo', interval=interval, auto_adjust=True,
                actions=True, volume_basis='reported_shares_unscaled')


def frame(index, volume):
    return pd.DataFrame(dict(Open=100., High=101., Low=99., Close=100.,
                             Volume=volume, **{'Stock Splits': 0.}), index=index)


def fixtures(now=NOW, prior_count=10):
    day = now.astimezone(rvol.ET).date()
    bounds = rvol.session_bounds(day)
    current = frame(pd.date_range(bounds['open'], now.replace(second=0, microsecond=0),
                                  freq='min'), 20.)
    histories = []
    probe = day - timedelta(days=1)
    while len(histories) < prior_count:
        try:
            b = rvol.session_bounds(probe)
        except ValueError:
            probe -= timedelta(days=1)
            continue
        if b['duration_minutes'] == bounds['duration_minutes']:
            histories.append(frame(pd.date_range(b['open'], b['close'],
                                                 freq='5min', inclusive='left'), 50.))
        probe -= timedelta(days=1)
    return current, pd.concat(histories).sort_index()


def evaluate(current=None, history=None, now=NOW, **overrides):
    if current is None or history is None:
        c, h = fixtures(now)
        current = c if current is None else current
        history = h if history is None else history
    args = dict(decision_at=now, current_observed_at=now-timedelta(seconds=1),
                history_observed_at=now-timedelta(seconds=2),
                completed_before=now-timedelta(seconds=3),
                current_source=source('1m'), history_source=source('5m'))
    args.update(overrides)
    return rvol.evaluate(current, history, **args)


def test_missing_capability_is_reproduced_as_one_day_not_a_denominator():
    c, _ = fixtures()
    result = evaluate(c, c.iloc[:0])
    assert result['status'] == 'UNKNOWN'
    assert result['same_time_of_day_relative_volume'] is None


def test_legacy_healthy_one_day_bars_honestly_have_no_comparable_denominator():
    from review_evidence import completed_observation
    c,_=fixtures()
    legacy=completed_observation(c,NOW)
    assert len(legacy['bars'])==6 and legacy['fresh']
    assert legacy['same_time_of_day_relative_volume'] is None
    assert legacy['volume_comparison_status']=='UNAVAILABLE_NO_COMPARABLE_SESSION_HISTORY'


def test_actual_same_clock_cumulative_ratio_not_daily_or_last_bar_ratio():
    result = evaluate()
    assert result['status'] == 'VERIFIED'
    assert result['same_time_of_day_relative_volume'] == 2.
    assert result['current_cumulative_volume'] == 800.
    assert result['prior_cumulative_mean'] == 400.
    assert result['prior_session_count'] == 10
    assert result['as_of'] == '2026-10-21T14:10:00+00:00'
    assert result['elapsed_regular_minutes'] == 40
    assert len(result['sourcehash']) == 64


@pytest.mark.parametrize('damage', ['missing_current', 'missing_prior_prefix',
    'missing_prior_afternoon', 'duplicate_current', 'duplicate_prior',
    'negative_volume', 'nan_volume', 'bad_ohlc', 'missing_actions',
    'split_prior', 'split_current', 'naive', 'future_available'])
def test_bad_or_unknown_required_inputs_never_become_zero_or_one(damage):
    c, h = fixtures()
    if damage == 'missing_current': c = c.drop(c.index[5])
    if damage == 'missing_prior_prefix': h = h.drop(h.index[2])
    if damage == 'missing_prior_afternoon': h = h.drop(h.index[70])
    if damage == 'duplicate_current': c = pd.concat([c, c.iloc[2:3]])
    if damage == 'duplicate_prior': h = pd.concat([h, h.iloc[2:3]])
    if damage == 'negative_volume': c.loc[c.index[2], 'Volume'] = -1
    if damage == 'nan_volume': h.loc[h.index[2], 'Volume'] = float('nan')
    if damage == 'bad_ohlc': c.loc[c.index[2], 'Low'] = 102
    if damage == 'missing_actions': h = h.drop(columns=['Stock Splits'])
    if damage == 'split_prior': h.loc[h.index[2], 'Stock Splits'] = 2
    if damage == 'split_current': c.loc[c.index[2], 'Stock Splits'] = 2
    if damage == 'naive': h.index = h.index.tz_localize(None)
    if damage == 'future_available':
        c['available_at'] = NOW + timedelta(seconds=1)
    result = evaluate(c, h)
    assert result['status'] == 'UNKNOWN'
    assert result['same_time_of_day_relative_volume'] is None


def test_unknown_basis_is_not_proved_by_default_argument():
    assert evaluate(current_source=None)['status'] == 'UNKNOWN'
    wrong = dict(source('5m'), volume_basis='split_adjusted')
    assert evaluate(history_source=wrong)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('clock', ['decision_at','current_observed_at','history_observed_at','completed_before'])
def test_naive_or_future_observation_clocks_fail_closed(clock):
    value = NOW.replace(tzinfo=None) if clock == 'decision_at' else NOW+timedelta(minutes=1)
    result = evaluate(**{clock: value})
    assert result['status'] == 'UNKNOWN'


def test_known_zero_numerator_is_zero_but_zero_denominator_is_unknown():
    c, h = fixtures(); c['Volume'] = 0.
    assert evaluate(c,h)['same_time_of_day_relative_volume'] == 0.
    h['Volume'] = 0.
    assert evaluate(c,h)['status'] == 'UNKNOWN'


def test_no_lookahead_or_mutation_from_unfinished_and_future_suffix():
    c,h = fixtures(); original_c=c.copy(deep=True);original_h=h.copy(deep=True)
    first = evaluate(c,h)
    c.loc[c.index>=pd.Timestamp('2026-10-21T14:10:00Z'),'Volume']=1e12
    future=frame(pd.date_range('2026-10-22T13:30Z',periods=20,freq='5min'),1e12)
    second=evaluate(c,pd.concat([h,future]))
    assert second['same_time_of_day_relative_volume'] == first['same_time_of_day_relative_volume']
    assert second['sourcehash'] == first['sourcehash']
    pd.testing.assert_frame_equal(h,original_h)
    assert list(original_c.columns) == list(c.columns)


def test_less_than_ten_sessions_is_unknown_not_covered():
    c,h=fixtures(prior_count=9)
    result=evaluate(c,h)
    assert result['status']=='UNKNOWN'
    assert result['reason']=='UNKNOWN_INSUFFICIENT_COMPARABLE_SESSIONS'


def test_dst_uses_session_local_offset_not_a_fixed_utc_open():
    now=datetime(2026,11,3,15,10,37,tzinfo=UTC)
    result=evaluate(now=now)
    assert result['status']=='VERIFIED'
    assert result['elapsed_regular_minutes']==40
    assert result['same_time_of_day_relative_volume']==2.


def test_halfday_and_special_closure_are_calendar_facts_not_filled_bars():
    b=rvol.session_bounds('2026-11-27')
    assert b['duration_minutes']==210
    assert b['close'].hour==18
    with pytest.raises(ValueError):rvol.session_bounds('2025-01-09')
    now=datetime(2026,11,27,15,10,37,tzinfo=UTC)
    c=frame(pd.date_range(b['open'],now,freq='min'),20.)
    _,h=fixtures()
    assert evaluate(c,h,now=now)['status']=='UNKNOWN'


def test_default_disabled_producer_never_invokes_fetcher_or_writes_cache(tmp_path):
    calls=[]
    result=rvol.get_evidence('TEST',fixtures()[0],decision_at=NOW,
        current_observed_at=NOW,completed_before=NOW,cache_dir=tmp_path,
        fetcher=lambda *a,**k:calls.append((a,k)))
    assert result['status']=='UNKNOWN'
    assert not calls and not list(tmp_path.iterdir())


def get(cache,c,now=NOW,fetcher=None,acquire=True):
    return rvol.get_evidence('TEST',c,decision_at=now,
        current_observed_at=NOW-timedelta(seconds=1),completed_before=NOW-timedelta(seconds=3),
        enabled=True,current_source=source('1m'),history_cache=cache,
        fetcher=fetcher,acquire=acquire)


def test_atomic_durable_cache_restart_and_cache_only_no_duplicate_provider(tmp_path):
    c,h=fixtures();calls=[]
    def provider(ticker,**kwargs):
        calls.append((ticker,kwargs));return h
    cache=rvol.HistoryCache(tmp_path,clock=lambda:NOW-timedelta(seconds=2))
    first=get(cache,c,fetcher=provider)
    assert first['status']=='VERIFIED' and len(calls)==1
    assert calls[0][1]==rvol.HISTORY_REQUEST
    assert len(list(tmp_path.glob('*.json')))==1 and not list(tmp_path.glob('.rvol-*'))
    restarted=rvol.HistoryCache(tmp_path,clock=lambda:NOW)
    second=get(restarted,c,fetcher=lambda *a,**k:pytest.fail('cache-only must not fetch'),acquire=False)
    assert second==first


def test_new_fetch_clock_is_not_backdated_but_actual_later_cache_read_is_usable(tmp_path):
    c,h=fixtures();calls=[];observed=NOW+timedelta(seconds=1)
    cache=rvol.HistoryCache(tmp_path,clock=lambda:observed)
    first=get(cache,c,fetcher=lambda *a,**k:(calls.append(1) or h))
    assert first['status']=='UNKNOWN'
    assert first['reason']=='UNKNOWN_FUTURE_HISTORY_OBSERVATION'
    second=get(cache,c,now=NOW+timedelta(seconds=2),acquire=False)
    assert second['status']=='VERIFIED' and len(calls)==1
    assert second['source_times']['history_observed_at']==observed.isoformat()


def test_cache_corruption_is_unknown_without_reacquisition(tmp_path):
    c,h=fixtures();cache=rvol.HistoryCache(tmp_path,clock=lambda:NOW-timedelta(seconds=1))
    assert get(cache,c,fetcher=lambda *a,**k:h)['status']=='VERIFIED'
    path=tmp_path/'TEST.json';content=path.read_text();path.write_text(content.replace('100.0','999.0',1))
    restarted=rvol.HistoryCache(tmp_path)
    assert get(restarted,c,fetcher=lambda *a,**k:pytest.fail('corruption must not refetch'))['status']=='UNKNOWN'


def test_negative_cache_survives_restart_and_avoids_blind_retry(tmp_path):
    c,_=fixtures();calls=[]
    def broken(*a,**k):calls.append(1);raise RuntimeError('synthetic provider outage')
    cache=rvol.HistoryCache(tmp_path,clock=lambda:NOW-timedelta(seconds=1))
    assert get(cache,c,fetcher=broken)['reason']=='UNKNOWN_HISTORY_FETCH_FAILED'
    restarted=rvol.HistoryCache(tmp_path,clock=lambda:NOW)
    assert get(restarted,c,fetcher=broken)['reason']=='UNKNOWN_HISTORY_FETCH_FAILED'
    assert len(calls)==1


def test_acquisition_budget_is_bounded_and_cache_only_cannot_use_it(tmp_path):
    _,h=fixtures();calls=[]
    cache=rvol.HistoryCache(tmp_path,clock=lambda:NOW-timedelta(seconds=1),max_acquisitions=2)
    provider=lambda *a,**k:(calls.append(1) or h)
    for ticker in ('AAA','BBB'):
        assert cache.history(ticker,decision_at=NOW,enabled=True,fetcher=provider)[0] is not None
    assert cache.history('CCC',decision_at=NOW,enabled=True,fetcher=provider)[1]=='UNKNOWN_ACQUISITION_BUDGET'
    assert cache.history('CCC',decision_at=NOW,enabled=True,acquire=False,fetcher=provider)[1]=='UNKNOWN_HISTORY_CACHE_MISS'
    assert len(calls)==2


def test_stale_cache_only_has_no_provider_side_effect(tmp_path):
    c,h=fixtures();cache=rvol.HistoryCache(tmp_path,clock=lambda:NOW-timedelta(seconds=10),ttl_seconds=5)
    get(cache,c,fetcher=lambda *a,**k:h)
    assert get(cache,c,acquire=False)['reason']=='UNKNOWN_HISTORY_CACHE_MISS'


def test_missing_basis_does_not_waste_optional_acquisition(tmp_path):
    c,_=fixtures()
    result=rvol.get_evidence('TEST',c,decision_at=NOW,current_observed_at=NOW,
        completed_before=NOW,enabled=True,cache_dir=tmp_path,
        fetcher=lambda *a,**k:pytest.fail('no proven source basis'))
    assert result['reason']=='UNKNOWN_VOLUME_BASIS'
    assert not list(tmp_path.iterdir())


def test_bounded_disk_eviction_only_removes_own_valid_cache_receipt(tmp_path):
    _,h=fixtures();cache=rvol.HistoryCache(tmp_path,clock=lambda:NOW-timedelta(seconds=1),max_entries=1)
    for ticker in ('AAA','BBB'):
        assert cache.history(ticker,decision_at=NOW,enabled=True,fetcher=lambda *a,**k:h)[0] is not None
    assert [p.name for p in tmp_path.glob('*.json')]==['BBB.json']


def test_optional_calendar_missing_is_unknown_no_hidden_install(monkeypatch):
    import sys
    c,h=fixtures();rvol._calendar.cache_clear()
    monkeypatch.setitem(sys.modules,'exchange_calendars',None)
    result=evaluate(c,h)
    assert result['reason']=='UNKNOWN_CALENDAR_UNAVAILABLE'


def test_cache_preserves_explicit_per_row_availability(tmp_path):
    c,h=fixtures();h['available_at']=NOW+timedelta(seconds=1)
    cache=rvol.HistoryCache(tmp_path,clock=lambda:NOW-timedelta(seconds=1))
    result=get(cache,c,fetcher=lambda *a,**k:h)
    assert result['reason']=='UNKNOWN_FUTURE_AVAILABILITY'


def test_availability_is_not_before_bar_completion_and_binds_content_hash():
    c,h=fixtures();c['available_at']=c.index+pd.Timedelta(minutes=1)
    first=evaluate(c,h)
    assert first['status']=='VERIFIED'
    c['available_at']+=pd.Timedelta(seconds=1)
    second=evaluate(c,h)
    assert second['status']=='VERIFIED' and first['sourcehash']!=second['sourcehash']
    c['available_at']=c.index
    assert evaluate(c,h)['reason']=='UNKNOWN_INVALID_AVAILABILITY'


def public(value, now=NOW):
    return rvol.public_evidence(value,decision_at=now,
                               completed_through='2026-10-21T14:10:00Z')


def test_public_evidence_is_strict_pure_projection_not_arbitrary_nested_content(monkeypatch):
    result=evaluate();result['private_payload']={'secret':'must not be copied'}
    monkeypatch.setattr(rvol,'session_schedule',lambda *a,**k:pytest.fail('frozen projection calendar call'))
    saved=public(result)
    assert saved['status']=='VERIFIED'
    assert saved['same_time_of_day_relative_volume']==2.
    assert 'private_payload' not in saved
    assert len(str(saved))<8192


@pytest.mark.parametrize('damage',['version','hash','future','ratio','mean','count',
    'duplicate_session','coverage','basis','elapsed','as_of','boolean','calendar'])
def test_invalid_frozen_metrics_never_become_verified_input(damage):
    result=evaluate()
    if damage=='version':result['version']='unsupported'
    if damage=='hash':result['sourcehash']='not-a-hash'
    if damage=='future':result['source_times']['history_observed_at']=(NOW+timedelta(seconds=1)).isoformat()
    if damage=='ratio':result['same_time_of_day_relative_volume']=20.
    if damage=='mean':result['prior_cumulative_mean']=1.
    if damage=='count':result['prior_session_count']=9
    if damage=='duplicate_session':result['prior_sessions'][0]=result['prior_sessions'][1]
    if damage=='coverage':result['current_complete_1m_rows']=5
    if damage=='basis':result['history_source']['auto_adjust']=False
    if damage=='elapsed':result['elapsed_regular_minutes']=41
    if damage=='as_of':result['as_of']='2026-10-21T14:05:00Z'
    if damage=='boolean':result['current_cumulative_volume']=True
    if damage=='calendar':result['calendar_id']='UNKNOWN_EXCHANGE'
    saved=public(result)
    assert saved['status']=='UNKNOWN' and saved['same_time_of_day_relative_volume'] is None


def test_public_unknown_keeps_only_allowlisted_reason_and_no_fake_metric():
    saved=public(dict(version=rvol.VERSION,status='UNKNOWN',reason='PRIVATE arbitrary text',
                      same_time_of_day_relative_volume=999.,extra='private'))
    assert saved['status']=='UNKNOWN' and saved['same_time_of_day_relative_volume'] is None
    assert saved['reason']=='UNKNOWN_INVALID_SAVED_EVIDENCE'
    assert 'extra' not in saved
