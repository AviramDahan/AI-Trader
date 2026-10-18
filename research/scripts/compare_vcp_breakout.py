"""Offline paired structural comparison, never an order/fill/profit backtester.

Accepts an explicit observation dataset or an existing scanner history cache.
The two arms share the exact source, decision/reference price and baseline target
builder. Candidate B can only FILTER an already-valid single_breakout_v1 plan.
No DB, HTTP, model, scanner worker, order-execution method or provider fetch is
called. The adapter/fixture may reuse the existing engine's pure session calendar.
Results go to stdout; raw cached OHLCV/quotes are not printed or copied.
"""
from __future__ import annotations

import argparse
# Initialize stdlib event-loop definitions before the offline subprocess guard;
# optional market-data packages import asyncio for type definitions, not fetching.
import asyncio
import base64
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, time, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import sys
from typing import Any
import zlib
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "service" / "server"
MAX_JSON = 16_000_000
MAX_OBSERVATIONS = 5000
MAX_BARS = 1024
STATES = {"UNKNOWN", "REJECTED", "FORMING", "CONFIRMED", "OVEREXTENDED"}
STRUCTURAL_REASONS = {
    "pre_nearest_resistance_below_2r", "pre_entry_inside_unresolved_price_zone",
    "pre_price_structure_fails_risk_reward", "pre_invalid_rounded_levels",
    "pre_insufficient_confirmed_price_zones", "pre_entry_not_above_completed_high",
}


def instant(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid_timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    return result.astimezone(timezone.utc)


def finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid_numeric_value")
    return float(value)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def strict_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def decode_json(raw: bytes) -> Any:
    if len(raw) > MAX_JSON:
        raise ValueError("input_size_limit")
    return json.loads(raw, object_pairs_hook=strict_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))


def read_json(path: str | Path) -> tuple[Any, str]:
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    return decode_json(raw), hashlib.sha256(raw).hexdigest()


@contextmanager
def offline_only():
    """Fail closed if a future import accidentally attempts network/subprocess IO."""
    def deny(*args, **kwargs):
        raise RuntimeError("comparison_forbids_network_and_subprocess")
    old = socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto, socket.create_connection, subprocess.Popen, subprocess.run
    socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = deny
    socket.create_connection = subprocess.Popen = subprocess.run = deny
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto, socket.create_connection, subprocess.Popen, subprocess.run = old


def pure_modules():
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    import pandas as pd
    import scanner_targets
    import single_target_policy
    import single_breakout_policy
    import vcp_breakout
    return pd, scanner_targets, single_target_policy, single_breakout_policy, vcp_breakout


def frame_from_record(row: dict):
    pd, _, _, _, _ = pure_modules()
    bars = row.get("bars")
    if bars is None:
        return None
    if not isinstance(bars, list) or not 1 <= len(bars) <= MAX_BARS:
        raise ValueError("invalid_bar_count")
    records, dates, selected_bars = [], [], []
    decision, observed = instant(row["decision_at"]), instant(row["source_observed_at"])
    for bar in bars:
        if not isinstance(bar, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(bar.get("date", ""))):
            raise ValueError("invalid_bar_date")
        values = [finite(bar[key]) for key in ("Open", "High", "Low", "Close", "Volume")]
        op, hi, lo, cl, vol = values
        if min(op, hi, lo, cl) <= 0 or vol < 0 or not lo <= min(op, cl) <= max(op, cl) <= hi:
            raise ValueError("invalid_OHLCV")
        dates.append(bar["date"])
        records.append(values)
    if dates != sorted(set(dates)):
        raise ValueError("bars_must_be_unique_chronological")
    frame = pd.DataFrame(records, columns=["Open", "High", "Low", "Close", "Volume"],
                         index=pd.to_datetime(dates))
    frame.attrs["history_fetched_at"] = observed.timestamp()
    # Preserve per-bar publication/availability if supplied; the adapter owns
    # authoritative as-of filtering and source availability validation.
    if any("available_at" in item for item in bars):
        if not all("available_at" in item for item in bars):
            raise ValueError("partial_bar_availability")
        frame["available_at"] = [item["available_at"] for item in bars]
        frame = frame[[instant(item["available_at"]) <= min(decision, observed) for item in bars]]
    # Both arms receive the same completed, observed-at-decision subset. Future
    # rows do not influence source-structure deduplication either.
    _, targets, _, _, _ = pure_modules()
    frame = targets._completed_daily(frame, decision)
    for date, values in frame.iterrows():
        selected_bars.append([date.date().isoformat()] + [float(values[key]) for key in ("Open", "High", "Low", "Close", "Volume")])
    frame.attrs["comparison_consumed_source_sha256"] = fingerprint(selected_bars)
    return frame


