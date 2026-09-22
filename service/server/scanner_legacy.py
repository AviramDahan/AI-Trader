"""Audited, forward-only adoption of original scanner paper positions.

No historical fills are replayed. Original cash/positions remain the legacy
wallet, separate from the new verified account. Only structured persisted
evidence may supply the original entry, quantity, stop and single target.
"""
from __future__ import annotations

import math

from database import begin_write_transaction, get_db_connection


def _insert(cur, table, values):
    columns = list(values)
    cur.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(values[key] for key in columns))
    return int(cur.lastrowid)


def audit_positions(cur=None):
    from scanner_engine import scanner_agent_id, _loads, parse_time
    conn = get_db_connection() if cur is None else None
    cur = cur or conn.cursor()
    agent_id = scanner_agent_id(cur)
    cur.execute("SELECT * FROM positions WHERE agent_id=? AND quantity>0 ORDER BY id", (agent_id,))
    positions = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT payload_json FROM scanner_legacy_records WHERE source='stock-scanner.json'")
    tracked = [_loads(row["payload_json"], {}) for row in cur.fetchall()]
    report = []
    for position in positions:
        try:
            cur.execute("SELECT trade_id,adopted_at FROM scanner_legacy_adoptions WHERE position_id=?", (position["id"],))
            adopted = cur.fetchone()
        except Exception:
            adopted = None  # Read-only pre-migration audit on the older schema.
        result = {"position": position, "eligible": False, "issues": []}
        cur.execute("SELECT cash FROM agents WHERE id=?", (agent_id,))
        result["original_wallet_cash"] = float(cur.fetchone()["cash"])
        if adopted:
            result.update(adopted=dict(adopted))
            report.append(result)
            continue
        matches = [item for item in tracked if item.get("ticker") == position["symbol"]
                   and item.get("action") == "BUY" and item.get("paper_execution") == "long_opened"]
        if len(matches) != 1:
            result["issues"].append("missing_or_ambiguous_structured_tracking")
        else:
            item = matches[0]
            result["tracking"] = item
            cur.execute("SELECT * FROM signals WHERE agent_id=? AND signal_id=?",
                        (agent_id, item.get("signal_id")))
            source = cur.fetchone()
            if not source:
                result["issues"].append("missing_executed_signal")
            else:
                source = dict(source)
                result["source_signal"] = source
                try:
                    numeric = [float(item[key]) for key in ("entry", "stop_loss", "take_profit", "paper_quantity")]
                    entry, stop, target, qty = numeric
                    valid = (all(math.isfinite(v) and v > 0 for v in numeric)
                             and stop < entry < target and position["market"] == "us-stock"
                             and position["side"] == "long" and source["side"] == "buy"
                             and source["symbol"] == position["symbol"] and source["exit_price"] is None
                             and item.get("status") == "OPEN"
                             and math.isclose(entry, float(position["entry_price"]), rel_tol=1e-7)
                             and math.isclose(entry, float(source["entry_price"]), rel_tol=1e-7)
                             and math.isclose(qty, float(position["quantity"]), abs_tol=1e-6)
                             and math.isclose(qty, float(source["quantity"]), abs_tol=1e-6)
                             and abs((parse_time(source["executed_at"]) - parse_time(position["opened_at"])).total_seconds()) < 2)
                    if not valid:
                        result["issues"].append("inconsistent_execution_evidence")
                except (KeyError, TypeError, ValueError):
                    result["issues"].append("invalid_execution_evidence")
        cur.execute("SELECT id FROM scanner_trades WHERE ticker=? AND status='open'", (position["symbol"],))
        if cur.fetchone():
            result["issues"].append("already_has_lifecycle_trade")
        cur.execute("""SELECT o.id FROM scanner_orders o JOIN scanner_signals s ON s.id=o.signal_id
                       WHERE s.ticker=? AND o.status='pending'""", (position["symbol"],))
        if cur.fetchone():
            result["issues"].append("already_has_pending_order")
        result["eligible"] = not result["issues"]
        report.append(result)
    if conn:
        conn.close()
    return report


