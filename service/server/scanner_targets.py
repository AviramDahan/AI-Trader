"""Deterministic daily swing-zone targets; experimental, not price forecasts."""
import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd


ET = ZoneInfo("America/New_York")


def _completed_daily(frame):
    now_et = datetime.now(timezone.utc).astimezone(ET)
    # The same-day Yahoo bar is eligible only after the regular session has
    # completed and providers have had a small finalization buffer.
    cutoff = now_et.date() + timedelta(days=1) if now_et.time() >= time(16, 5) else now_et.date()
    return frame[[pd.Timestamp(stamp).date() < cutoff for stamp in frame.index]]


def swing_zones(frame, atr, lookback=126):
    # Only completed daily bars; two later bars must confirm each pivot.
    frame = _completed_daily(frame).tail(lookback)
    points = []
    for i in range(2, len(frame)-2):
        window = frame.iloc[i-2:i+3]
        for column, kind in (("High", "swing_high"), ("Low", "swing_low")):
            price = float(frame.iloc[i][column])
            extreme = window[column].max() if column == "High" else window[column].min()
            if math.isfinite(price) and price > 0 and price == extreme:
                points.append({"price": price, "date": frame.index[i].date().isoformat(), "kind": kind})
    groups = []
    for point in sorted(points, key=lambda p: p["price"]):
        if not groups or point["price"] - groups[-1][0]["price"] > .5 * atr:
            groups.append([])
        groups[-1].append(point)
    return [{"low": min(p["price"] for p in group), "high": max(p["price"] for p in group),
             "touches": len({p["date"] for p in group}), "pivots": group} for group in groups]


def open_position_target_plan(frame, entry, stop, fractions, current_price=None):
    """Build three forward targets from observed resistance and measured structure.

    This is intentionally separate from signal admission. Existing risk and stop
    are preserved; only still-unfilled targets may be revised by the maintenance
    script. Confirmed resistance is preferred. When price discovery leaves fewer
    than three overhead zones, projections use the completed 20-session range and
    are labelled as projections rather than resistance.
    """
    values = [entry, stop, *(fractions or [])]
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Invalid open-position target inputs")
    entry, stop = float(entry), float(stop)
    fractions = [float(value) for value in fractions]
    if entry <= 0 or stop <= 0 or stop >= entry or len(fractions) != 3 or abs(sum(fractions) - 1) > 1e-4:
        raise ValueError("Invalid long position or target allocation")

    completed = _completed_daily(frame)[["Open", "High", "Low", "Close", "Volume"]]
    completed = completed.dropna(subset=["High", "Low", "Close"]).tail(504)
    if len(completed) < 65:
        raise ValueError("Insufficient completed daily history")
    close = completed["Close"].astype(float)
    high = completed["High"].astype(float)
    low = completed["Low"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1])
    latest = float(close.iloc[-1])
    reference = max(entry, latest, float(current_price or 0))
    if not all(math.isfinite(value) and value > 0 for value in (atr, latest, reference)):
        raise ValueError("Invalid daily history")

    candidates = []
    for zone in swing_zones(completed, atr, lookback=504):
        if float(zone["low"]) <= reference:
            continue
        target = float(zone["low"]) - 0.08 * atr
        if target > reference + 0.10 * atr:
            candidates.append({
                "price": target,
                "source": "confirmed_daily_resistance",
                "zone": zone,
                "touches": int(zone["touches"]),
            })

    # If overhead history is sparse, project the latest completed 20-session
    # chart range from its high. These are measured-move objectives, not claimed
    # resistance levels, and remain visibly labelled as such in the UI/audit.
    window = completed.tail(20)
    range_high = float(window["High"].max())
    range_low = float(window["Low"].min())
    chart_range = range_high - range_low
    if not math.isfinite(chart_range) or chart_range < atr:
        chart_range = atr
    for ratio in (0.272, 0.618, 1.0, 1.272, 1.618):
        target = range_high + ratio * chart_range
        if target > reference + 0.10 * atr:
            candidates.append({
                "price": target,
                "source": "twenty_session_measured_move",
                "ratio": ratio,
                "range_high": range_high,
                "range_low": range_low,
                "touches": 0,
            })

    candidates.sort(key=lambda item: (item["price"], 0 if item["source"] == "confirmed_daily_resistance" else 1))
    selected = []
    for candidate in candidates:
        if selected and candidate["price"] - selected[-1]["price"] < 0.20 * atr:
            # Prefer observed resistance over a nearby projection.
            if (candidate["source"] == "confirmed_daily_resistance"
                    and selected[-1]["source"] != "confirmed_daily_resistance"):
                selected[-1] = candidate
            continue
        selected.append(candidate)
        if len(selected) == 3:
            break
    if len(selected) < 3:
        raise ValueError("Insufficient forward chart objectives")

    targets = [round(item["price"], 2) for item in selected]
    if not entry < targets[0] < targets[1] < targets[2] or targets[0] <= reference:
        raise ValueError("Invalid forward target order")
    original_r = entry - stop
    rr = [(target - entry) / original_r for target in targets]
    weighted = sum(ratio * fraction for ratio, fraction in zip(rr, fractions))
    return {
        "method": "daily_resistance_and_measured_move_v1",
        "entry": entry,
        "stop": stop,
        "current_reference": latest,
        "data_as_of": completed.index[-1].date().isoformat(),
        "atr": atr,
        "targets": targets,
        "rr": rr,
        "weighted_rr": weighted,
        "fractions": fractions,
        "objectives": selected,
        "resistance_buffer_atr": 0.08,
        "projection_window_sessions": 20,
        "note": "Observed resistance preferred; measured-move objectives are labelled projections, not guaranteed resistance or forecasts.",
    }