def baseline_structure(row: dict, frame=None) -> dict:
    """The real target builders only. Not technical/news/AI approval or a fill."""
    _, targets, v2, breakout, _ = pure_modules()
    decision = instant(row["decision_at"])
    observed = instant(row["source_observed_at"])
    if observed > decision:
        return {"status": "UNKNOWN", "reason": "source_observed_after_decision", "plan": None}
    if row.get("action", "BUY") != "BUY" or row.get("strategy", "single") != "single":
        return {"status": "NOT_APPLICABLE", "reason": "outside_BUY_SINGLE_scope", "plan": None}
    price = finite(row["reference_price"])
    if price <= 0:
        raise ValueError("nonpositive_reference_price")
    if row.get("reference_at") and instant(row["reference_at"]) > decision:
        return {"status": "UNKNOWN", "reason": "reference_after_decision", "plan": None}
    source = row.get("source_inputs")
    if source is None and frame is not None:
        completed = targets._completed_daily(frame, decision)
        if len(completed) >= 15:
            source = targets.single_source_structure(completed)
    if not isinstance(source, dict):
        return {"status": "UNKNOWN", "reason": "missing_retained_structure", "plan": None}
    source_at = source["data_as_of"]
    if len(source_at) == 10:
        source_at = datetime.combine(datetime.fromisoformat(source_at).date(), time(16, 5),
                                     ZoneInfo("America/New_York")).astimezone(timezone.utc)
    else:
        source_at = instant(source_at)
    if source_at > min(decision, observed):
        return {"status": "UNKNOWN", "reason": "source_not_available_at_observation", "plan": None}
    if frame is not None:
        completed = targets._completed_daily(frame, decision)
        if completed.empty or source_at.date() > completed.index[-1].date():
            return {"status": "UNKNOWN", "reason": "structure_after_available_history", "plan": None}
    completed_high = row.get("completed_high")
    if completed_high is None and frame is not None:
        completed = targets._completed_daily(frame, decision)
        if len(completed) >= 20:
            completed_high = float(completed["High"].tail(20).max())
    try:
        try:
            plan = v2.build(price, source["atr"], source["zones"], source["data_as_of"], row["decision_at"])
        except ValueError as exc:
            if str(exc) != "no_forward_zone":
                raise
            plan = breakout.build(price, source["atr"], source["zones"], source["data_as_of"],
                                  row["decision_at"], completed_high)
        return {"status": "APPROVED", "reason": None, "plan": plan}
    except ValueError as exc:
        return {"status": "REJECTED", "reason": str(exc), "plan": None}


