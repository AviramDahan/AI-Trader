"""Time-labelled AI evidence only. No network, orders, scoring or trading gates."""
import copy
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

VERSION = 'review_time_context_v1'
ET = ZoneInfo('America/New_York')
DAILY_FIELDS = ('volume_ratio','rsi14','ema20','ema50','macd_histogram','atr','atr_pct',
                'return_20d_pct','recent_high_20d','recent_low_20d',
                'average_dollar_volume','realized_volatility_pct')


def instant(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError('evidence_requires_timezone')
    return stamp.to_pydatetime().astimezone(timezone.utc)


def finite(value, positive=False):
    return (not isinstance(value,bool) and isinstance(value,(int,float)) and
            math.isfinite(value) and (value>0 if positive else value>=0))


def unknown(reason):
    return dict(status=reason,source='yahoo_regular_1m',bars=[],fresh=False,
                same_time_of_day_relative_volume=None,
                volume_comparison_status='UNAVAILABLE_NO_COMPARABLE_SESSION_HISTORY')


class ObservedQuote(tuple):
    """Keep the existing two-value quote interface; attach bounded factual evidence."""
    def __new__(cls,price,at,evidence, *, volume_frame=None, source_observed_at=None,
                completed_before=None, volume_source=None):
        quote=super().__new__(cls,(price,at))
        quote.evidence=copy.deepcopy(evidence)
        # Private in-memory input, never part of the model/journal JSON. The
        # explicit producer metadata is required; a DataFrame is not provenance.
        quote.volume_frame=volume_frame
        quote.source_observed_at=source_observed_at
        quote.completed_before=completed_before
        quote.volume_source=copy.deepcopy(volume_source)
        return quote


def completed_observation(frame,observed_at,completed_before=None):
    """At most six completed 5m bars, from the SAME existing 1m response.

    Five distinct, valid one-minute OHLCV rows are required per bar. No gaps,
    duplicate timestamps, unfinished minutes or previous sessions are filled in.
    Missing volume is unknown, not zero. This does not confirm a trade or fill.
    """
    try:
        now=instant(observed_at)
        cutoff=instant(completed_before) if completed_before is not None else now
        if cutoff>now:
            return unknown('UNKNOWN_INCONSISTENT_OBSERVATION_TIME')
        from scanner_engine import market_session_state
        if not market_session_state(now)['is_trading_day']:
            return unknown('UNKNOWN_NON_TRADING_DAY')
        if frame is None or frame.empty or len(frame)>600:
            return unknown('UNKNOWN_NO_VALID_FRAME')
        if any(k not in frame for k in ('Open','High','Low','Close','Volume')):
            return unknown('UNKNOWN_MISSING_OHLCV')
        if frame.index.tz is None or frame.index.has_duplicates:
            return unknown('UNKNOWN_AMBIGUOUS_TIMESTAMPS')
        boundary=cutoff.replace(second=0,microsecond=0)
        boundary-=timedelta(minutes=boundary.minute%5)
        # The existing response may contain a whole session. Only the bounded
        # evidence window needs row parsing, including for rejected candidates.
        stamps=frame.index.tz_convert('UTC')
        selected=frame.loc[(stamps>=boundary-timedelta(minutes=30)) & (stamps<boundary)]
        indexed={instant(at):row for at,row in selected.iterrows()}
        local=now.astimezone(ET)
        bars=[];gaps=0;expected_bars=0
        for offset in range(6,0,-1):
            start=boundary-timedelta(minutes=5*offset)
            end=start+timedelta(minutes=5)
            first,last=start.astimezone(ET),(end-timedelta(minutes=1)).astimezone(ET)
            if first.date()!=local.date() or not (570<=first.hour*60+first.minute<960
                                                and 570<=last.hour*60+last.minute<960):
                continue
            expected_bars+=1
            minutes=[indexed.get(start+timedelta(minutes=i)) for i in range(5)]
            if any(row is None for row in minutes):
                gaps+=1;continue
            values=[[float(row[k]) for k in ('Open','High','Low','Close','Volume')] for row in minutes]
            if any(not all(finite(v,positive=True) for v in row[:4]) or not finite(row[4])
                   or not row[2]<=min(row[0],row[3])<=max(row[0],row[3])<=row[1] for row in values):
                gaps+=1;continue
            bars.append(dict(start_at=start.isoformat(),end_at=end.isoformat(),
                open=values[0][0],high=max(v[1] for v in values),low=min(v[2] for v in values),
                close=values[-1][3],volume=sum(v[4] for v in values)))
        out=unknown(('COMPLETED_BARS_WITH_GAPS' if gaps else 'COMPLETED_BARS') if bars else 'UNKNOWN_NO_COMPLETED_BARS')
        out.update(observed_at=now.isoformat(),completed_through=cutoff.isoformat(),bars=bars,gap_buckets=gaps,
                   expected_bars=expected_bars,complete_window=bool(bars) and gaps==0)
        if bars:
            out['fresh']=(now-instant(bars[-1]['end_at'])).total_seconds()<=720
            out['latest_completed_at']=bars[-1]['end_at']
            if not out['fresh']:out['status']='STALE_COMPLETED_BARS'
        return out
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return unknown('UNKNOWN_INVALID_OBSERVATION')


def context(candidate,observed_at,expected_session):
    """Freeze exact input provenance, without interpreting unknown as bearish/bullish."""
    now=instant(observed_at)
    daily_at=candidate.get('daily_reference_as_of') or candidate.get('price_as_of')
    coverage=('LATEST_COMPLETED_SESSION' if daily_at==expected_session else
              'OTHER_COMPLETED_SESSION' if daily_at else 'UNKNOWN_NO_DAILY_SESSION')
    daily=dict(as_of=daily_at,expected_session=expected_session,coverage=coverage,
        reference_close=candidate.get('daily_reference_close'),
        current_session_volume_available=False,
        metrics={k:candidate[k] for k in DAILY_FIELDS if k in candidate})
    quote_at=candidate.get('quote_at')
    quote=dict(price=candidate.get('entry'),as_of=None,age_seconds=None)
    try:
        at=instant(quote_at)
        quote.update(as_of=at.isoformat(),age_seconds=(now-at).total_seconds())
    except (ValueError,TypeError):pass
    intraday=copy.deepcopy(candidate.get('_intraday_evidence') or unknown('UNKNOWN_NO_OBSERVATION'))
    try:
        if not intraday['bars']:
            # Preserve the collector's precise unknown reason; never add facts.
            intraday=unknown(intraday.get('status','UNKNOWN_NO_OBSERVATION'))
        elif (instant(intraday['observed_at'])>now or len(intraday['bars'])>6 or
              instant(intraday['completed_through'])>instant(intraday['observed_at'])):
            raise ValueError('future_or_unbounded')
        if any(instant(b['end_at'])>instant(intraday['completed_through']) or instant(b['end_at'])>now
               or instant(b['start_at'])+timedelta(minutes=5)!=instant(b['end_at'])
               or not all(finite(b[k],positive=True) for k in ('open','high','low','close'))
               or not finite(b['volume']) or not b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']
               or instant(b['start_at']).astimezone(ET).date()!=now.astimezone(ET).date()
               for b in intraday['bars']):
            raise ValueError('invalid_bar')
        if any(instant(a['end_at'])>instant(b['start_at']) for a,b in zip(intraday['bars'],intraday['bars'][1:])):
            raise ValueError('overlapping_or_unsorted_bars')
        if intraday['bars']:
            intraday['fresh']=(now-instant(intraday['bars'][-1]['end_at'])).total_seconds()<=720
            if not intraday['fresh']:intraday['status']='STALE_COMPLETED_BARS'
    except KeyError:
        intraday=unknown('UNKNOWN_NO_OBSERVATION')
    except (ValueError,TypeError):
        intraday=unknown('UNKNOWN_INVALID_OR_FUTURE_OBSERVATION')
    if 'relative_volume' in intraday:
        from intraday_volume import public_evidence
        saved = public_evidence(intraday['relative_volume'], decision_at=now,
            completed_through=intraday['bars'][-1]['end_at'] if intraday['bars'] else None)
        intraday['relative_volume'] = saved
        intraday['same_time_of_day_relative_volume'] = saved.get('same_time_of_day_relative_volume')
        intraday['volume_comparison_status'] = saved['volume_comparison_status']
    plan=candidate.get('validated_target_plan') or {}
    high=plan.get('completed_high')
    for b in intraday['bars']:
        b['close_above_completed_20d_high']=(b['close']>high if finite(high,positive=True) else None)
    policy={k:plan[k] for k in ('policy_version','target_kind','source_data_at','completed_high',
                              'completed_high_sessions','minimum_rr') if k in plan}
    result=dict(version=VERSION,prepared_at=now.isoformat(),completed_daily=daily,
                entry_quote=quote,intraday=intraday,target_policy=policy)
    from review_rationale import price_facts
    result['entry_price_facts']=price_facts(candidate,result)
    return result
