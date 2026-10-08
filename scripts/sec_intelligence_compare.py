"""Read-only forward comparison of retained SEC candidate rankings.

No historical SEC state is reconstructed. A hypothetical selection is not a
fill or a trade; outcome metrics are reported only for executed Native trades.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service" / "server"))
from database import get_db_connection, using_postgres
from signal_research import outcome


def compare(conn, since: str) -> dict:
    rows = [dict(r) for r in conn.execute("""SELECT scan_id,ticker,mode,baseline_rank_score,
        insider_adjustment,filing_adjustment,sec_adjustment,sec_snapshot_id,
        rejection_reason,shortlist_limit
        FROM si_decisions WHERE decided_at>=? ORDER BY scan_id,ticker LIMIT 50001""", (since,))]
    clipped = len(rows) > 50000
    rows = rows[:50000]
    scans: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        scans[row["scan_id"]].append(row)
    changes = {name: {"selected": 0, "changed_vs_baseline": 0, "new_tickers": []}
               for name in ("baseline", "insider_only", "filing_only", "combined")}
    for scan_id, candidates in scans.items():
        limit = int(candidates[0]["shortlist_limit"])
        def choose(component: str):
            return [r["ticker"] for r in sorted(candidates, key=lambda r: (
                float(r["baseline_rank_score"]) + (0 if component == "baseline" else
                    float(r["insider_adjustment"]) if component == "insider_only" else
                    float(r["filing_adjustment"]) if component == "filing_only" else
                    float(r["sec_adjustment"])), r["ticker"]), reverse=True)[:limit]]
        baseline = set(choose("baseline"))
        for name in changes:
            selected = set(choose(name))
            extra = sorted(selected - baseline)
            changes[name]["selected"] += len(selected)
            changes[name]["changed_vs_baseline"] += len(extra)
            changes[name]["new_tickers"].extend(extra[:10])
    for item in changes.values():
        item["new_tickers"] = sorted(set(item["new_tickers"]))[:20]
    trades = [dict(r) for r in conn.execute("""SELECT * FROM scanner_trades
        WHERE opened_at>=? AND is_shadow=0 AND legacy_position_id IS NULL
        ORDER BY id DESC LIMIT 5001""", (since,))]
    trade_clipped = len(trades) > 5000
    trades = trades[:5000]
    fills = defaultdict(list)
    for trade in trades:
        fills[trade["id"]] = [dict(r) for r in conn.execute(
            "SELECT * FROM scanner_fills WHERE trade_id=? ORDER BY id", (trade["id"],))]
    actual = [outcome(t, fills[t["id"]]) for t in trades]
    closed = [row for row in actual if row["closed_net_pct"] is not None]
    return {"window_since": since, "scans": len(scans), "candidate_observations": len(rows),
            "candidate_rows_clipped": clipped, "trade_rows_clipped": trade_clipped,
            "coverage": {"verified_snapshot_candidate_observations": sum(bool(r["sec_snapshot_id"]) for r in rows),
                         "unknown_snapshot_candidate_observations": sum(not r["sec_snapshot_id"] for r in rows),
                         "influenced_candidate_observations": sum(bool(r["sec_adjustment"]) for r in rows),
                         "rejection_reasons": dict(Counter(
                             r["rejection_reason"] for r in rows if r["rejection_reason"]))},
            "selection_comparison": changes,
            "actual_native_only": {"executed_trades": len(trades), "verified_closed": len(closed),
                "mean_net_pct": sum(r["closed_net_pct"] for r in closed)/len(closed) if closed else None,
                "mean_net_r": sum(r["closed_net_r"] for r in closed)/len(closed) if closed else None,
                "mean_fee_pct": sum(r["fee_pct"] for r in closed)/len(closed) if closed else None},
            "counterfactual_trade_count": None, "counterfactual_net_results": None,
            "counterfactual_drawdown": None, "counterfactual_ai_cost": None,
            "limitation": "Selection changes are forward retained ranks only. Unselected names have no natural AI/order/fill outcomes; no counterfactual returns or equity drawdown are inferred."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=168)
    args = parser.parse_args()
    if not 1 <= args.hours <= 2160:
        parser.error("hours must be 1..2160")
    with get_db_connection() as connection:
        if using_postgres():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            connection.execute("SET LOCAL statement_timeout='15s'")
        else:
            connection.execute("PRAGMA query_only=ON")
        result = compare(connection, (datetime.now(timezone.utc)-timedelta(hours=args.hours)).isoformat())
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
