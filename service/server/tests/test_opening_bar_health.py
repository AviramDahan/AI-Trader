"""No requests, trades or signals: session-aware health clock regression."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scanner_engine import _regular_session_bar_stale

UTC = timezone.utc
ET = ZoneInfo('America/New_York')

@pytest.mark.parametrize('day,utc_hour', [('2026-09-30',13), ('2026-12-01',14)])
def test_open_does_not_require_completed_bar_before_it_exists(day, utc_hour):
    opened = datetime.fromisoformat(day).replace(hour=9,minute=30,tzinfo=ET).astimezone(UTC)
    assert opened.hour == utc_hour
    old = opened - timedelta(days=1)
    assert not _regular_session_bar_stale(old, opened + timedelta(minutes=4))
    assert not _regular_session_bar_stale(old, opened + timedelta(minutes=15))
    assert _regular_session_bar_stale(old, opened + timedelta(minutes=15,seconds=1))

def test_intraday_staleness_threshold_is_unchanged():
    bar = datetime(2026,9,30,15,0,tzinfo=UTC)
    assert not _regular_session_bar_stale(bar, bar + timedelta(minutes=15))
    assert _regular_session_bar_stale(bar, bar + timedelta(minutes=15,seconds=1))

def test_new_regular_bar_replaces_opening_baseline():
    bar = datetime(2026,9,30,13,40,tzinfo=UTC)
    assert not _regular_session_bar_stale(bar, bar + timedelta(minutes=10))
    assert _regular_session_bar_stale(bar, bar + timedelta(minutes=16))
