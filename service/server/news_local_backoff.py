"""Process-local news admission only; no queue, model or gateway mutations."""
import threading
import time

_lock=threading.Lock()
_until=0.
_streak=0
_validated_since_failure=False


def failed():
    global _until,_streak,_validated_since_failure
    with _lock:
        _streak=min(4,_streak+1)
        _until=max(_until,time.monotonic()+min(900,120*2**(_streak-1)))
        _validated_since_failure=False


def remaining():
    with _lock:
        return max(0.,_until-time.monotonic())


def validated_stage():
    # A single valid stage is progress, not proof that the story completed.
    global _validated_since_failure
    with _lock:
        _validated_since_failure=True


def story_completed():
    # A cached-only result or health probe must not clear a failing circuit.
    global _until,_streak,_validated_since_failure
    with _lock:
        if _validated_since_failure:
            _until,_streak,_validated_since_failure=0.,0,False


def story_incomplete():
    global _validated_since_failure
    with _lock:
        _validated_since_failure=False
