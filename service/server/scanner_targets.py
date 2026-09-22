"""Deterministic daily swing-zone targets; experimental, not price forecasts."""
import math
from datetime import datetime, timezone


def swing_zones(frame, atr):
    # Only completed daily bars; two later bars must confirm each pivot.
    today = datetime.now(timezone.utc).date()
    frame = frame[[stamp.date() < today for stamp in frame.index]].tail(126)
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
