"""Cached daily OHLC charts for paper positions and scanner signals."""

from __future__ import annotations

import hashlib
import io
import json
import math
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from database import get_db_connection
from scanner_engine import market_session_state


ROOT = Path(__file__).resolve().parents[2]
CHART_CACHE = ROOT / ".runtime" / "position-charts"
SIGNAL_CHART_CACHE = ROOT / ".runtime" / "signal-charts"
ET = ZoneInfo("America/New_York")


def _loads(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


def _completed_daily(frame: pd.DataFrame) -> pd.DataFrame:
    now_et = datetime.now(timezone.utc).astimezone(ET)
    cutoff = now_et.date() + timedelta(days=1) if now_et.time() >= time(16, 5) else now_et.date()
    return frame[[pd.Timestamp(stamp).date() < cutoff for stamp in frame.index]]


def _download_daily(ticker: str) -> pd.DataFrame:
    daily = yf.Ticker(ticker).history(period="6mo", interval="1d", prepost=False, auto_adjust=True, timeout=20)
    if daily is None or daily.empty:
        raise ValueError("Daily chart provider unavailable")
    daily = daily[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
    if not market_session_state()["is_open"]:
        intraday = yf.Ticker(ticker).history(period="5d", interval="5m", prepost=False, auto_adjust=True, timeout=20)
        if intraday is not None and not intraday.empty:
            dates = pd.Index([pd.Timestamp(stamp).date() for stamp in intraday.index])
            latest_date = max(dates)
            latest = intraday[dates == latest_date].dropna(subset=["Open", "High", "Low", "Close"])
            if latest_date > pd.Timestamp(daily.index[-1]).date() and len(latest) >= 35:
                stamp = pd.Timestamp(latest_date, tz=getattr(daily.index, "tz", None))
                daily.loc[stamp] = {
                    "Open": float(latest["Open"].iloc[0]),
                    "High": float(latest["High"].max()),
                    "Low": float(latest["Low"].min()),
                    "Close": float(latest["Close"].iloc[-1]),
                    "Volume": float(latest["Volume"].sum()),
                }
    frame = _completed_daily(daily).sort_index().tail(90)
    if len(frame) < 30:
        raise ValueError("Insufficient completed daily chart data")
    return frame


def operational_allocations(trade: dict) -> list[float]:
    if trade["strategy"] == "single":
        return [0.0, 1.0, 0.0]
    return [float(trade[f"tp{i}_pct"]) for i in (1, 2, 3)]


def signal_chart_record(signal: dict, strategy: str) -> dict:
    filled = signal.get("actual_entry") is not None
    return {
        **signal,
        "strategy": strategy,
        "entry_price": float(signal["actual_entry"] if filled else signal["planned_entry"]),
        "entry_label": "Actual paper entry" if filled else "Planned entry (not filled)",
        "entry_note": "Triangle = actual simulated fill." if filled else "Triangle = planned entry; no fill has occurred.",
        "opened_at": signal["created_at"],
        "chart_kind": "SIGNAL",
    }


def render_position_chart(trade: dict, frame: pd.DataFrame) -> bytes:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    frame = frame.copy().sort_index().dropna(subset=["Open", "High", "Low", "Close"]).tail(90)
    if len(frame) < 10:
        raise ValueError("Insufficient position chart data")
    allocations = operational_allocations(trade)
    levels = [
        (str(trade.get("entry_label") or "Entry"), float(trade["entry_price"]), "#ffcd57", "-"),
        ("SL", float(trade["current_stop"]), "#ff6677", "-"),
    ]
    for index, allocation in enumerate(allocations, 1):
        active = allocation > 0
        target = float(trade[f"tp{index}"])
        price_move = target / float(trade["entry_price"]) - 1
        levels.append((
            f"TP{index} ({price_move:+.1%} move, {allocation:.0%}{' active' if active else ' shadow'})",
            target,
            "#45d6bd",
            "-" if active else "--",
        ))
    if not all(math.isfinite(price) and price > 0 for _, price, _, _ in levels):
        raise ValueError("Invalid position chart levels")

    fig = Figure(figsize=(12, 7), dpi=120, facecolor="#101b25")
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111, facecolor="#101b25")
    for index, (_, row) in enumerate(frame.iterrows()):
        opening, high, low, close = [float(row[key]) for key in ("Open", "High", "Low", "Close")]
        if (not all(math.isfinite(value) and value > 0 for value in (opening, high, low, close))
                or high < max(opening, close) or low > min(opening, close) or high < low):
            raise ValueError("Invalid chart candle")
        color = "#45d6bd" if close >= opening else "#ff6677"
        ax.vlines(index, low, high, color=color, linewidth=1)
        ax.add_patch(Rectangle(
            (index - .3, min(opening, close)), .6, max(abs(close - opening), close * .00005),
            facecolor=color,
        ))
    for label, price, color, style in levels:
        ax.axhline(price, color=color, linestyle=style, linewidth=1.15, alpha=.9)
        ax.annotate(
            f"{label}: ${price:.2f}", xy=(1, price), xycoords=("axes fraction", "data"),
            xytext=(8, 0), textcoords="offset points", color=color, fontsize=9, va="center",
        )
    opened = pd.Timestamp(trade.get("opened_at") or trade.get("created_at"))
    entry_index = min(range(len(frame)), key=lambda i: abs(pd.Timestamp(frame.index[i]).date() - opened.date()))
    ax.scatter([entry_index], [float(trade["entry_price"])], marker="^", s=100, color="#ffcd57", zorder=5)
    ticks = list(range(0, len(frame), max(1, len(frame) // 6)))
    ax.set_xticks(ticks, [pd.Timestamp(frame.index[i]).strftime("%m/%d") for i in ticks])
    ax.set_xlim(-1, len(frame) + 3)
    ax.tick_params(colors="#cbd5e1")
    ax.grid(alpha=.12, color="white")
    ax.set_ylabel("USD", color="#cbd5e1")
    for spine in ax.spines.values():
        spine.set_color("#405365")
    chart_kind = str(trade.get("chart_kind") or "POSITION").upper()
    ax.set_title(f"{trade['ticker']} | PAPER {chart_kind} | Daily candles", color="white", loc="left", pad=18)
    as_of = pd.Timestamp(frame.index[-1]).date().isoformat()
    fig.text(
        .08, .025,
        f"Chart through {as_of} | Yahoo Finance (may be delayed)\n"
        f"{trade.get('entry_note') or 'Triangle = simulated entry.'} TP/SL levels are paper-tracking rules, not forecasts.",
        color="#aebccc", fontsize=9,
    )
    fig.subplots_adjust(left=.08, right=.76, top=.88, bottom=.13)
    output = io.BytesIO()
    canvas.print_png(output)
    return output.getvalue()


def position_chart_bytes(trade_id: int) -> bytes:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM scanner_trades WHERE id=? AND is_shadow=0 AND status='open'",
        (int(trade_id),),
    ).fetchone()
    conn.close()
    if not row:
        raise LookupError("Open primary paper trade not found")
    trade = dict(row)
    signature_values = {
        "renderer_version": 2,
        "entry": trade["entry_price"], "stop": trade["current_stop"],
        "tp1": trade["tp1"], "tp2": trade["tp2"], "tp3": trade["tp3"],
        "strategy": trade["strategy"], "last_bar_at": trade["last_bar_at"],
    }
    signature = hashlib.sha256(json.dumps(signature_values, sort_keys=True).encode()).hexdigest()[:12]
    CHART_CACHE.mkdir(parents=True, exist_ok=True)
    path = CHART_CACHE / f"trade-{int(trade_id)}-{signature}.png"
    if path.exists():
        return path.read_bytes()
    png = render_position_chart(trade, _download_daily(trade["ticker"]))
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(png)
    temporary.replace(path)
    return png


def signal_chart_bytes(signal_id: int) -> bytes:
    """Render a signal plan without implying that its planned entry was filled."""
    from scanner_engine import lifecycle_settings

    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM scanner_signals WHERE id=? AND legacy_unverified=0",
        (int(signal_id),),
    ).fetchone()
    if not row:
        conn.close()
        raise LookupError("Verified paper signal not found")
    signal = dict(row)
    linked = conn.execute(
        "SELECT strategy FROM scanner_trades WHERE signal_id=? AND is_shadow=0 ORDER BY id LIMIT 1",
        (int(signal_id),),
    ).fetchone()
    conn.close()
    strategy = linked["strategy"] if linked else lifecycle_settings()["active_strategy"]
    planned_entry = float(signal["actual_entry"] if signal["actual_entry"] is not None else signal["planned_entry"])
    chart_record = signal_chart_record(signal, strategy)
    signature_values = {
        "renderer_version": 3,
        "entry": planned_entry, "stop": signal["current_stop"],
        "tp1": signal["tp1"], "tp2": signal["tp2"], "tp3": signal["tp3"],
        "strategy": strategy, "updated_at": signal["updated_at"],
    }
    signature = hashlib.sha256(json.dumps(signature_values, sort_keys=True).encode()).hexdigest()[:12]
    SIGNAL_CHART_CACHE.mkdir(parents=True, exist_ok=True)
    path = SIGNAL_CHART_CACHE / f"signal-{int(signal_id)}-{signature}.png"
    if path.exists():
        return path.read_bytes()
    png = render_position_chart(chart_record, _download_daily(signal["ticker"]))
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(png)
    temporary.replace(path)
    return png