def compare_row(row: dict, *, baseline_fn=None, evaluate_fn=None, validate_fn=None) -> dict:
    """Strict subset comparison; injectable pure functions support no-IO controls."""
    for field in ("observation_id", "ticker", "decision_at", "source_observed_at", "reference_kind"):
        if not isinstance(row.get(field), str) or not row[field] or len(row[field]) > 160:
            raise ValueError("missing_or_invalid_observation_field")
    if not re.fullmatch(r"[A-Z0-9.\-]{1,16}", row["ticker"]):
        raise ValueError("invalid_ticker")
    decision, observed = instant(row["decision_at"]), instant(row["source_observed_at"])
    if observed > decision:
        raise ValueError("source_observed_after_decision")
    if baseline_fn is None:
        _, _, _, breakout, vcp = pure_modules()
        frame = frame_from_record(row)
        baseline = baseline_structure(row, frame)
        evaluate_fn, validate_fn = vcp.evaluate, vcp.validate_trigger
        breakout_version = breakout.VERSION
    else:
        frame = row.get("bars")
        baseline = baseline_fn(row, frame)
        breakout_version = "single_breakout_v1"
    evidence = {"state": "UNKNOWN", "reasons": ["missing_retained_OHLCV"], "eligible": False}
    if frame is not None:
        evidence = evaluate_fn(frame, decision_at=row["decision_at"], source_observed_at=row["source_observed_at"])
        if evidence.get("state") not in STATES:
            raise ValueError("invalid_adapter_state")
    plan = baseline.get("plan")
    applicable = baseline["status"] == "APPROVED" and isinstance(plan, dict) and plan.get("policy_version") == breakout_version
    candidate_status, candidate_reason = baseline["status"], baseline.get("reason")
    if applicable:
        if evidence["state"] == "UNKNOWN":
            candidate_status, candidate_reason = "UNKNOWN", "vcp_missing_evidence"
        elif evidence["state"] != "CONFIRMED":
            candidate_status, candidate_reason = "REJECTED", "vcp_" + evidence["state"].lower()
        else:
            try:
                checked = validate_fn(evidence, row["reference_price"],
                                      row.get("reference_at", row["decision_at"]), row["decision_at"])
                if checked.get("state") != "CONFIRMED":
                    raise ValueError("vcp_trigger_not_confirmed")
            except ValueError as exc:
                candidate_status, candidate_reason = "REJECTED", str(exc)
    source_id = row.get("source_inputs_sha256")
    consumed_id = getattr(frame, "attrs", {}).get("comparison_consumed_source_sha256")
    if consumed_id:
        source_id = fingerprint({"retained_structure": source_id or row.get("source_inputs"), "completed_OHLCV": consumed_id})
    elif not source_id:
        source_id = fingerprint({"bars": row.get("bars"), "source_inputs": row.get("source_inputs")})
    setup_id = fingerprint([row["ticker"], row.get("action", "BUY"), row.get("strategy", "single"), source_id])
    return {"observation_id": row["observation_id"], "ticker": row["ticker"],
            "decision_at": row["decision_at"], "reference_kind": row["reference_kind"],
            "source_id": source_id, "unique_structure_id": setup_id,
            "unique_reference_configuration_id": fingerprint([setup_id, row["reference_price"]]),
            "baseline_status": baseline["status"], "baseline_reason": baseline.get("reason"),
            "baseline_policy_version": plan.get("policy_version") if isinstance(plan, dict) else None,
            "candidate_status": candidate_status, "candidate_reason": candidate_reason,
            "vcp_applies_to_saved_baseline_breakout": applicable,
            "vcp_state": evidence["state"],
            "vcp_reasons": evidence.get("reasons", []),
            "same_frozen_target_plan": True,
            "executed_trade": False, "AI_approval": "NOT_RECONSTRUCTED"}


def unavailable_performance() -> dict:
    return {"status": "DATA_INSUFFICIENT", "signal_to_entry_conversion": None,
            "closed_trades": None, "win_rate": None, "net_expectancy_R": None,
            "profit_factor": None, "maximum_drawdown": None, "average_holding_period": None,
            "why": "No complete historical AI/order/fill/fee/partial-exit ledger; no price-touch or intrabar path invented.",
            "minimum_evidence": "Matched known-at-decision candidates, actual historical reviews, eligible quote/bars, frozen contracts and closed Native trade/fee ledger; independent chronological holdout."}