def structure_plan(direction, entry, atr, zones, minimum_rr):
    if direction not in {"BUY", "SELL"} or not all(math.isfinite(v) and v > 0 for v in (entry, atr, minimum_rr)):
        raise ValueError("Invalid structure inputs")
    sign = 1 if direction == "BUY" else -1
    if any(not all(math.isfinite(float(z[key])) and float(z[key]) > 0 for key in ("low", "high"))
           or z["low"] > z["high"] for z in zones):
        raise ValueError("Invalid price zone")
    if any(z["low"] <= entry <= z["high"] for z in zones):
        raise ValueError("entry_inside_unresolved_price_zone")
    ahead = sorted([z for z in zones if (z["low"] > entry if sign == 1 else z["high"] < entry)],
                   key=lambda z: z["low"] if sign == 1 else -z["high"])
    behind = [z for z in zones if (z["high"] < entry if sign == 1 else z["low"] > entry)]
    if len(ahead) < 3 or not behind:
        raise ValueError("insufficient_confirmed_price_zones")
    anchor = max(behind, key=lambda z: z["high"]) if sign == 1 else min(behind, key=lambda z: z["low"])
    structural_stop = anchor["low"] - .25*atr if sign == 1 else anchor["high"] + .25*atr
    risk = max(abs(entry-structural_stop), 1.5*atr, .01*entry)
    if risk > 4*atr:
        raise ValueError("structural_stop_too_distant")
    stop = round(entry-sign*risk, 2)
    targets = [round((z["low"]-.15*atr) if sign == 1 else (z["high"]+.15*atr), 2) for z in ahead[:3]]
    rr = [sign*(target-entry)/abs(entry-stop) for target in targets]
    weighted = sum(rr)/3
    if min([stop]+targets) <= 0 or not (1 <= rr[0] < rr[1] < rr[2]) or rr[1] < minimum_rr or weighted < minimum_rr:
        raise ValueError("price_structure_fails_risk_reward")
    return {"method": "confirmed_daily_swing_zones_v1", "entry": entry, "stop": stop,
            "targets": targets, "rr": rr, "weighted_rr": weighted, "minimum_rr": minimum_rr,
            "fractions": [.333333, .333333, .333334], "zones": ahead[:3], "stop_zone": anchor,
            "atr": atr, "target_buffer_atr": .15, "stop_buffer_atr": .25,
            "note": "Experimental observed price zones, not calibrated forecasts; equal quantity allocation."}


def validate_plan(plan, entry, stop, action):
    rebuilt = structure_plan(action, entry, float(plan["atr"]),
                             [*plan["zones"], plan["stop_zone"]], float(plan["minimum_rr"]))
    if stop != rebuilt["stop"] or plan["targets"] != rebuilt["targets"]:
        raise ValueError("Structure plan price mismatch")
    return rebuilt
