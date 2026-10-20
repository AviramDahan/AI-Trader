"""Opt-in Paper experiment: prior daily setup + completed regular 5m witness.

Pure calculation. No price, volume, model, database or message acquisition.
SETUP/FORMING is never executable attribution. Existing daily rules remain OR.
"""
from __future__ import annotations

import copy
from datetime import timedelta
import json
import os
import re

from entry_strategies import (DEFAULT_CONFIGS, SOURCE_PIN, _prepare, _record,
    _finish, _instant, _finite, _mean, _ema, _location, _hash, ET, HISTORY_REASONS)
from vendor.entry_discovery.vcp_pattern_calculator import calculate_vcp_pattern
from vendor.entry_discovery.stockbee import Bar, detect_base_profile

FLAG = 'STOCK_SCANNER_INDEPENDENT_INTRADAY_ENABLED'
SETUP_VERSION = 'independent_entry_setup_intraday_v1'
DETECTOR_VERSION = 'independent_entry_discovery_intraday_v1'
PACKAGE_VERSION = 'entry_discovery_intraday_v1'
EXECUTION_VERSION = 'independent_entry_execution_intraday_v1'
POLICY_VERSION = 'completed_regular_5m_prior_daily_setup_v1'
PRICE_BASIS = 'yahoo_auto_adjusted_v1'
ROUTES = tuple(s for s in DEFAULT_CONFIGS if s != 'PEAD')
# These are NEW cumulative same-prefix intraday policy hypotheses, not measured
# daily-volume equivalences, tuned optimal values or probabilities of a return.
RVOL_MIN = dict(zip(ROUTES, (1.5, 1.5, 1.0, 1.5)))
PENDING = 'intraday_confirmation_pending'
MAX_BYTES = 4096


def enabled(cfg=None):
    from entry_discovery_capabilities import creation_allowed
    if not creation_allowed():
        return False
    if cfg is not None and 'independent_intraday_enabled' in cfg:
        return cfg['independent_intraday_enabled'] is True
    return os.getenv(FLAG, 'false').lower() == 'true'


def _canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()


def _setup_level(record, level, kind, **features):
    record['features'].update(features)
    record['trigger'] = dict(kind=kind, level=float(level),
        max_entry_price=float(level*1.03), confirmed_at=None)
    return _finish(record, 'FORMING', PENDING, record['score'])


def _vcp_setup(record, rows, context):
    cfg = record['config'];window = rows[-cfg['lookback']:]
    pattern = calculate_vcp_pattern(list(reversed(window)), lookback_days=cfg['lookback'],
                                    min_contractions=cfg['min_contractions'])
    contractions = pattern.get('contractions') or []
    if not pattern.get('valid_vcp') or pattern.get('wide_and_loose') or len(contractions)<cfg['min_contractions']:
        return _finish(record, 'REJECTED', 'vcp_pattern_unconfirmed')
    for c in contractions:
        hi, lo = c['high_idx'], c['low_idx']
        if (type(hi) is not int or type(lo) is not int or not 0<=hi<lo<len(window) or
                c.get('high_date')!=window[hi]['date'] or c.get('low_date')!=window[lo]['date']):
            return _finish(record, 'UNKNOWN', 'vcp_pivot_unconfirmed')
    pivot = window[contractions[-1]['high_idx']]['high']
    dry = _mean([r['volume'] for r in rows[-10:]])/_mean([r['volume'] for r in rows[-50:]])
    sma50, sma200 = (_mean([r['close'] for r in rows[-n:]]) for n in (50,200))
    if dry>=cfg['dry_up_max']:
        return _finish(record, 'REJECTED', 'vcp_volume_not_dry')
    if rows[-1]['close']<=max(sma50,sma200):
        return _finish(record, 'REJECTED', 'vcp_trend_not_confirmed')
    record['score']=pattern['score']/100
    return _setup_level(record,pivot,'PRIOR_DAILY_VCP_COMPLETED_5M_BREAK',pivot=pivot,
        sma50=sma50,sma200=sma200,dry_up_ratio=dry,num_contractions=len(contractions))


