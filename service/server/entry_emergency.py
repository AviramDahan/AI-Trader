"""Shared durable PAPER entry stop; never disables exits or changes contracts.

An acknowledged change is committed under the same write lock used by entry
admission and bar execution. Missing legacy state is read-only/unpaused. All
other invalid state fails closed for entries, not for TP/SL or close orders.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json

KEY = VERSION = 'paper_entry_emergency_v1'
MAX_INTERVALS = 2048
MAX_BYTES = 262144
BAR_SIZE = timedelta(minutes=5)
UTC = timezone.utc
BLOCK_REASONS = frozenset({'entry_emergency_paused', 'entry_emergency_control_invalid',
    'entry_emergency_incomplete_bar', 'entry_emergency_paused_bar', 'entry_emergency_before_resume'})


def _instant(value):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError()
        return dt.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('entry_emergency_control_invalid') from None


def _stamp(value):
    return _instant(value).isoformat().replace('+00:00', 'Z')


def _now(value=None):
    return _instant(value) if value is not None else datetime.now(UTC)


def initial():
    return dict(version=VERSION, revision=0, paused=False, updated_at=None, intervals=[])


def validate(value, *, now=None):
    """Strict bounded history for recovery; no truncation, repair or pruning."""
    try:
        if (type(value) is not dict or set(value) != {'version', 'revision', 'paused', 'updated_at', 'intervals'}
                or value['version'] != VERSION or type(value['revision']) is not int
                or type(value['paused']) is not bool or type(value['intervals']) is not list
                or not 0 <= value['revision'] <= MAX_INTERVALS*2-1
                or len(value['intervals']) > MAX_INTERVALS):
            raise ValueError()
        if len(json.dumps(value, allow_nan=False, separators=(',', ':')).encode()) > MAX_BYTES:
            raise ValueError()
        intervals = value['intervals']
        if not intervals:
            if value != initial():
                raise ValueError()
            return initial()
        if (value['revision'] != 2*len(intervals)-int(value['paused'])
                or not value['paused'] and len(intervals) == MAX_INTERVALS):
            raise ValueError()
        limit, previous = _now(now), None
        last = None
        for index, interval in enumerate(intervals):
            if type(interval) is not dict or set(interval) != {'paused_at', 'resumed_at'}:
                raise ValueError()
            start = interval['paused_at']
            if type(start) is not str or len(start) > 32 or _stamp(start) != start:
                raise ValueError()
            began = _instant(start)
            if began > limit or previous is not None and began < previous:
                raise ValueError()
            end = interval['resumed_at']
            if end is None:
                if index != len(intervals)-1 or not value['paused']:
                    raise ValueError()
                last = start
            else:
                if type(end) is not str or len(end) > 32 or _stamp(end) != end:
                    raise ValueError()
                resumed = _instant(end)
                if resumed < began or resumed > limit:
                    raise ValueError()
                previous, last = resumed, end
                if index == len(intervals)-1 and value['paused']:
                    raise ValueError()
        if value['updated_at'] != last:
            raise ValueError()
        return copy.deepcopy(value)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError('entry_emergency_control_invalid') from None


def snapshot(cur, *, now=None):
    """Read only. Absence never inserts an unrequested format9 setting."""
    row = cur.execute('SELECT value_json FROM scanner_settings WHERE key=?', (KEY,)).fetchone()
    if row is None:
        return initial()
    try:
        raw = row['value_json']
        if type(raw) is not str or len(raw.encode()) > MAX_BYTES:
            raise ValueError()
        # Duplicate JSON keys are invalid, not a last-value override.
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    raise ValueError()
                result[key] = item
            return result
        return validate(json.loads(raw, object_pairs_hook=pairs), now=now)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError('entry_emergency_control_invalid') from None


def public_status(value, *, now=None):
    """No raw history, private actors, prompts or arbitrary text in the UI."""
    try:
        state = validate(value, now=now)
    except ValueError:
        return dict(version=VERSION, valid=False, paused=True, revision=None,
                    updated_at=None, interval_count=None, resume_eligible_from=None,
                    reason='entry_emergency_control_invalid', exits_continue=True)
    intervals = state['intervals']
    resume = intervals[-1]['resumed_at'] if intervals else None
    return dict(version=VERSION, valid=True, paused=state['paused'], revision=state['revision'],
        updated_at=state['updated_at'], interval_count=len(intervals), resume_eligible_from=resume,
        reason='entry_emergency_paused' if state['paused'] else None, exits_continue=True)


def status(cur=None, *, observed_at=None):
    from database import get_db_connection
    try:
        if cur is None:
            with get_db_connection() as conn:
                return public_status(snapshot(conn.cursor(), now=observed_at), now=observed_at)
        return public_status(snapshot(cur, now=observed_at), now=observed_at)
    except (ValueError, TypeError, KeyError):
        return public_status(None)


def set_paused(paused, expected_revision, *, now=None):
    """Trusted operator CAS; API callers must not supply an external clock.

    The final available pause is always retained. Once history is full, resume
    refuses and leaves that pause effective; no interval can be silently pruned.
    """
    if type(paused) is not bool or type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('entry_emergency_invalid_request')
    from database import begin_write_transaction, get_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        begin_write_transaction(cur)
        observed = _now(now)  # Capture AFTER obtaining the shared writer lock.
        prior = snapshot(cur, now=observed)
        if prior['revision'] != expected_revision:
            raise ValueError('entry_emergency_revision_conflict')
        if prior['paused'] == paused:
            conn.commit()
            return prior  # Including resume/rev0: no bootstrap insertion.
        state, at = copy.deepcopy(prior), _stamp(observed)
        if paused:
            if len(state['intervals']) >= MAX_INTERVALS:
                raise ValueError('entry_emergency_history_capacity')
            state['intervals'].append(dict(paused_at=at, resumed_at=None))
        else:
            if len(state['intervals']) >= MAX_INTERVALS:
                raise ValueError('entry_emergency_history_capacity')
            state['intervals'][-1]['resumed_at'] = at
        state.update(paused=paused, revision=prior['revision']+1, updated_at=at)
        state = validate(state, now=observed)
        cur.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
            (KEY, json.dumps(state, separators=(',', ':'), allow_nan=False), at))
        conn.commit()
        return state
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _overlap(state, start):
    end = start + BAR_SIZE
    return any(start < _instant(interval['resumed_at']) and end > _instant(interval['paused_at'])
               if interval['resumed_at'] is not None else end > _instant(interval['paused_at'])
               for interval in state['intervals'])


def check(cur, *, bar_at=None, observed_at=None):
    """Entry-only predicate. Caller owns the normal serialized write transaction."""
    try:
        from database import using_postgres
        if using_postgres():
            # A repeatable-read snapshot taken while waiting for the writer lock
            # must never hide an already-acknowledged pause. Normal writers use RC.
            isolation = cur.execute('SHOW transaction_isolation').fetchone()['transaction_isolation']
            if isolation != 'read committed':
                raise ValueError('entry_emergency_control_invalid')
        observed = _now(observed_at)
        state = snapshot(cur, now=observed)
        reason = 'entry_emergency_paused' if state['paused'] else None
        if reason is None and bar_at is not None and state['revision']:
            start = _instant(bar_at)
            if start + BAR_SIZE > observed:
                reason = 'entry_emergency_incomplete_bar'
            elif _overlap(state, start):
                reason = 'entry_emergency_paused_bar'
            elif state['intervals'] and start < _instant(state['intervals'][-1]['resumed_at']):
                reason = 'entry_emergency_before_resume'
        return dict(allowed=reason is None, reason=reason, revision=state['revision'])
    except (ValueError, TypeError, KeyError, OverflowError):
        return dict(allowed=False, reason='entry_emergency_control_invalid', revision=None)


def allows_entry(cur, *, bar_at=None, observed_at=None):
    return check(cur, bar_at=bar_at, observed_at=observed_at)['allowed']


def was_paused(cur, bar_at, *, observed_at=None):
    """Only explicit historical pause overlap can cover a MISSING recovery bar.

    The resume floor and present pause must not erase older, unpaused data gaps.
    Invalid state proves no historical no-fill interval; uncertainty stays safe.
    """
    try:
        observed = _now(observed_at)
        state = snapshot(cur, now=observed)
        start = _instant(bar_at)
        return start + BAR_SIZE <= observed and _overlap(state, start)
    except (ValueError, TypeError, KeyError, OverflowError):
        return False