def compare_observations(rows: list[dict], **functions) -> dict:
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_OBSERVATIONS:
        raise ValueError("invalid_observation_count")
    seen, compared, duplicates = {}, [], 0
    for row in rows:
        key = row.get("observation_id")
        digest = fingerprint(row)
        if key in seen:
            if seen[key] != digest:
                raise ValueError("conflicting_duplicate_observation")
            duplicates += 1
            continue
        seen[key] = digest
        compared.append(compare_row(row, **functions))
    matrix = Counter((row["baseline_status"], row["candidate_status"]) for row in compared)
    admitted_a = [row for row in compared if row["baseline_status"] == "APPROVED"]
    admitted_b = [row for row in compared if row["candidate_status"] == "APPROVED"]
    known = [row for row in compared if row["baseline_status"] in {"APPROVED", "REJECTED"}
             and row["candidate_status"] in {"APPROVED", "REJECTED"}]
    assert all(row["baseline_status"] == "APPROVED" for row in admitted_b), "VCP_must_not_rescue_failed_baseline"
    return {"scope": "PAIRED_STRUCTURAL_REFERENCE_ONLY_NOT_BACKTEST", "input_observations": len(rows),
            "deduplicated_observations": len(compared), "duplicate_observation_ids_excluded": duplicates,
            "unique_tickers": len({r["ticker"] for r in compared}),
            "unique_source_structures": len({r["unique_structure_id"] for r in compared}),
            "unique_source_reference_configurations": len({r["unique_reference_configuration_id"] for r in compared}),
            "baseline_A_structurally_approved_observations": len(admitted_a),
            "candidate_B_structurally_approved_observations": len(admitted_b),
            "baseline_A_unique_approved_structures": len({r["unique_structure_id"] for r in admitted_a}),
            "candidate_B_unique_approved_structures": len({r["unique_structure_id"] for r in admitted_b}),
            "candidate_B_rescued_A_rejections": 0,
            "baseline_approved_policy_versions": dict(Counter(r["baseline_policy_version"] for r in admitted_a)),
            "paired_known_decision_denominator": len(known),
            "paired_known_A_approval_rate": sum(r["baseline_status"] == "APPROVED" for r in known) / len(known) if known else None,
            "paired_known_B_approval_rate": sum(r["candidate_status"] == "APPROVED" for r in known) / len(known) if known else None,
            "candidate_B_unknown_observations": sum(r["candidate_status"] == "UNKNOWN" for r in compared),
            "eligible_breakout_VCP_gate_observations": sum(r["vcp_applies_to_saved_baseline_breakout"] for r in compared),
            "vcp_states_all_observed_sources": dict(Counter(r["vcp_state"] for r in compared)),
            "baseline_reasons": dict(Counter(r["baseline_reason"] for r in compared if r["baseline_reason"])),
            "candidate_reasons": dict(Counter(r["candidate_reason"] for r in compared if r["candidate_reason"])),
            "paired_matrix": [{"A": a, "B": b, "observations": n} for (a, b), n in sorted(matrix.items())],
            "ranking": "UNCHANGED: this POC is a strict existing-breakout filter, not a rank bonus or candidate refill policy.",
            "performance": unavailable_performance(), "observations": compared}


