"""Pure components extracted from pinned MIT TraderMonty source.

Upstream network/CLI, scoring, sizing and exit rules are intentionally excluded.
See PROVENANCE.json and LICENSE in this directory.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass

@dataclass
class Bar:
    """Normalized daily OHLCV bar."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class BaseProfile:
    """Prior-base metrics computed from bars before the trigger day."""

    prior_base_days: int
    base_width_pct: float
    avg_prior_range_pct: float
    volume_dry_up: bool


@dataclass
class TriggerProfile:
    """Trigger metrics for the latest bar."""

    trigger_tags: list[str]
    primary_trigger: str
    day_gain_pct: float
    dollar_gain: float
    current_range_pct: float
    current_range_dollars: float
    volume_ratio_1d: float
    volume_ratio_20d: float
    close_location_pct: float
    prev_day_gain_pct: float


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def pct_change(new: float, old: float) -> float:
    if old <= 0:
        return 0.0
    return ((new / old) - 1.0) * 100.0


def close_location_pct(bar: Bar) -> float:
    day_range = bar.high - bar.low
    if day_range <= 0:
        return 50.0
    return ((bar.close - bar.low) / day_range) * 100.0


def detect_base_profile(
    bars: list[Bar],
    min_base_days: int,
    max_base_days: int,
    max_base_width_pct: float,
    max_prior_avg_range_pct: float,
) -> BaseProfile:
    """Detect the best simple prior consolidation window before the trigger day."""
    if len(bars) < min_base_days + 2:
        return BaseProfile(0, 0.0, 0.0, False)

    best: BaseProfile | None = None
    longest_window = min(max_base_days, len(bars) - 1)
    for window in range(min_base_days, longest_window + 1):
        prior = bars[1 : 1 + window]
        ref_close = prior[0].close
        if ref_close <= 0:
            continue
        base_width_pct = (
            (max(b.high for b in prior) - min(b.low for b in prior)) / ref_close
        ) * 100
        avg_range_pct = average([((b.high - b.low) / b.close) * 100 for b in prior if b.close > 0])
        if base_width_pct <= max_base_width_pct and avg_range_pct <= max_prior_avg_range_pct:
            # Compare base volume with the older pre-base volume, when available.
            base_vol = average([float(b.volume) for b in prior])
            older = bars[1 + window : 1 + window * 2]
            older_vol = average([float(b.volume) for b in older]) if older else 0.0
            volume_dry_up = bool(older_vol and base_vol <= older_vol * 0.85)
            candidate = BaseProfile(window, base_width_pct, avg_range_pct, volume_dry_up)
            if best is None:
                best = candidate
            elif candidate.prior_base_days > best.prior_base_days:
                best = candidate
            elif (
                candidate.prior_base_days == best.prior_base_days
                and candidate.base_width_pct < best.base_width_pct
            ):
                best = candidate

    if best:
        return best

    fallback_window = min(longest_window, max(min_base_days, 1))
    prior = bars[1 : 1 + fallback_window]
    ref_close = prior[0].close if prior else 1.0
    width = (
        ((max(b.high for b in prior) - min(b.low for b in prior)) / ref_close) * 100
        if prior
        else 0.0
    )
    avg_range = average([((b.high - b.low) / b.close) * 100 for b in prior if b.close > 0])
    return BaseProfile(0, width, avg_range, False)


def detect_triggers(bars: list[Bar], args: argparse.Namespace) -> TriggerProfile:
    """Detect trigger tags and current-day metrics."""
    latest = bars[0]
    prev = bars[1]
    prior_2 = bars[2]
    day_gain_pct = pct_change(latest.close, prev.close)
    dollar_gain = latest.close - latest.open
    current_range = latest.high - latest.low
    current_range_pct = (current_range / latest.close) * 100 if latest.close > 0 else 0.0
    prior_ranges = [b.high - b.low for b in bars[1:4]]
    prior_range_max = max(prior_ranges) if prior_ranges else 0.0
    prev_day_gain_pct = pct_change(prev.close, prior_2.close)
    volume_ratio_1d = latest.volume / prev.volume if prev.volume > 0 else 0.0
    avg_vol_20 = average([float(b.volume) for b in bars[1:21]])
    volume_ratio_20d = latest.volume / avg_vol_20 if avg_vol_20 > 0 else 0.0

    trigger_tags: list[str] = []
    volume_floor_ok = latest.volume >= args.min_volume
    volume_expanded = latest.volume > prev.volume

    if day_gain_pct >= args.four_pct_threshold and volume_expanded and volume_floor_ok:
        trigger_tags.append("4pct_breakout")
    if dollar_gain >= args.dollar_threshold and volume_floor_ok:
        trigger_tags.append("dollar_breakout")
    if (
        current_range > prior_range_max
        and prev_day_gain_pct <= args.max_prev_day_gain_for_range
        and volume_expanded
        and volume_floor_ok
    ):
        trigger_tags.append("range_expansion")
    if latest.volume >= args.nine_million_volume:
        trigger_tags.append("9m_volume")

    primary_order = ["4pct_breakout", "range_expansion", "dollar_breakout", "9m_volume"]
    primary = next((tag for tag in primary_order if tag in trigger_tags), "none")

    return TriggerProfile(
        trigger_tags=trigger_tags,
        primary_trigger=primary,
        day_gain_pct=day_gain_pct,
        dollar_gain=dollar_gain,
        current_range_pct=current_range_pct,
        current_range_dollars=current_range,
        volume_ratio_1d=volume_ratio_1d,
        volume_ratio_20d=volume_ratio_20d,
        close_location_pct=close_location_pct(latest),
        prev_day_gain_pct=prev_day_gain_pct,
    )
