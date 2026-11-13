"""Causal cumulative intraday RVOL evidence; never an entry gate or signal.

Numerator: all completed regular-session 1m rows from open to a completed 5m
boundary. Denominator: mean cumulative volume to the SAME session-clock offset
in the last ten prior comparable XNYS sessions, each fully covered by 5m rows.
Half-days are only compared with half-days. Missing data is not zero volume.

``evaluate`` is pure. ``get_evidence`` has acquisition OFF by default and only
uses an explicitly supplied existing-provider fetcher. ``acquire=False`` is a
guaranteed provider-free cache read/evaluation. Cached observation clocks are
never backdated; a newly fetched snapshot can require a later actual decision
clock before evaluation. No provider/model/strategy setting is changed here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import threading
from collections import OrderedDict, deque
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from numbers import Real
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

VERSION = 'intraday_cumulative_rvol_v1'
ET = ZoneInfo('America/New_York')
UTC = timezone.utc
PRIOR_SESSIONS = 10
MAX_HISTORY_ROWS = 3000
MAX_CURRENT_ROWS = 600
SOURCE = dict(provider='yahoo', auto_adjust=True, actions=True,
              volume_basis='reported_shares_unscaled')
HISTORY_REQUEST = dict(period='1mo', interval='5m', prepost=False,
                       auto_adjust=True, actions=True, repair=False,
                       rounding=False, timeout=15)
UNKNOWN_REASONS = frozenset('''
UNKNOWN_AMBIGUOUS_CLOCK UNKNOWN_FUTURE_OBSERVATION UNKNOWN_VOLUME_BASIS
UNKNOWN_INVALID_FRAME UNKNOWN_ACTIONS_OR_OHLCV_NOT_RECORDED
UNKNOWN_INSUFFICIENT_COMPARABLE_SESSIONS UNKNOWN_HISTORY_WINDOW_BOUND
UNKNOWN_CALENDAR_UNAVAILABLE UNKNOWN_NONCOMPARABLE_SESSION
UNKNOWN_NO_COMPLETED_WINDOW UNKNOWN_STALE_CURRENT_WINDOW
UNKNOWN_PRIOR_SESSION_NOT_AVAILABLE UNKNOWN_INCOMPLETE_REGULAR_SESSION
UNKNOWN_FUTURE_AVAILABILITY UNKNOWN_INVALID_AVAILABILITY UNKNOWN_INVALID_OHLCV
UNKNOWN_SPLIT_VOLUME_UNITS UNKNOWN_SPLIT_OR_ACTIONS_COVERAGE
UNKNOWN_ZERO_OR_INVALID_DENOMINATOR UNKNOWN_INVALID_RATIO UNKNOWN_INVALID_INPUT
UNKNOWN_ACQUISITION_DISABLED UNKNOWN_INVALID_ACQUISITION_AUTHORITY
UNKNOWN_PROVIDER_ADAPTER_NOT_CONFIGURED UNKNOWN_HISTORY_CACHE_MISS
UNKNOWN_FUTURE_HISTORY_OBSERVATION UNKNOWN_ACQUISITION_BUDGET
UNKNOWN_HISTORY_FETCH_FAILED UNKNOWN_HISTORY_CACHE_UNAVAILABLE
UNKNOWN_CACHE_INVALID UNKNOWN_CACHE_NAMESPACE_BOUND
UNKNOWN_CALENDAR_OR_CLOCK_UNAVAILABLE UNKNOWN_SCAN_ACQUISITION_BUDGET
UNKNOWN_COLLECTOR_FAILURE UNKNOWN_INVALID_SAVED_EVIDENCE
'''.split())


def _instant(value):
    at = pd.Timestamp(value)
    if at.tzinfo is None:
        raise ValueError('UNKNOWN_AMBIGUOUS_CLOCK')
    return at.to_pydatetime().astimezone(UTC)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def unknown(reason, **metadata):
    return dict(version=VERSION, status='UNKNOWN', reason=reason,
                same_time_of_day_relative_volume=None,
                volume_comparison_status=reason, **metadata)


@lru_cache(maxsize=8)
def _calendar(year):
    # Local library only: no downloads, installation or calendar network calls.
    import exchange_calendars as calendars
    return calendars.get_calendar('XNYS', start=f'{year-1}-01-01',
                                  end=f'{year+1}-12-31')


def session_schedule(start, end):
    """Local XNYS schedule with aware open/close columns and version metadata.

    Missing calendar support raises ValueError; callers must preserve UNKNOWN.
    No hand-built fallback calendar invents a full session on an early close.
    """
    try:
        import exchange_calendars as calendars
        first, last = pd.Timestamp(start).date(), pd.Timestamp(end).date()
        if first > last or (last-first).days > 100:
            raise ValueError()
        frames = [_calendar(year).schedule.loc[str(first):str(last), ['open','close']]
                  for year in range(first.year, last.year+1)]
        frame = pd.concat(frames)
        frame = frame.loc[~frame.index.duplicated()].sort_index().copy()
        frame.attrs.update(calendar_id='XNYS', calendar_version=calendars.__version__)
        return frame
    except (ImportError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise ValueError('UNKNOWN_CALENDAR_UNAVAILABLE') from exc


def session_bounds(day, schedule=None):
    """Return aware bounds for one real session; closed/unknown days raise."""
    day = pd.Timestamp(day).date()
    frame = session_schedule(day,day) if schedule is None else schedule
    try:
        rows = frame.loc[[pd.Timestamp(x).date()==day for x in frame.index]]
        if len(rows)!=1:
            raise ValueError()
        opened, closed = (_instant(rows.iloc[0][name]) for name in ('open','close'))
        seconds=(closed-opened).total_seconds()
        duration = int(seconds/60)
        if (opened.astimezone(ET).date()!=day or opened.astimezone(ET).hour!=9 or
                opened.astimezone(ET).minute!=30 or opened.second or opened.microsecond or
                closed.second or closed.microsecond or seconds not in (210*60,390*60)):
            raise ValueError()
        return dict(session=day.isoformat(), open=opened, close=closed,
                    duration_minutes=duration, calendar_id=frame.attrs['calendar_id'],
                    calendar_version=frame.attrs['calendar_version'])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('UNKNOWN_NONCOMPARABLE_SESSION') from exc


def _source(value, interval):
    if not isinstance(value,dict) or value.get('interval')!=interval:
        raise ValueError('UNKNOWN_VOLUME_BASIS')
    if any(type(value.get(k)) is not type(v) or value.get(k)!=v for k,v in SOURCE.items()):
        raise ValueError('UNKNOWN_VOLUME_BASIS')
    return {**SOURCE, 'interval':interval}


def _frame(value, limit):
    if (not isinstance(value,pd.DataFrame) or len(value)>limit or
            not isinstance(value.index,pd.DatetimeIndex) or value.index.tz is None or value.index.hasnans):
        raise ValueError('UNKNOWN_INVALID_FRAME')
    if any(k not in value for k in ('Open','High','Low','Close','Volume','Stock Splits')):
        raise ValueError('UNKNOWN_ACTIONS_OR_OHLCV_NOT_RECORDED')
    result=value.copy(deep=True)
    result.index=result.index.tz_convert('UTC')
    return result


def _rows(frame, expected, observed, interval_minutes):
    selected=frame.loc[(frame.index>=expected[0]) & (frame.index<=expected[-1])]
    if selected.index.has_duplicates or list(selected.index.sort_values())!=list(expected):
        raise ValueError('UNKNOWN_INCOMPLETE_REGULAR_SESSION')
    selected=selected.sort_index()
    rows=[]
    for at,row in selected.iterrows():
        available=None
        if 'available_at' in selected:
            available=_instant(row['available_at'])
            if available>observed:raise ValueError('UNKNOWN_FUTURE_AVAILABILITY')
            if available<at.to_pydatetime()+timedelta(minutes=interval_minutes):
                raise ValueError('UNKNOWN_INVALID_AVAILABILITY')
        values=[]
        for name in ('Open','High','Low','Close','Volume','Stock Splits'):
            value=row[name]
            if isinstance(value,bool) or not isinstance(value,Real):
                raise ValueError('UNKNOWN_INVALID_OHLCV')
            value=float(value)
            if not math.isfinite(value):raise ValueError('UNKNOWN_INVALID_OHLCV')
            values.append(value)
        o,h,l,c,v,split=values
        if not (0<l<=min(o,c)<=max(o,c)<=h) or v<0:
            raise ValueError('UNKNOWN_INVALID_OHLCV')
        if split!=0:
            raise ValueError('UNKNOWN_SPLIT_VOLUME_UNITS')
        rows.append([at.isoformat(),*values,available.isoformat() if available else None])
    return rows


def evaluate(current_frame, history_frame, *, decision_at, current_observed_at,
             history_observed_at, completed_before, current_source=None,
             history_source=None, schedule=None):
    """Pure factual evidence, no threshold, score, action, provider or DB access.

    Sources must explicitly record provider/interval/auto_adjust/actions/volume
    basis (see SOURCE). Yahoo auto_adjust changes OHLC, NOT reported Volume;
    detected splits or absent action coverage are UNKNOWN, not adjusted guesses.
    ``available_at`` rows, if supplied, must not exceed their snapshot clock.
    Output ``as_of`` equals the completed current 5m boundary and may be used as
    a same-clock witness only; this cumulative RVOL is not a single-bar ratio.
    """
    try:
        now,co,ho,cut=map(_instant,(decision_at,current_observed_at,
                                    history_observed_at,completed_before))
        if max(co,ho,cut)>now or cut>co:
            raise ValueError('UNKNOWN_FUTURE_OBSERVATION')
        cs,hs=_source(current_source,'1m'),_source(history_source,'5m')
        cur=_frame(current_frame,MAX_CURRENT_ROWS)
        hist=_frame(history_frame,MAX_HISTORY_ROWS)
        if hist.empty:raise ValueError('UNKNOWN_INSUFFICIENT_COMPARABLE_SESSIONS')
        day=now.astimezone(ET).date()
        first=min(hist.index.min().date(),day)
        if (day-first).days>45:raise ValueError('UNKNOWN_HISTORY_WINDOW_BOUND')
        schedule=session_schedule(first,day) if schedule is None else schedule
        current=session_bounds(day,schedule)
        end=min(cut.replace(second=0,microsecond=0)-timedelta(minutes=cut.minute%5),
                current['close'])
        elapsed=int((end-current['open']).total_seconds()/60)
        if elapsed<=0:raise ValueError('UNKNOWN_NO_COMPLETED_WINDOW')
        if (now-end).total_seconds()>720:raise ValueError('UNKNOWN_STALE_CURRENT_WINDOW')
        expected=pd.date_range(current['open'],end,freq='min',inclusive='left')
        current_rows=_rows(cur,expected,co,1)
        prior=[]
        for stamp in schedule.index:
            d=pd.Timestamp(stamp).date()
            if d>=day:continue
            b=session_bounds(d,schedule)
            if b['duration_minutes']==current['duration_minutes']:prior.append(b)
        prior=sorted(prior,key=lambda b:b['session'])[-PRIOR_SESSIONS:]
        if len(prior)!=PRIOR_SESSIONS:
            raise ValueError('UNKNOWN_INSUFFICIENT_COMPARABLE_SESSIONS')
        samples=[];consumed=[]
        for b in prior:
            if b['close']>min(ho,now):raise ValueError('UNKNOWN_PRIOR_SESSION_NOT_AVAILABLE')
            full=pd.date_range(b['open'],b['close'],freq='5min',inclusive='left')
            rows=_rows(hist,full,ho,5)
            volume=math.fsum(r[5] for r in rows[:elapsed//5])
            samples.append(volume);consumed.extend(rows)
        # Action at a causal current-day 5m row can also disclose a split.
        action_rows=hist.loc[(hist.index>=prior[0]['open']) & (hist.index<end)]
        if (pd.to_numeric(action_rows['Stock Splits'],errors='coerce').isna().any() or
                (action_rows['Stock Splits'].astype(float)!=0).any()):
            raise ValueError('UNKNOWN_SPLIT_OR_ACTIONS_COVERAGE')
        numerator=math.fsum(r[5] for r in current_rows)
        denominator=math.fsum(samples)/PRIOR_SESSIONS
        if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator<=0:
            raise ValueError('UNKNOWN_ZERO_OR_INVALID_DENOMINATOR')
        ratio=numerator/denominator
        if not math.isfinite(ratio):raise ValueError('UNKNOWN_INVALID_RATIO')
        clocks=dict(decision_at=now.isoformat(),current_observed_at=co.isoformat(),
                    history_observed_at=ho.isoformat(),completed_before=cut.isoformat())
        fingerprint=dict(version=VERSION,current=current_rows,history=consumed,
                         sources=[cs,hs],clocks=clocks,calendar=current['calendar_version'])
        return dict(version=VERSION,status='VERIFIED',reason=None,
            same_time_of_day_relative_volume=ratio,
            volume_comparison_status='VERIFIED_PRIOR_SESSION_CUMULATIVE',
            definition='CUMULATIVE_REGULAR_OPEN_TO_SAME_COMPLETED_5M_PREFIX',
            as_of=end.isoformat(),completed_through=end.isoformat(),
            current_session=day.isoformat(),elapsed_regular_minutes=elapsed,
            current_cumulative_volume=numerator,prior_cumulative_mean=denominator,
            prior_session_count=len(prior),prior_sessions=[b['session'] for b in prior],
            prior_cumulative_volumes=samples,current_complete_1m_rows=len(current_rows),
            prior_complete_5m_rows=len(consumed),source_times=clocks,
            sourcehash=hashlib.sha256(_json(fingerprint).encode()).hexdigest(),
            calendar_id=current['calendar_id'],calendar_version=current['calendar_version'],
            current_source=cs,history_source=hs,
            interpretation='MEASUREMENT_ONLY_NOT_A_GATE_SIGNAL_OR_RETURN_PROBABILITY')
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,ImportError) as exc:
        reason=str(exc) if str(exc) in UNKNOWN_REASONS else 'UNKNOWN_INVALID_INPUT'
        return unknown(reason)


def public_evidence(value, *, decision_at, completed_through):
    """Strict frozen-evidence projection, with NO calendar/provider/cache access.

    ``completed_through`` is the exact 5m witness end, not a request cutoff with
    seconds. This checks stored identity, clocks, arithmetic and coverage; it
    cannot reconstruct raw source rows or re-prove the calendar's historical
    schedule from a hash. Original provenance clocks are retained, not refreshed.
    Unknown/malformed data exposes only a fixed reason and a null metric.
    """
    bad='UNKNOWN_INVALID_SAVED_EVIDENCE'
    try:
        if not isinstance(value,dict) or value.get('version')!=VERSION:
            return unknown(bad)
        if value.get('status')=='UNKNOWN':
            reason=value.get('reason')
            return unknown(reason if reason in UNKNOWN_REASONS else bad)
        if (value.get('status')!='VERIFIED' or value.get('reason') is not None or
                value.get('definition')!='CUMULATIVE_REGULAR_OPEN_TO_SAME_COMPLETED_5M_PREFIX' or
                value.get('volume_comparison_status')!='VERIFIED_PRIOR_SESSION_CUMULATIVE'):
            return unknown(bad)
        now,end,expected=map(_instant,(decision_at,value['as_of'],completed_through))
        if end!=expected or end!=_instant(value['completed_through']):return unknown(bad)
        if not 0<=(now-end).total_seconds()<=720:return unknown(bad)
        times=value['source_times']
        keys=('decision_at','current_observed_at','history_observed_at','completed_before')
        if not isinstance(times,dict) or set(times)!=set(keys):return unknown(bad)
        original,co,ho,cut=map(lambda key:_instant(times[key]),keys)
        if max(co,ho,cut)>original or original>now or cut>co or end>cut:return unknown(bad)
        if not isinstance(value.get('sourcehash'),str) or not re.fullmatch('[0-9a-f]{64}',value['sourcehash']):
            return unknown(bad)
        if (value.get('calendar_id')!='XNYS' or not isinstance(value.get('calendar_version'),str) or
                not re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}',value['calendar_version'])):
            return unknown(bad)
        cs,hs=_source(value['current_source'],'1m'),_source(value['history_source'],'5m')
        count=value['prior_session_count'];elapsed=value['elapsed_regular_minutes']
        current_rows=value['current_complete_1m_rows'];history_rows=value['prior_complete_5m_rows']
        if any(type(x) is not int for x in (count,elapsed,current_rows,history_rows)):
            return unknown(bad)
        if (count!=PRIOR_SESSIONS or history_rows not in (420,780) or
                current_rows!=elapsed or elapsed%5 or not 5<=elapsed<=390):return unknown(bad)
        duration=history_rows*5//count
        if elapsed>duration:return unknown(bad)
        local=end.astimezone(ET);opened=end-timedelta(minutes=elapsed)
        if (opened.astimezone(ET).date()!=local.date() or
                opened.astimezone(ET).hour!=9 or opened.astimezone(ET).minute!=30 or
                opened.second or opened.microsecond or value.get('current_session')!=local.date().isoformat()):
            return unknown(bad)
        boundary=cut.replace(second=0,microsecond=0)-timedelta(minutes=cut.minute%5)
        if min(boundary,opened+timedelta(minutes=duration))!=end:return unknown(bad)
        dates=value['prior_sessions'];samples=value['prior_cumulative_volumes']
        if (not isinstance(dates,list) or not isinstance(samples,list) or
                len(dates)!=count or len(samples)!=count or len(set(dates))!=count or dates!=sorted(dates)):
            return unknown(bad)
        for text in dates:
            if not isinstance(text,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',text):return unknown(bad)
            day=date.fromisoformat(text)
            if day>=local.date() or day.weekday()>=5:return unknown(bad)
            prior_close=datetime.combine(day,datetime.min.time(),ET).replace(hour=9,minute=30)+timedelta(minutes=duration)
            if prior_close.astimezone(UTC)>ho:return unknown(bad)
        def number(x):
            if isinstance(x,bool) or not isinstance(x,Real) or not math.isfinite(x) or x<0:
                raise ValueError(bad)
            return float(x)
        samples=[number(x) for x in samples]
        numerator=number(value['current_cumulative_volume'])
        denominator=number(value['prior_cumulative_mean'])
        ratio=number(value['same_time_of_day_relative_volume'])
        if (denominator<=0 or not math.isclose(math.fsum(samples)/count,denominator,rel_tol=1e-12,abs_tol=1e-12)
                or not math.isclose(numerator/denominator,ratio,rel_tol=1e-12,abs_tol=1e-12)):
            return unknown(bad)
        result=dict(version=VERSION,status='VERIFIED',reason=None,
            same_time_of_day_relative_volume=ratio,
            volume_comparison_status='VERIFIED_PRIOR_SESSION_CUMULATIVE',
            definition=value['definition'],as_of=end.isoformat(),completed_through=end.isoformat(),
            current_session=local.date().isoformat(),elapsed_regular_minutes=elapsed,
            current_cumulative_volume=numerator,prior_cumulative_mean=denominator,
            prior_session_count=count,prior_sessions=list(dates),prior_cumulative_volumes=samples,
            current_complete_1m_rows=current_rows,prior_complete_5m_rows=history_rows,
            source_times={key:_instant(times[key]).isoformat() for key in keys},
            sourcehash=value['sourcehash'],calendar_id='XNYS',calendar_version=value['calendar_version'],
            current_source=cs,history_source=hs,
            interpretation='MEASUREMENT_ONLY_NOT_A_GATE_SIGNAL_OR_RETURN_PROBABILITY')
        if len(_json(result).encode())>8192:return unknown(bad)
        return result
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):return unknown(bad)


class HistoryCache:
    """Bounded per-symbol atomic cache. No network unless enabled+acquire+fetcher.

    Only the scanner's existing provider adapter may be injected. Disk receipts
    hash exact serialized rows/metadata and retain actual observation times.
    In-process serialization plus the existing sole scanner lease prevent
    duplicate acquisition; this is not a replacement cross-worker lease.
    """
    def __init__(self, directory=None, *, clock=None, ttl_seconds=3600,
                 max_entries=64, max_acquisitions=6):
        self.directory=Path(directory) if directory is not None else None
        self.clock=clock or (lambda:datetime.now(UTC))
        self.ttl=ttl_seconds;self.max_entries=max_entries;self.max_acquisitions=max_acquisitions
        self.entries=OrderedDict();self.calls=deque();self.lock=threading.RLock()

    def _path(self,ticker):
        if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,11}',ticker):
            raise ValueError('UNKNOWN_INVALID_TICKER')
        return self.directory/(ticker+'.json') if self.directory is not None else None

    def _read(self,ticker):
        path=self._path(ticker)
        if path is None or not path.exists():return None
        if path.is_symlink() or path.stat().st_size>2_000_000:
            raise ValueError('UNKNOWN_CACHE_INVALID')
        raw=json.loads(path.read_text(encoding='utf-8'))
        payload=raw['payload']
        if hashlib.sha256(_json(payload).encode()).hexdigest()!=raw['sha256']:
            raise ValueError('UNKNOWN_CACHE_HASH_MISMATCH')
        if payload['version']!=VERSION or payload['ticker']!=ticker:
            raise ValueError('UNKNOWN_CACHE_INVALID')
        return payload

    def _write(self,ticker,payload):
        path=self._path(ticker)
        if path is None:return
        if self.directory.is_symlink() or path.is_symlink():
            raise ValueError('UNKNOWN_CACHE_INVALID')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        # Evict only a valid owned receipt, never an unrelated or corrupt file.
        files=list(self.directory.glob('*.json'))
        if not path.exists() and len(files)>=self.max_entries:
            victim=min(files,key=lambda p:p.stat().st_mtime)
            if (victim.is_symlink() or victim.resolve().parent!=self.directory.resolve()
                    or self._read(victim.stem) is None):
                raise ValueError('UNKNOWN_CACHE_CAPACITY')
            victim.unlink()
        blob=_json(dict(payload=payload,sha256=hashlib.sha256(_json(payload).encode()).hexdigest())).encode()
        if len(blob)>2_000_000:raise ValueError('UNKNOWN_CACHE_SIZE')
        fd,name=tempfile.mkstemp(prefix='.rvol-',dir=self.directory)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(blob);out.flush();os.fsync(out.fileno())
            os.chmod(name,0o600);os.replace(name,path)
        finally:
            if os.path.exists(name):os.unlink(name)

    def history(self,ticker, *, decision_at, enabled=False, acquire=True, fetcher=None):
        if enabled is not True:return None,'UNKNOWN_ACQUISITION_DISABLED'
        if type(acquire) is not bool:return None,'UNKNOWN_INVALID_ACQUISITION_AUTHORITY'
        try:
            decision=_instant(decision_at)
            with self.lock:
                entry=self.entries.get(ticker)
                if entry is None:
                    entry=self._read(ticker)
                if entry is not None:
                    at=_instant(entry['observed_at']);age=(decision-at).total_seconds()
                    if age<0:return None,'UNKNOWN_FUTURE_HISTORY_OBSERVATION'
                    lifetime=self.ttl if entry.get('rows') is not None else 300
                    if age<=lifetime:return copy.deepcopy(entry),None
                if not acquire:return None,'UNKNOWN_HISTORY_CACHE_MISS'
                if fetcher is None:return None,'UNKNOWN_PROVIDER_ADAPTER_NOT_CONFIGURED'
                now=_instant(self.clock())
                while self.calls and (now-self.calls[0]).total_seconds()>300:self.calls.popleft()
                if len(self.calls)>=self.max_acquisitions:return None,'UNKNOWN_ACQUISITION_BUDGET'
                self.calls.append(now)
                try:
                    result=fetcher(ticker,**HISTORY_REQUEST)
                    history=_frame(result,MAX_HISTORY_ROWS)
                    cols=['Open','High','Low','Close','Volume','Stock Splits']
                    if 'available_at' in history:cols.append('available_at')
                    rows=[]
                    for at,r in history.iterrows():
                        numeric=[r[k] for k in cols if k!='available_at']
                        if any(isinstance(v,bool) or not isinstance(v,Real) for v in numeric):
                            raise ValueError('UNKNOWN_INVALID_HISTORY_RESPONSE')
                        row=[at.isoformat(),*map(float,numeric)]
                        if not all(math.isfinite(v) for v in row[1:]):
                            raise ValueError('UNKNOWN_INVALID_HISTORY_RESPONSE')
                        if 'available_at' in cols:row.append(_instant(r['available_at']).isoformat())
                        rows.append(row)
                    entry=dict(version=VERSION,ticker=ticker,observed_at=_instant(self.clock()).isoformat(),
                        source={**SOURCE,'interval':'5m'},columns=cols,rows=rows)
                except Exception:
                    entry=dict(version=VERSION,ticker=ticker,observed_at=_instant(self.clock()).isoformat(),
                               rows=None,reason='UNKNOWN_HISTORY_FETCH_FAILED')
                self._write(ticker,entry)
                self.entries[ticker]=entry
                while len(self.entries)>self.max_entries:self.entries.popitem(last=False)
                if _instant(entry['observed_at'])>decision:
                    return None,'UNKNOWN_FUTURE_HISTORY_OBSERVATION'
                return copy.deepcopy(entry),None
        except (ValueError,TypeError,KeyError,OSError,json.JSONDecodeError):
            return None,'UNKNOWN_HISTORY_CACHE_UNAVAILABLE'


_CACHES={}
_CACHE_LOCK=threading.Lock()


def get_evidence(ticker,current_frame, *, decision_at,current_observed_at,
                 completed_before,enabled=False,fetcher=None,acquire=True,
                 current_source=None,cache_dir=None,history_cache=None):
    """Optional bounded cache producer; ``acquire=False`` never calls provider.

    Caller owns its existing per-scan budget (at most six history acquisitions).
    There is also a six-acquisition/300s in-process guard. Acquisition defaults
    OFF, including cache filesystem access. Source identity is explicit; current
    source metadata is not inferred merely from passing a DataFrame.
    """
    if enabled is not True:return unknown('UNKNOWN_ACQUISITION_DISABLED')
    if type(acquire) is not bool:return unknown('UNKNOWN_INVALID_ACQUISITION_AUTHORITY')
    try:_source(current_source,'1m')
    except ValueError:return unknown('UNKNOWN_VOLUME_BASIS')
    # A missing calendar or invalid current authority never licenses extra IO.
    try:
        now,co,cut=map(_instant,(decision_at,current_observed_at,completed_before))
        if max(co,cut)>now or cut>co:return unknown('UNKNOWN_FUTURE_OBSERVATION')
        session_bounds(now.astimezone(ET).date())
    except (ValueError,TypeError,KeyError,ImportError):return unknown('UNKNOWN_CALENDAR_OR_CLOCK_UNAVAILABLE')
    if history_cache is None:
        path=Path(cache_dir) if cache_dir is not None else Path(__file__).resolve().parents[2]/'.runtime'/'intraday-volume'
        with _CACHE_LOCK:
            key=str(path.resolve())
            if key not in _CACHES:
                if len(_CACHES)>=4:return unknown('UNKNOWN_CACHE_NAMESPACE_BOUND')
                _CACHES[key]=HistoryCache(path)
            history_cache=_CACHES[key]
    entry,reason=history_cache.history(ticker,decision_at=decision_at,enabled=True,
                                     acquire=acquire,fetcher=fetcher)
    if entry is None:return unknown(reason)
    if entry.get('rows') is None:return unknown(entry['reason'])
    try:
        frame=pd.DataFrame([r[1:] for r in entry['rows']],columns=entry['columns'],
                           index=pd.DatetimeIndex([r[0] for r in entry['rows']]))
        return evaluate(current_frame,frame,decision_at=decision_at,
            current_observed_at=current_observed_at,history_observed_at=entry['observed_at'],
            completed_before=completed_before,current_source=current_source,
            history_source=entry['source'])
    except (ValueError,TypeError,KeyError):return unknown('UNKNOWN_CACHE_INVALID')
