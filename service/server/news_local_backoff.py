"""Process-local news admission only; no queue, model or gateway mutations."""
import threading
import time

_lock=threading.Lock()
_until=0.
_streak=0


def failed():
    global _until,_streak
    with _lock:
        _streak=min(4,_streak+1)
        _until=max(_until,time.monotonic()+min(900,120*2**(_streak-1)))


def remaining():
    with _lock:
        return max(0.,_until-time.monotonic())


def recovered():
    # Called only after full schema validation, never from a health probe.
    global _until,_streak
    with _lock:
        _until,_streak=0.,0
