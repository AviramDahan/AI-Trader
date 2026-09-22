"""Dry-run or apply chart-structured targets to currently open paper trades.

The script never changes entry, quantity, stop, original R, fills or accounting.
It refuses positions that already have a TP fill and records every applied change
in ``scanner_target_revisions``. The default mode is read-only.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "service" / "server"
sys.path.insert(0, str(SERVER_DIR))

import database  # noqa: E402
from scanner_engine import market_session_state, now_z  # noqa: E402
from scanner_targets import open_position_target_plan  # noqa: E402


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _decode(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError):
        return default


def _download(symbols: list[str]) -> dict[str, pd.DataFrame]:
    raw = yf.download(
        symbols,
        period="5y",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
        timeout=30,
    )
    frames = {}
    for symbol in symbols:
        try:
            frame = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
            frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["High", "Low", "Close"])
            if len(frame) >= 65:
                frames[symbol] = frame
        except (KeyError, TypeError):
            continue
    if set(frames) != set(symbols):
        missing = sorted(set(symbols).difference(frames))
        raise RuntimeError(f"Fresh daily history incomplete; missing: {', '.join(missing)}")
    session_state = market_session_state()
    if session_state["is_open"]:
        raise RuntimeError("US market is open; current-position targets may only be revised after the close")
    intraday = yf.download(
        symbols,
        period="5d",
        interval="5m",
        group_by="ticker",
        auto_adjust=True,
        prepost=False,
        progress=False,
        threads=True,
        timeout=30,
    )
    for symbol, daily in frames.items():
        try:
            bars = intraday[symbol] if isinstance(intraday.columns, pd.MultiIndex) else intraday
            bars = bars[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["High", "Low", "Close"])
            dates = pd.Index([pd.Timestamp(stamp).date() for stamp in bars.index])
            latest_date = max(dates)
            current_session = bars[dates == latest_date]
            if latest_date > pd.Timestamp(daily.index[-1]).date() and len(current_session) >= 35:
                daily.loc[pd.Timestamp(latest_date)] = {
                    "Open": float(current_session["Open"].iloc[0]),
                    "High": float(current_session["High"].max()),
                    "Low": float(current_session["Low"].min()),
                    "Close": float(current_session["Close"].iloc[-1]),
                    "Volume": float(current_session["Volume"].sum()),
                }
                frames[symbol] = daily.sort_index()
        except (KeyError, TypeError, ValueError):
            continue
    return frames


def _load_open_groups(conn) -> dict[int, list[dict]]:
    rows = conn.execute(
        """SELECT t.*,s.tp1 AS signal_tp1,s.tp2 AS signal_tp2,s.tp3 AS signal_tp3,
                  s.tp1_pct AS signal_tp1_pct,s.tp2_pct AS signal_tp2_pct,s.tp3_pct AS signal_tp3_pct,
                  s.technical_json
             FROM scanner_trades t JOIN scanner_signals s ON s.id=t.signal_id
            WHERE t.status='open' ORDER BY t.signal_id,t.is_shadow,t.id"""
    ).fetchall()
    groups: dict[int, list[dict]] = {}
    for row in rows:
        item = dict(row)
        groups.setdefault(int(item["signal_id"]), []).append(item)
    return groups


def _build_plans(groups: dict[int, list[dict]], frames: dict[str, pd.DataFrame]) -> dict[int, dict]:
    plans = {}
    today = datetime.now(timezone.utc).date()
    for signal_id, trades in groups.items():
        primary = next((trade for trade in trades if not int(trade["is_shadow"])), trades[0])
        frame = frames[primary["ticker"]]
        data_date = pd.Timestamp(frame.index[-1]).date()
        if (today - data_date).days > 4:
            raise RuntimeError(f"{primary['ticker']}: daily history is stale ({data_date})")
        fractions = [primary[f"signal_tp{i}_pct"] for i in (1, 2, 3)]
        plan = open_position_target_plan(
            frame,
            entry=float(primary["entry_price"]),
            stop=float(primary["original_stop"]),
            fractions=fractions,
            current_price=float(primary["last_price"] or 0),
        )
        plans[signal_id] = plan
    return plans


def _print_plans(groups: dict[int, list[dict]], plans: dict[int, dict]) -> None:
    for signal_id, trades in groups.items():
        primary = next((trade for trade in trades if not int(trade["is_shadow"])), trades[0])
        plan = plans[signal_id]
        sources = ",".join(
            (f"R[{item['zone']['low']:.2f}-{item['zone']['high']:.2f};touches={item['zone']['touches']}]"
             if item["source"] == "confirmed_daily_resistance"
             else f"MM[{item['ratio']:.3f}x;range={item['range_low']:.2f}-{item['range_high']:.2f}]")
            for item in plan["objectives"]
        )
        before = [float(primary[f"tp{i}"]) for i in (1, 2, 3)]
        print(
            f"{primary['ticker']}: old={','.join(f'{v:.2f}' for v in before)} "
            f"new={','.join(f'{v:.2f}' for v in plan['targets'])} "
            f"rr={','.join(f'{v:.2f}' for v in plan['rr'])} as_of={plan['data_as_of']} sources={sources}"
        )


def _backup_sqlite() -> Path:
    if database.using_postgres():
        raise RuntimeError("Automatic target revision requires an external PostgreSQL backup first")
    source = Path(database._SQLITE_DB_PATH).resolve()
    if not source.is_relative_to(ROOT.resolve()):
        raise RuntimeError("Refusing to back up a database outside the workspace")
    backup_dir = ROOT / ".runtime" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"clawtrader-before-target-revision-{stamp}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    return destination


def _apply(groups: dict[int, list[dict]], plans: dict[int, dict], requested_by: str) -> int:
    backup = _backup_sqlite()
    conn = database.get_db_connection()
    cur = conn.cursor()
    changed = 0
    try:
        database.begin_write_transaction(cur)
        for signal_id, trades in groups.items():
            cur.execute(
                "SELECT COUNT(*) AS count FROM scanner_fills WHERE trade_id IN (SELECT id FROM scanner_trades WHERE signal_id=?) AND fill_type='tp'",
                (signal_id,),
            )
            if int(cur.fetchone()["count"] or 0):
                raise RuntimeError(f"Signal {signal_id} already has a TP fill; targets were not changed")
            cur.execute("SELECT status,technical_json,tp1,tp2,tp3,tp1_pct,tp2_pct,tp3_pct FROM scanner_signals WHERE id=?", (signal_id,))
            signal = dict(cur.fetchone())
            if signal["status"] not in {"ENTERED", "ACTIVE", "PENDING_ENTRY"}:
                raise RuntimeError(f"Signal {signal_id} is no longer eligible")
            plan = plans[signal_id]
            targets = [float(value) for value in plan["targets"]]
            previous_signal_targets = [float(signal[f"tp{i}"]) for i in (1, 2, 3)]
            if all(math.isclose(old, new, abs_tol=0.005) for old, new in zip(previous_signal_targets, targets)):
                continue
            fractions = [float(signal[f"tp{i}_pct"]) for i in (1, 2, 3)]
            technical = _decode(signal["technical_json"], {})
            technical["target_plan"] = plan
            technical["target_revision"] = {
                "applied_at": now_z(),
                "requested_by": requested_by,
                "previous_targets": previous_signal_targets,
            }
            stamp = now_z()
            cur.execute(
                """UPDATE scanner_signals
                      SET tp1=?,tp2=?,tp3=?,rr1=?,rr2=?,rr3=?,weighted_rr=?,technical_json=?,updated_at=?
                    WHERE id=?""",
                (*targets, *plan["rr"], sum(r * f for r, f in zip(plan["rr"], fractions)), _json(technical), stamp, signal_id),
            )
            for trade in trades:
                previous = {
                    "tp1": float(trade["tp1"]),
                    "tp2": float(trade["tp2"]),
                    "tp3": float(trade["tp3"]),
                    "settings_target_plan": _decode(trade["settings_json"], {}).get("target_plan"),
                }
                revised = {"tp1": targets[0], "tp2": targets[1], "tp3": targets[2]}
                settings = _decode(trade["settings_json"], {})
                settings["target_plan"] = plan
                settings["target_revision"] = {
                    "applied_at": stamp,
                    "requested_by": requested_by,
                    "previous_targets": [previous["tp1"], previous["tp2"], previous["tp3"]],
                    "preserved_entry": float(trade["entry_price"]),
                    "preserved_original_stop": float(trade["original_stop"]),
                    "preserved_original_r": float(trade["original_r"]),
                }
                cur.execute(
                    "UPDATE scanner_trades SET tp1=?,tp2=?,tp3=?,settings_json=? WHERE id=? AND status='open'",
                    (*targets, _json(settings), trade["id"]),
                )
                cur.execute(
                    """INSERT INTO scanner_target_revisions(
                           trade_id,signal_id,applied_at,requested_by,method,data_as_of,
                           previous_json,revised_json,evidence_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        trade["id"], signal_id, stamp, requested_by, plan["method"], plan["data_as_of"],
                        _json(previous), _json(revised), _json(plan),
                    ),
                )
                changed += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"Applied {changed} trade target revision(s). Backup: {backup}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply after showing the complete dry-run plan")
    parser.add_argument("--requested-by", default="manual-user-request", help="Non-secret audit label")
    args = parser.parse_args()

    database.init_database()
    if args.apply and market_session_state()["is_open"]:
        raise SystemExit("Refusing to revise targets while the US market is open.")
    conn = database.get_db_connection()
    conn.row_factory = getattr(conn, "row_factory", None) or sqlite3.Row
    groups = _load_open_groups(conn)
    conn.close()
    if not groups:
        print("No open paper trades.")
        return 0
    tickers = sorted({trades[0]["ticker"] for trades in groups.values()})
    frames = _download(tickers)
    plans = _build_plans(groups, frames)
    _print_plans(groups, plans)
    if not args.apply:
        print("DRY RUN ONLY. Re-run with --apply after review.")
        return 0
    _apply(groups, plans, args.requested_by.strip() or "manual-user-request")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