def _momentum_setup(record, rows, context):
    cfg=record['config']
    prior=[Bar(**{k:r[k] for k in ('date','open','high','low','close','volume')}) for r in reversed(rows)]
    # The pinned helper uses ONLY indexes1.. for prior-base calculation. None is
    # an explicitly absent trigger slot, never a fabricated market candle.
    base=detect_base_profile([None,*prior],**{k:cfg[k] for k in
        ('min_base_days','max_base_days','max_base_width_pct','max_prior_avg_range_pct')})
    if not base.prior_base_days:
        return _finish(record,'REJECTED','momentum_base_unconfirmed')
    level=max(r['high'] for r in rows[-base.prior_base_days:])
    return _setup_level(record,level,'PRIOR_DAILY_BASE_COMPLETED_5M_BURST',
        prior_base_days=base.prior_base_days,base_width_pct=base.base_width_pct,
        prior_close=rows[-1]['close'],prior_day_gain_pct=(rows[-1]['close']/rows[-2]['close']-1)*100,
        prior_range_max=max(r['high']-r['low'] for r in rows[-3:]))


def _pullback_setup(record, rows, context):
    cfg=record['config'];closes=[r['close'] for r in rows]
    sma50=_mean(closes[-50:]);earlier=_mean(closes[-60:-10]);ema20=_ema(closes,20)
    recent=rows[-cfg['pullback_lookback']:]
    peak_index=max(range(len(recent)),key=lambda i:recent[i]['high'])
    if peak_index>=len(recent)-1:
        return _finish(record,'REJECTED','pullback_setup_unconfirmed')
    depth=(1-min(r['low'] for r in recent[peak_index+1:])/recent[peak_index]['high'])*100
    touched=any(r['low']<=ema20*(1+cfg['touch_ema_pct']/100) for r in recent)
    if sma50<=earlier:
        return _finish(record,'REJECTED','pullback_uptrend_unconfirmed')
    if not cfg['pullback_min_pct']<=depth<=cfg['pullback_max_pct'] or not touched:
        return _finish(record,'REJECTED','pullback_setup_unconfirmed')
    if rows[-1]['close']>ema20:
        return _finish(record,'REJECTED','pullback_already_reclaimed')
    return _setup_level(record,max(ema20,rows[-1]['high']),
        'PRIOR_DAILY_PULLBACK_COMPLETED_5M_RECLAIM',ema20=ema20,sma50=sma50,
        pullback_depth_pct=depth,touched_ema=touched)


def _rs_setup(record, rows, context):
    cfg=record['config']
    if context.get('benchmark_price_basis')!=PRICE_BASIS:
        return _finish(record,'UNKNOWN','intraday_benchmark_price_basis_unknown')
    try:
        observed=_instant(context['benchmark_observed_at'])
        benchmark=_prepare(context['benchmark_frame'],_instant(record['source_times']['decision_at']),
                           observed,rows[-1]['date'])
        by_date={r['date']:r for r in benchmark};needed=rows[-cfg['long_period']-1:]
        matched=[by_date[r['date']] for r in needed]
        short=((rows[-1]['close']/rows[-cfg['short_period']-1]['close']-1)-
               (matched[-1]['close']/matched[-cfg['short_period']-1]['close']-1))*100
        long=((rows[-1]['close']/needed[0]['close']-1)-(matched[-1]['close']/matched[0]['close']-1))*100
    except (KeyError,ValueError,TypeError,IndexError):
        return _finish(record,'UNKNOWN','benchmark_unavailable_at_decision')
    record['sourcehash']=_hash(dict(equity=record['sourcehash'],benchmark=matched,
                                    benchmark_observed_at=observed.isoformat()))
    record['source_times']['effective_available_at']=max(observed,
        _instant(record['source_times']['effective_available_at'])).isoformat()
    base=rows[-cfg['base_days']:];level=max(r['high'] for r in base)
    width=(level-min(r['low'] for r in base))/base[-1]['close']*100
    sma50=_mean([r['close'] for r in rows[-50:]])
    old=_mean([r['close'] for r in rows[-60:-10]])
    if short<=cfg['excess_short_min_pct'] or long<=cfg['excess_long_min_pct']:
        return _finish(record,'REJECTED','relative_strength_unconfirmed')
    if width>cfg['max_base_width_pct'] or sma50<=old:
        return _finish(record,'REJECTED','leader_setup_unconfirmed')
    return _setup_level(record,level,'PRIOR_DAILY_RS_BASE_COMPLETED_5M_BREAK',
        excess_short_pct=short,excess_long_pct=long,base_width_pct=width,sma50=sma50)


