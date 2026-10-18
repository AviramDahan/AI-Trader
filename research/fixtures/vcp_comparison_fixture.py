"""Invented253-business-bar controls: no historical prices, AI or fills.

The contraction path follows the same explicitly synthetic calculation fixture
as the Trading Agent's lifecycle tests. This tiny generator replaces a large
repeated OHLCV JSON file. Dates use the existing engine's session calendar, but
prices/volumes are invented, not a market-data feed or historical signal.
"""
import copy
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def build_dataset():
    server = Path(__file__).resolve().parents[2] / "service" / "server"
    if str(server) not in sys.path:
        sys.path.insert(0, str(server))
    # Calendar function only: no engine lifecycle, DB, quotes or orders called.
    from scanner_engine import market_session_state
    end = date(2026, 10, 2)
    days = []
    while len(days) < 252:
        if market_session_state(datetime.combine(end, time(12), ZoneInfo("America/New_York")))["is_trading_day"]:
            days.append(end.isoformat())
        end -= timedelta(days=1)
    days.reverse()
    anchors = [(0, 100), (20, 80), (40, 99), (55, 90), (70, 99.2),
               (82, 95), (104, 99.2), (119, 99.2)]
    tail = []
    for i in range(120):
        for (a, pa), (b, pb) in zip(anchors, anchors[1:]):
            if a <= i <= b:
                tail.append(pa + (pb - pa) * (i - a) / (b - a))
                break
    closes = [70 + 20 * i / 131 for i in range(132)] + tail
    scale = 100 / 100.9
    bars = [dict(date=day, Open=close*scale, High=(close+.65)*scale,
                 Low=(close-.65)*scale, Close=close*scale,
                 Volume=1_000_000 if i < 242 else 200_000)
            for i, (day, close) in enumerate(zip(days, closes))]
    bars.append(dict(date="2026-10-05", Open=99.2*scale, High=100.6*scale,
                     Low=99.1*scale, Close=100.4*scale, Volume=2_000_000))
    zone = dict(low=98.9, high=99.0, touches=1,
                pivots=[dict(price=98.9, date="2026-09-29", kind="swing_low",
                             confirmed_at="2026-10-01T20:05:00Z")])
    row = dict(observation_id="synthetic_confirmed", ticker="SYNTH", action="BUY", strategy="single",
               decision_at="2026-10-06T14:00:37Z", source_observed_at="2026-10-05T20:10:00Z",
               reference_at="2026-10-06T14:00:00Z", reference_kind="SYNTHETIC_REFERENCE_NOT_TRADE",
               reference_price=100.0, completed_high=max(b["High"] for b in bars[-20:]),
               source_inputs=dict(atr=1.0, zones=[zone], data_as_of="2026-10-05"), bars=bars)
    repeat, weak, short, protected = [copy.deepcopy(row) for _ in range(4)]
    repeat["observation_id"] = "synthetic_repeat_same_source"
    weak["observation_id"] = "synthetic_weak_trigger_volume"
    weak["bars"][-1]["Volume"] = 840_000
    short["observation_id"] = "synthetic_incomplete_warmup"
    short["bars"] = short["bars"][-127:]
    protected["observation_id"] = "synthetic_protected_nearest_resistance"
    protected["source_inputs"]["zones"].append(dict(low=100.5, high=100.7, touches=1,
        pivots=[dict(price=100.5, date="2026-09-29", kind="swing_high", confirmed_at="2026-10-01T20:05:00Z")]))
    return {"version": 1, "synthetic": True,
            "source": "INVENTED253-session controlled calculation fixture; not historical market, AI approval, execution or performance data",
            "observations": [row, repeat, weak, short, protected]}
