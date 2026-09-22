"""Real OHLC charts for executed paper entries; no image-generation model."""
import io
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
CHART_CACHE = ROOT / ".runtime" / "entry-charts"


def render_entry_chart(trade, frame):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import Rectangle

    opened = pd.Timestamp(trade["opened_at"])
    if opened.tzinfo is None:
        opened = opened.tz_localize("UTC")
    frame = frame.copy().sort_index()
    frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    # Only completed candles known before the recorded entry event.
    frame = frame[frame.index + pd.Timedelta(minutes=15) <= opened].tail(90)
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
    if len(frame) < 10 or (opened-frame.index[-1]).total_seconds() > 4*86400:
        raise ValueError("Insufficient recent chart data")
    levels = [("Actual entry", float(trade["entry_price"]), "#ffcd57", "-"),
              ("Original SL", float(trade["original_stop"]), "#ff6677", "-")]
    for i in (1,2,3):
        shadow = trade["strategy"] == "single" and i != 2
        levels.append((f"TP{i}" + (" (shadow)" if shadow else ""), float(trade[f"tp{i}"]), "#45d6bd", "--" if shadow else "-"))
    if not all(math.isfinite(price) and price > 0 for _,price,_,_ in levels):
        raise ValueError("Invalid trade levels")
    fig = Figure(figsize=(12,7), dpi=120, facecolor="#101b25")
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111, facecolor="#101b25")
    for i, (_, row) in enumerate(frame.iterrows()):
        o,h,l,c = [float(row[key]) for key in ("Open","High","Low","Close")]
        if not all(math.isfinite(v) and v > 0 for v in (o,h,l,c)) or not l <= min(o,c) <= max(o,c) <= h:
            raise ValueError("Invalid chart candle")
        color = "#45d6bd" if c >= o else "#ff6677"
        ax.vlines(i,l,h,color=color,linewidth=1)
        ax.add_patch(Rectangle((i-.3,min(o,c)),.6,max(abs(c-o), c*.00005),facecolor=color))
    for label,price,color,style in levels:
        ax.axhline(price,color=color,linestyle=style,linewidth=1,alpha=.85)
        ax.annotate(f"{label}: ${price:.2f}", xy=(1,price), xycoords=("axes fraction","data"),
                    xytext=(8,0),textcoords="offset points",color=color,fontsize=10,va="center")
    ax.scatter([len(frame)], [float(trade["entry_price"])], marker="^",s=110,color="#ffcd57",zorder=5)
    ax.axvline(len(frame),color="#ffcd57",alpha=.4,linestyle=":")
    ticks = list(range(0,len(frame),max(1,len(frame)//6)))
    ax.set_xticks(ticks,[frame.index[i].tz_convert("America/New_York").strftime("%m/%d\n%H:%M") for i in ticks])
    ax.set_xlim(-1,len(frame)+3)
    ax.tick_params(colors="#cbd5e1")
    ax.grid(alpha=.12,color="white")
    ax.set_ylabel("USD",color="#cbd5e1")
    for spine in ax.spines.values():
        spine.set_color("#405365")
    ax.set_title(f"{trade['ticker']} | PAPER ENTRY | 15-minute candles",color="white",loc="left",pad=18)
    fig.text(.08,.025,f"Entry: {opened.strftime('%Y-%m-%d %H:%M %Z')} | Yahoo Finance (may be delayed)\n"
             "Candles precede entry; triangle = actual simulated fill. Targets are not forecasts. Times on axis: New York.",
             color="#aebccc",fontsize=9)
    fig.subplots_adjust(left=.08,right=.77,top=.88,bottom=.15)
    output = io.BytesIO(); canvas.print_png(output)
    return output.getvalue()


def entry_chart_bytes(trade):
    CHART_CACHE.mkdir(parents=True, exist_ok=True)
    file = CHART_CACHE / f"trade-{int(trade['id'])}-entry-v1.png"
    if file.exists():
        return file.read_bytes()
    frame = yf.Ticker(trade["ticker"]).history(period="1mo",interval="15m",prepost=False,auto_adjust=True,timeout=15)
    if frame is None or frame.empty:
        raise ValueError("Chart provider unavailable")
    png = render_entry_chart(trade,frame)
    temporary = file.with_suffix(".tmp")
    temporary.write_bytes(png); temporary.replace(file)
    return png


def send_entry_chart(trade_id):
    from database import get_db_connection
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM scanner_trades WHERE id=? AND is_shadow=0 AND legacy_position_id IS NULL", (int(trade_id),)).fetchone()
    conn.close()
    if not row:
        return "chart_unavailable"
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return "missing_credentials"
    trade = dict(row)
    try:
        png = entry_chart_bytes(trade)
        caption = (f"{trade['ticker']} — גרף כניסה לעסקת דמו בלבד\n\n"
                   f"כניסה בפועל: ${trade['entry_price']:.2f}\nסטופ מקורי: ${trade['original_stop']:.2f}\n"
                   + "\n".join(f"TP{i}: ${trade[f'tp{i}']:.2f}" for i in (1,2,3))
                   + ("\n\nיעד פעיל יחיד: TP2. ‏TP1 ו־TP3 מסומנים להשוואת Shadow בלבד." if trade["strategy"] == "single" else "\n\nאסטרטגיה פעילה: מימוש מדורג.")
                   + "\nהנרות לפני הכניסה; המשולש מסמן ביצוע מדומה. נתוני Yahoo עשויים להיות מושהים.")
        session = requests.Session(); session.trust_env = False
        response = session.post(f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id":chat,"caption":caption},files={"photo":("entry.png",png,"image/png")},timeout=20)
        result = response.json()
        return "sent" if response.ok and result.get("ok") and str(result.get("result",{}).get("chat",{}).get("id")) == chat else "failed"
    except Exception:
        return "failed"  # Never log a request URL containing the token.