_SETUPS=dict(zip(ROUTES,(_vcp_setup,_momentum_setup,_pullback_setup,_rs_setup)))


def prepare_setups(frame, *, decision_at, source_observed_at, enabled_ids, context=None):
    """Prior daily setup only. FORMING can enter a bounded queue, never an order."""
    ids=tuple(enabled_ids);context=context or {}
    if len(ids)!=len(set(ids)) or set(ids)-set(ROUTES):
        raise ValueError('intraday_unknown_route')
    decision,observed=_instant(decision_at),_instant(source_observed_at)
    try:
        rows=_prepare(frame,decision,observed,context.get('expected_session'))
        if context.get('price_basis')!=PRICE_BASIS:
            raise ValueError('intraday_price_basis_unknown')
        if rows[-1]['date']>=decision.astimezone(ET).date().isoformat():
            raise ValueError('intraday_requires_prior_daily_session')
        error=None;input_failure=None
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        reasons=HISTORY_REASONS|{'intraday_price_basis_unknown','intraday_requires_prior_daily_session'}
        rows=[];error=str(exc) if str(exc) in reasons else 'invalid_history'
        input_failure=getattr(exc,'input_failure',None)
    output={}
    for sid in ids:
        record=_record(sid,copy.deepcopy(DEFAULT_CONFIGS[sid]),decision,observed,rows)
        record['version']=SETUP_VERSION
        record['features']=dict(price_basis=PRICE_BASIS,intraday_policy_version=POLICY_VERSION)
        if input_failure is not None:
            record['features']['input_failure']=copy.deepcopy(input_failure)
        if error:
            output[sid]=_finish(record,'UNKNOWN',error)
        elif len(rows)<record['config']['min_history']:
            output[sid]=_finish(record,'UNKNOWN','insufficient_history')
        else:
            output[sid]=_SETUPS[sid](record,rows,context)
    return output


def _session_row(value):
    """Typed frozen calendar fact, not a new query against today's calendar.

    Authentic calendar provenance is established at creation. Cold readers
    enforce its frozen semantic bounds, not provider truth or a DB signature.
    """
    keys={'session','open','close','duration_minutes','calendar_id','calendar_version'}
    if (not isinstance(value,dict) or set(value)!=keys or value.get('calendar_id')!='XNYS' or
            not isinstance(value.get('calendar_version'),str) or
            not re.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}',value['calendar_version']) or
            type(value.get('duration_minutes')) is not int or value['duration_minutes'] not in (210,390)):
        raise ValueError('intraday_session_proof_invalid')
    opened,closed=_instant(value['open']),_instant(value['close'])
    local_open,local_close=opened.astimezone(ET),closed.astimezone(ET)
    if (local_open.date().isoformat()!=value['session'] or local_open.weekday()>=5 or
            local_close.date()!=local_open.date() or (local_open.hour,local_open.minute)!=(9,30) or
            (local_close.hour,local_close.minute) not in ((13,0),(16,0)) or
            opened.second or opened.microsecond or closed.second or closed.microsecond or
            (closed-opened).total_seconds()!=value['duration_minutes']*60):
        raise ValueError('intraday_session_proof_invalid')
    return dict(value,open=opened.isoformat(),close=closed.isoformat())


