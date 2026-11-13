"""Process-local news admission only; no queue, model or gateway mutations."""
import threading
import time
from contextvars import ContextVar

_lock=threading.Lock()
_until=0.
_streak=0
_live_stage=ContextVar('news_story_live_stage',default=None)


def begin_story():
    return _live_stage.set(False)


def end_story(token):
    _live_stage.reset(token)


def in_story():
    return _live_stage.get() is not None


def failed():
    global _until,_streak
    if _live_stage.get() is None:
        return  # Position/other tasks must not alter the publication circuit.
    with _lock:
        _streak=min(4,_streak+1)
        _until=max(_until,time.monotonic()+min(900,120*2**(_streak-1)))
    _live_stage.set(False)


def remaining():
    with _lock:
        return max(0.,_until-time.monotonic())


def validated_stage():
    # A single valid stage is progress, not proof that the story completed.
    if _live_stage.get() is not None:
        _live_stage.set(True)


def story_completed():
    # A cached-only result or health probe must not clear a failing circuit.
    global _until,_streak
    with _lock:
        if _live_stage.get() is True:
            _until,_streak=0.,0
            _live_stage.set(False)


def story_incomplete():
    if _live_stage.get() is not None:
        _live_stage.set(False)