def adopt_positions():
    """All-or-nothing, idempotent adoption; callers back up first and stop workers."""
    from scanner_engine import lifecycle_settings, now_z, _json, parse_time
    cfg = lifecycle_settings()
    stamp = now_z()
    dt = parse_time(stamp)
    cursor_at = dt.replace(minute=dt.minute // 5 * 5, second=0, microsecond=0).isoformat()
    conn = get_db_connection(); cur = conn.cursor()
    try:
        begin_write_transaction(cur)
        report = audit_positions(cur)
        unresolved = [row for row in report if not row.get("adopted") and not row["eligible"]]
        if unresolved:
            raise ValueError("Adoption blocked: " + "; ".join(
                row["position"]["symbol"] + ":" + ",".join(row["issues"]) for row in unresolved))
        adopted = []
        for row in report:
            if row.get("adopted"):
                continue
            p, item, source = row["position"], row["tracking"], row["source_signal"]
            entry, stop, target, qty = float(p["entry_price"]), float(item["stop_loss"]), float(item["take_profit"]), float(p["quantity"])
            risk = entry - stop
            snapshot = dict(cfg, strategy="single", legacy_unverified=True, managed_from=stamp,
                            entry_costs_known=False, historical_fills_reconstructed=False,
                            original_target=target, accounting_wallet="original_agents_cash",
                            management_policy="forward_only_original_stop_and_target")
            signal_id = _insert(cur, "scanner_signals", dict(
                external_signal_id=source["signal_id"], agent_id=p["agent_id"], scan_id=f"legacy:{p['id']}",
                ticker=p["symbol"], company=item.get("company") or p["symbol"], action="BUY", status="ENTERED",
                planned_entry=entry, actual_entry=entry, entry_type="legacy_executed", valid_until=stamp,
                original_stop=stop, current_stop=stop, tp1=entry+risk, tp2=target, tp3=entry+3*risk,
                tp1_pct=0, tp2_pct=1, tp3_pct=0, rr1=1, rr2=(target-entry)/risk, rr3=3,
                weighted_rr=(target-entry)/risk, confidence=float(item.get("confidence") or 0),
                confidence_basis=_json({"label": "Legacy score, unverified; excluded from statistics"}),
                time_horizon=item.get("time_horizon") or "legacy", reason=item.get("reason") or "",
                reason_he=item.get("telegram_reason_he") or "עסקה ישנה שהועברה לניהול מכאן והלאה. היסטוריית הביצועים אינה מאומתת.",
                news_json=_json(item.get("relevant_news") or []), technical_json="{}", market_context_json="{}",
                created_at=p["opened_at"], updated_at=stamp, legacy_unverified=1))
            order_id = _insert(cur, "scanner_orders", dict(
                signal_id=signal_id, client_order_key=f"legacy:{p['id']}", purpose="legacy_adoption", side="buy",
                order_type="historical_record", limit_price=entry, quantity=qty, filled_quantity=qty,
                average_fill_price=entry, status="imported", valid_until=stamp, created_at=stamp, updated_at=stamp))
            trade_id = _insert(cur, "scanner_trades", dict(
                signal_id=signal_id, order_id=order_id, agent_id=p["agent_id"], ticker=p["symbol"],
                company=item.get("company") or p["symbol"], side="long", strategy="single", is_shadow=0, status="open",
                original_quantity=qty, remaining_quantity=qty, entry_price=entry, original_stop=stop, current_stop=stop,
                original_r=risk, tp1=entry+risk, tp2=target, tp3=entry+3*risk, tp1_pct=0, tp2_pct=1, tp3_pct=0,
                settings_json=_json(snapshot), opened_at=p["opened_at"], last_price=p.get("current_price") or entry,
                unrealized_pnl=((p.get("current_price") or entry)-entry)*qty,
                last_bar_at=cursor_at, legacy_position_id=p["id"], managed_from=stamp))
            _insert(cur, "scanner_legacy_adoptions", dict(position_id=p["id"], trade_id=trade_id,
                adopted_at=stamp, evidence_json=_json(row)))
            cur.execute("""INSERT INTO scanner_price_cursors(ticker,last_bar_at,status,last_attempt_at)
                           VALUES(?,?,'waiting',?) ON CONFLICT(ticker) DO UPDATE SET last_bar_at=excluded.last_bar_at,
                           status='waiting',last_attempt_at=excluded.last_attempt_at,error=NULL""", (p["symbol"], cursor_at, stamp))
            cur.execute("""INSERT INTO scanner_news_schedule(ticker,next_due_at,status) VALUES(?,?,'due')
                           ON CONFLICT(ticker) DO UPDATE SET next_due_at=excluded.next_due_at,status='due',error=NULL""", (p["symbol"], stamp))
            adopted.append({"ticker": p["symbol"], "position_id": p["id"], "trade_id": trade_id})
        conn.commit()
        return {"adopted": adopted, "managed_from": stamp, "policy": "forward_only", "new_entry_alerts": 0}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