def _witness(setup,evidence,price,quote_at,decision_at,*,frozen_session=None):
    now,quote=_instant(decision_at),_instant(quote_at)
    if (not isinstance(setup,dict) or setup.get('version')!=SETUP_VERSION or
            setup.get('strategy_id') not in ROUTES or setup.get('state')!='FORMING' or
            setup.get('reasons')!=[PENDING] or len(_canonical(setup))>MAX_BYTES):
        raise ValueError('intraday_setup_not_qualified')
    clocks=setup['source_times'];daily=_instant(clocks['source_data_at'])
    if (not _finite(price) or price<=0 or quote>now or (now-quote).total_seconds()>720 or
            _instant(clocks['decision_at'])>now or _instant(clocks['effective_available_at'])>now or
            _instant(clocks['decision_at']).astimezone(ET).date()!=now.astimezone(ET).date()):
        raise ValueError('intraday_quote_not_fresh')
    if (not isinstance(evidence,dict) or evidence.get('price_basis')!=PRICE_BASIS or
            setup['features'].get('price_basis')!=PRICE_BASIS):
        raise ValueError('intraday_price_basis_unknown')
    observed=_instant(evidence['observed_at']);through=_instant(evidence['completed_through'])
    bars=evidence['bars']
    if (observed>now or through>observed or not isinstance(bars,list) or not 1<=len(bars)<=6 or
            evidence.get('complete_window') is not True or evidence.get('gap_buckets')!=0):
        raise ValueError('intraday_incomplete_window')
    if frozen_session is None:
        try:
            from intraday_volume import session_bounds
            bounds=session_bounds(now.astimezone(ET).date())
            session=_session_row({k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in bounds.items()})
        except (ValueError,ImportError,KeyError,TypeError):
            raise ValueError('intraday_calendar_unavailable') from None
    else:
        session=_session_row(frozen_session)
    opened,closed=_instant(session['open']),_instant(session['close'])
    if session['session']!=now.astimezone(ET).date().isoformat():
        raise ValueError('intraday_session_proof_invalid')
    if not opened<=now<closed:
        raise ValueError('intraday_outside_regular_session')
    prior_end=None
    for b in bars:
        start,end=_instant(b['start_at']),_instant(b['end_at'])
        if (start.second or start.microsecond or start.minute%5 or start+timedelta(minutes=5)!=end or
                not opened<=start<end<=closed or end>through or end>observed or
                (prior_end is not None and start!=prior_end) or
                any(not _finite(b.get(k)) or b[k]<=0 for k in ('open','high','low','close')) or
                not _finite(b.get('volume')) or b['volume']<0 or
                not b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']):
            raise ValueError('intraday_invalid_completed_bar')
        prior_end=end
    last=bars[-1];end=_instant(last['end_at'])
    if daily>=opened or end>quote or (now-end).total_seconds()>720:
        raise ValueError('intraday_confirmation_stale')
    level,ceiling=(setup['trigger'][k] for k in ('level','max_entry_price'))
    if min(price,last['close'])<=level:
        raise ValueError('intraday_trigger_not_confirmed')
    if max(price,last['close'])>ceiling:
        raise ValueError('intraday_trigger_overextended')
    sid=setup['strategy_id'];ft=setup['features'];cfg=setup['config']
    if sid=='TREND_PULLBACK_RECLAIM' and (last['close']<=max(last['open'],ft['sma50'])):
        raise ValueError('intraday_pullback_quality_unconfirmed')
    if sid=='RELATIVE_STRENGTH_LEADER' and (last['close']<=ft['sma50'] or _location(last)<cfg['close_location_min']):
        raise ValueError('intraday_leader_quality_unconfirmed')
    if sid=='STOCKBEE_MOMENTUM_BURST':
        price_shape=((last['close']/ft['prior_close']-1)*100>=cfg['four_pct_threshold'] or
            last['close']-last['open']>=cfg['dollar_threshold'] or
            (last['high']-last['low']>ft['prior_range_max'] and
             ft['prior_day_gain_pct']<=cfg['max_prev_day_gain_for_range']))
        if not price_shape or _location(last)<cfg['close_location_min']:
            raise ValueError('intraday_momentum_quality_unconfirmed')
    return last,observed,now,session


def eligible_for_volume(setup,evidence,*,price,quote_at,decision_at):
    """Cheap price/setup check only: never emits DETECTED or performs IO."""
    try:
        _witness(setup,evidence,price,quote_at,decision_at)
        return True
    except (ValueError,TypeError,KeyError,OverflowError):
        return False


def _volume(evidence,last,now,sid,session):
    # Shared strict reader retains the complete causal measurement, including
    # source basis, ten actual prefix samples and coverage. No calendar IO.
    from intraday_volume import public_evidence
    v=public_evidence(evidence.get('relative_volume'),decision_at=now,
                      completed_through=last['end_at'])
    try:
        ratio=v['same_time_of_day_relative_volume']
        if (v.get('status')!='VERIFIED' or
                v.get('calendar_id')!=session['calendar_id'] or
                v.get('calendar_version')!=session['calendar_version'] or
                v.get('current_session')!=session['session'] or
                v.get('elapsed_regular_minutes')!=int((_instant(last['end_at'])-
                    _instant(session['open'])).total_seconds()/60) or
                v.get('prior_complete_5m_rows')!=session['duration_minutes']//5*10):
            raise ValueError()
    except (ValueError,TypeError,KeyError,OverflowError):
        raise ValueError('intraday_volume_unavailable') from None
    if ratio<RVOL_MIN[sid]:
        raise ValueError('intraday_volume_unconfirmed')
    if sid=='STOCKBEE_MOMENTUM_BURST' and (not _finite(v.get('current_cumulative_volume')) or
            v['current_cumulative_volume']<DEFAULT_CONFIGS[sid]['min_volume']):
        raise ValueError('intraday_momentum_volume_floor_unconfirmed')
    return v


def confirm_setup(setup,evidence,*,price,quote_at,decision_at):
    """Freeze a new record only after real completed price + causal RVOL proof."""
    result=copy.deepcopy(setup)
    try:
        last,observed,now,session=_witness(setup,evidence,price,quote_at,decision_at)
        volume=_volume(evidence,last,now,setup['strategy_id'],session)
        times=result['source_times'];daily_hash=result['sourcehash']
        times.update(decision_at=now.isoformat(),intraday_observed_at=observed.isoformat(),
            intraday_data_at=last['end_at'])
        times['effective_available_at']=max(_instant(times['effective_available_at']),observed,
            *(_instant(t) for t in volume['source_times'].values())).isoformat()
        result['features'].update(daily_sourcehash=daily_hash,
            intraday_confirmation=copy.deepcopy(last),relative_volume=volume,regular_session=session)
        result['trigger'].update(confirmed_at=last['end_at'],
            admission_valid_until=(_instant(last['end_at'])+timedelta(seconds=720)).isoformat())
        result['entry_reference']=dict(kind='COMPLETED_REGULAR_5M_CLOSE_NOT_EXECUTABLE',
            price=last['close'],at=last['end_at'])
        result['version']=DETECTOR_VERSION
        result['sourcehash']=_hash(dict(daily=daily_hash,confirmation=last,volume=volume,session=session))
        result=_finish(result,'DETECTED',score=max(.5,result['score']))
        validate_record(result)
        return result
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        reason=str(exc) if str(exc).startswith('intraday_') else 'intraday_invalid_evidence'
        state='FORMING' if reason.endswith('unconfirmed') or reason=='intraday_trigger_not_confirmed' else 'UNKNOWN'
        return _finish(result,state,reason)


def validate_record(record):
    """Stored intraday evidence reader: independent of creation flags/calendar IO."""
    try:
        if (record.get('version')!=DETECTOR_VERSION or record.get('source_pin')!=SOURCE_PIN or
                record.get('strategy_id') not in ROUTES or record.get('state')!='DETECTED' or
                record.get('direction')!='BUY' or len(_canonical(record))>MAX_BYTES):
            raise ValueError()
        ft=record['features'];bar=ft['intraday_confirmation'];volume=ft['relative_volume']
        times=record['source_times'];tr=record['trigger'];decision=_instant(times['decision_at'])
        end=_instant(bar['end_at']);observed=_instant(times['intraday_observed_at'])
        if (ft.get('price_basis')!=PRICE_BASIS or ft.get('intraday_policy_version')!=POLICY_VERSION or
                _instant(bar['start_at'])+timedelta(minutes=5)!=end or
                not _instant(times['source_data_at'])<end<=observed<=decision or
                _instant(times['intraday_data_at'])!=end or _instant(tr['confirmed_at'])!=end or
                _instant(tr['admission_valid_until'])!=end+timedelta(seconds=720) or
                decision>_instant(tr['admission_valid_until']) or
                record['sourcehash']!=_hash(dict(daily=ft['daily_sourcehash'],confirmation=bar,volume=volume,session=ft['regular_session'])) or
                volume['status']!='VERIFIED' or volume['same_time_of_day_relative_volume']<RVOL_MIN[record['strategy_id']] or
                _instant(volume['as_of'])!=end or
                record['entry_reference']!=dict(kind='COMPLETED_REGULAR_5M_CLOSE_NOT_EXECUTABLE',price=bar['close'],at=bar['end_at'])):
            raise ValueError()
        if (record['config']!=DEFAULT_CONFIGS[record['strategy_id']] or record.get('reasons')!=[] or
                not _finite(record.get('score')) or not 0<=record['score']<=1 or
                not isinstance(ft['daily_sourcehash'],str) or len(ft['daily_sourcehash'])!=64 or
                any(c not in '0123456789abcdef' for c in ft['daily_sourcehash']) or
                record['evidence_ids']!=[_hash({k:record[k] for k in
                    ('version','strategy_id','sourcehash','config','features','trigger')})]):
            raise ValueError()
        setup=copy.deepcopy(record)
        setup.update(version=SETUP_VERSION,state='FORMING',reasons=[PENDING])
        evidence=dict(price_basis=PRICE_BASIS,bars=[bar],observed_at=observed.isoformat(),
            completed_through=end.isoformat(),complete_window=True,gap_buckets=0,relative_volume=volume)
        _,_,_,session=_witness(setup,evidence,bar['close'],end,decision,frozen_session=ft['regular_session'])
        if session!=ft['regular_session'] or _volume(evidence,bar,decision,record['strategy_id'],session)!=volume:
            raise ValueError()
        return record
    except (ValueError,KeyError,TypeError,OverflowError):
        raise ValueError('intraday_record_invalid') from None


def validate_trigger(record,price,quote_at,decision_at):
    validate_record(record)
    now,quote=_instant(decision_at),_instant(quote_at);tr=record['trigger']
    if (not _finite(price) or price<=0 or quote>now or (now-quote).total_seconds()>720 or
            quote<_instant(tr['confirmed_at']) or now>_instant(tr['admission_valid_until']) or
            _instant(record['source_times']['effective_available_at'])>now):
        raise ValueError('entry_strategy_quote_not_fresh')
    if price<=tr['level']:
        raise ValueError('entry_strategy_trigger_not_confirmed')
    if price>tr['max_entry_price']:
        raise ValueError('entry_strategy_entry_overextended')
    return True