def load_history_cache(path: str | Path) -> tuple[list[dict], dict]:
    with Path(path).open("rb") as stream:
        packed = stream.read(4_000_001)
    if len(packed) > 4_000_000:
        raise ValueError("compressed_cache_limit")
    # Bounded decompression; do not execute/import old workers or cache clients.
    with gzip.open(path, "rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    data = decode_json(raw)
    if data.get("schema") not in (1, 2) or not isinstance(data.get("histories"), dict) or not 1 <= len(data["histories"]) <= 1000:
        raise ValueError("unsupported_history_cache")
    rows, counts = [], []
    for ticker, encoded in sorted(data["histories"].items()):
        observed = data["fetched_at"] if data["schema"] == 1 else encoded["fetched_at"]
        at = datetime.fromtimestamp(finite(observed), timezone.utc).isoformat()
        split = decode_json((encoded if data["schema"] == 1 else encoded["data"]).encode())
        if not isinstance(split.get("data"), list) or not 1 <= len(split["data"]) <= MAX_BARS or len(split["data"]) != len(split.get("index", [])):
            raise ValueError("invalid_history_shape")
        names = split["columns"]
        if not isinstance(names, list) or len(names) != len(set(names)) or not {"Open", "High", "Low", "Close", "Volume"}.issubset(names):
            raise ValueError("invalid_history_columns")
        bars = []
        for stamp, values in zip(split["index"], split["data"]):
            if len(values) != len(names):
                raise ValueError("invalid_history_width")
            bars.append(dict(date=str(stamp)[:10], **dict(zip(names, values))))
        row = {"observation_id": fingerprint([ticker, at, bars]), "ticker": ticker,
               "action": "BUY", "strategy": "single", "decision_at": at,
               "source_observed_at": at, "reference_kind": "DAILY_CLOSE_REFERENCE_NOT_LIVE_ENTRY",
               "reference_price": bars[-1]["Close"], "bars": bars}
        rows.append(row)
        counts.append(len(bars))
    return rows, {"file_sha256": hashlib.sha256(packed).hexdigest(), "schema": data["schema"], "synthetic": False,
                  "symbols": len(rows), "completed_bars_before_adapter_filter_min": min(counts),
                  "completed_bars_before_adapter_filter_max": max(counts),
                  "symbols_with_200_bars": sum(n >= 200 for n in counts),
                  "symbols_with_253_bars": sum(n >= 253 for n in counts),
                  "snapshot_observed_at": sorted({r["source_observed_at"] for r in rows}),
                  "period_start_min": min(r["bars"][0]["date"] for r in rows),
                  "period_end_max": max(r["bars"][-1]["date"] for r in rows),
                  "scope": "Existing single dated cache; historical membership/adjustment basis and actual reviews not verified. Not a PIT universe backtest; never joined to later Oct16 observations."}


def retained_funnel(path: str | Path) -> dict:
    data, digest = read_json(path)
    funnel = data["result"]["funnel"]
    for key in ("review_summary", "review_groups"):
        if funnel[key].get("clipped"):
            raise ValueError("clipped_retained_summary")
    summary = funnel["review_summary"]["rows"]
    if len(summary) != 1:
        raise ValueError("ambiguous_retained_summary")
    counts = Counter()
    for row in funnel["review_groups"]["rows"]:
        n = row["n"]
        if type(n) is not int or n < 0:
            raise ValueError("invalid_retained_count")
        counts[row["reject_reason"]] += n
    total = summary[0]["review_rows"]
    if sum(counts.values()) != total:
        raise ValueError("retained_denominator_mismatch")
    structural = sum(n for key, n in counts.items() if key in STRUCTURAL_REASONS)
    return {"source_sha256": digest, "window_start": data["result"]["start"],
            "window_end_exclusive": data["result"].get("effective_end_exclusive", data["result"]["end_exclusive"]),
            "requested_window_end_exclusive": data["result"]["end_exclusive"],
            "observations": total, "unique_tickers": summary[0]["unique_tickers"],
            "scans": summary[0]["unique_scans"], "structural_rejections": structural,
            "counts": dict(counts), "structural_rejection_observation_rate": structural / total if total else None,
            "paired_VCP_rescues": 0,
            "conclusion": f"VCP cannot rescue these{structural} existing structural failures without changing protected gates. Full individual OHLCV/setup inputs missing, so added selectivity/quality on the other{total-structural} observations is DATA_INSUFFICIENT.",
            "do_not_merge": "News candidate cohort and later/older price cache are separate denominators. Tickers are not trades; repeated rows are not newAIcalls."}


def frozen_case_rows(path: str | Path) -> tuple[list[dict], dict]:
    packet, digest = read_json(path)
    if "envelope" in packet:
        e = packet["envelope"]
        if set(e) != {"codec", "bytes", "sha256", "payload"} or e["codec"] != "zlib-base64-v1" or type(e["bytes"]) is not int or not 0 < e["bytes"] <= 524288:
            raise ValueError("invalid_frozen_envelope")
        packed = base64.b64decode(e["payload"], validate=True)
        if len(packed) > 262144:
            raise ValueError("frozen_envelope_limit")
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, 524289)
        if len(raw) != e["bytes"] or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data or hashlib.sha256(raw).hexdigest() != e["sha256"]:
            raise ValueError("frozen_envelope_integrity")
        data = decode_json(raw)
        cases = [item["case"] for item in data["cases"]]
    else:
        data = packet["read_only_evidence"]["result"]
        cases = [data["case"]]
    if data.get("read_only") != "on" or data.get("isolation") != "repeatable read":
        raise ValueError("unverified_frozen_evidence_origin")
    rows = []
    for case in cases:
        # Preserve the exact existing target_evidence.capture wire contract:
        # sorted JSON with its default spaces, not this tool's compact hashes.
        saved_source_hash = hashlib.sha256(json.dumps(case["source_inputs"], sort_keys=True, allow_nan=False).encode()).hexdigest()
        if saved_source_hash != case["source_inputs_sha256"]:
            raise ValueError("frozen_source_hash_mismatch")
        at = datetime.fromtimestamp(finite(case["source_observed_at"]), timezone.utc).isoformat()
        rows.append({"observation_id": case["fingerprint"], "ticker": case["ticker"],
                     "action": case["action"], "strategy": case["strategy"],
                     "decision_at": case["decided_at"], "source_observed_at": at,
                     "reference_kind": "RETAINED_INTRADAY_REFERENCE_NOT_AN_EXECUTED_ENTRY",
                     "reference_price": case["quote"]["price"], "reference_at": case["quote"]["as_of"],
                     "source_inputs": case["source_inputs"], "source_inputs_sha256": case["source_inputs_sha256"]})
    return rows, {"file_sha256": digest, "observations": len(rows), "OHLCV_available": False, "synthetic": False,
                  "scope": "Real frozen source/quote comparison only. Retained V2 levels are rebuilt with current unchanged pure builders; VCP evidence remains UNKNOWN without source bars."}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dataset", help="Explicit version1 observation JSON; no URLs")
    group.add_argument("--synthetic-fixture", action="store_true", help="Committed253-session calculation fixture, NOT historical performance")
    group.add_argument("--history-cache", help="Existing local schema1/2 gzip cache; read only")
    group.add_argument("--frozen-case-packets", nargs="+", help="Existing private bounded case receipts; never committed")
    parser.add_argument("--retained-funnel", help="Existing dated aggregate94/87 receipt, not joined to dataset")
    parser.add_argument("--summary-only", action="store_true", help="Exclude per-observation hashes/tickers from stdout")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    sys.dont_write_bytecode = True
    with offline_only():
        if args.history_cache:
            rows, provenance = load_history_cache(args.history_cache)
        elif args.frozen_case_packets:
            rows, provenance = [], {"packets": []}
            for path in args.frozen_case_packets:
                part, source = frozen_case_rows(path)
                rows.extend(part)
                provenance["packets"].append(source)
        elif args.synthetic_fixture:
            fixtures = REPO / "research" / "fixtures"
            if str(fixtures) not in sys.path:
                sys.path.insert(0, str(fixtures))
            from vcp_comparison_fixture import build_dataset
            data = build_dataset()
            rows, provenance = data["observations"], {"synthetic": True, "source": data["source"],
                                                     "fixture_sha256": fingerprint(data)}
        else:
            data, digest = read_json(args.dataset)
            if type(data.get("version")) is not int or data["version"] != 1 or not isinstance(data.get("synthetic"), bool):
                raise ValueError("explicit_dataset_version_and_synthetic_label_required")
            rows, provenance = data["observations"], {"file_sha256": digest, "synthetic": data["synthetic"],
                                                     "source": data.get("source", "EXPLICIT_LOCAL_DATASET")}
        result = compare_observations(rows)
        if args.summary_only:
            result.pop("observations")
        result["dataset"] = provenance
        result["comparison_limits"] = [
            "Partial component comparison: actual target-plan geometry and VCP evidence only, not full Technical/News/AI/risk/admission/execution pipeline approval.",
            "A daily close cannot exceed its same completed20-session high. If eligible_breakout_VCP_gate_observations=0, existing V2 approvals do not measure VCP selectivity or quality and must not be called a neutral/improved strategy result.",
            "No held-out performance, historical AI decisions, paper orders or intrabar fills reconstructed. Repeated source configurations are not independent trades."]
        if args.retained_funnel:
            result["separate_retained_funnel"] = retained_funnel(args.retained_funnel)
        result["cost_and_execution_contract"] = "SAME existing LIMIT/slippage/fees/full-bar/stop-first policy in both arms; none simulated because no legal entry/AI ledger. No altered thresholds, fills, TP/SL or capital assumptions."
        result["out_of_sample"] = "DATA_INSUFFICIENT: one dated cache/retained structural cohort is not independent chronological performance OOS; synthetic fixtures never labeled OOS."
        result["safety"] = {"Production_calls": 0, "DB_calls": 0, "AI_calls": 0, "provider_fetches": 0,
                            "created_signals_orders_fills": 0, "Telegram_calls": 0, "raw_history_output": False}
        print(json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
