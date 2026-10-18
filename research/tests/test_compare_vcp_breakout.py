"""Comparator controls, not a historical-performance or live-execution test."""
import copy
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_vcp_breakout.py"
spec = importlib.util.spec_from_file_location("vcp_compare_research", SCRIPT)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def observation(identity="one", state="CONFIRMED", policy="single_breakout_v1", baseline="APPROVED"):
    return {"observation_id": identity, "ticker": "SYNTH", "decision_at": "2026-10-16T14:05:00Z",
            "source_observed_at": "2026-10-15T20:10:00Z", "reference_at": "2026-10-16T14:04:00Z",
            "reference_kind": "SYNTHETIC_REFERENCE_NOT_TRADE", "reference_price": 100.0,
            "source_inputs_sha256": "same_synthetic_structure", "bars": [{"state": state}],
            "test_policy": policy, "test_baseline": baseline}


def baseline(row, frame):
    status = row["test_baseline"]
    return {"status": status, "reason": None if status == "APPROVED" else "nearest_resistance_below_2r",
            "plan": {"policy_version": row["test_policy"], "stop": 98.5, "active_target": 103.0} if status == "APPROVED" else None}


def evaluate(bars, **kwargs):
    return {"state": bars[0]["state"], "reasons": [], "eligible": bars[0]["state"] == "CONFIRMED"}


def validate(evidence, price, quote_at, decision_at):
    if price > 103:
        raise ValueError("vcp_overextended")
    return copy.deepcopy(evidence)


FUNCTIONS = dict(baseline_fn=baseline, evaluate_fn=evaluate, validate_fn=validate)


class ComparatorTests(unittest.TestCase):
    def test_confirmed_preserves_baseline(self):
        row = observation()
        saved = copy.deepcopy(row)
        result = compare.compare_observations([row], **FUNCTIONS)
        self.assertEqual(result["candidate_B_structurally_approved_observations"], 1)
        self.assertEqual(result["paired_matrix"], [{"A": "APPROVED", "B": "APPROVED", "observations": 1}])
        self.assertEqual(row, saved)
        self.assertIsNone(result["performance"]["closed_trades"])
        self.assertIsNone(result["performance"]["win_rate"])

    def test_each_nonconfirmed_state_never_admits_breakout(self):
        for state in ("UNKNOWN", "FORMING", "REJECTED", "OVEREXTENDED"):
            with self.subTest(state=state):
                result = compare.compare_observations([observation(state=state)], **FUNCTIONS)
                self.assertEqual(result["candidate_B_structurally_approved_observations"], 0)
                self.assertEqual(result["candidate_B_unknown_observations"], int(state == "UNKNOWN"))

    def test_VCP_does_not_rescue_existing_RR_rejection(self):
        result = compare.compare_observations([observation(baseline="REJECTED")], **FUNCTIONS)
        self.assertEqual(result["candidate_B_rescued_A_rejections"], 0)
        self.assertEqual(result["candidate_reasons"], {"nearest_resistance_below_2r": 1})

    def test_existing_nonbreakout_V2_not_filtered(self):
        result = compare.compare_observations([observation(state="REJECTED", policy="single_target_v2")], **FUNCTIONS)
        self.assertEqual(result["candidate_B_structurally_approved_observations"], 1)
        self.assertEqual(result["eligible_breakout_VCP_gate_observations"], 0)

    def test_quote_revalidation_rejects_extended_reference(self):
        row = observation()
        row["reference_price"] = 105.0
        result = compare.compare_observations([row], **FUNCTIONS)
        self.assertEqual(result["candidate_reasons"], {"vcp_overextended": 1})

    def test_repeated_observations_are_one_source_structure_not_three_trades(self):
        first, repeat, price_change = observation("a"), observation("b"), observation("c")
        price_change["reference_price"] = 100.1
        result = compare.compare_observations([first, repeat, price_change, copy.deepcopy(first)], **FUNCTIONS)
        self.assertEqual(result["deduplicated_observations"], 3)
        self.assertEqual(result["duplicate_observation_ids_excluded"], 1)
        self.assertEqual(result["unique_source_structures"], 1)
        self.assertEqual(result["unique_source_reference_configurations"], 2)
        self.assertEqual(result["baseline_A_unique_approved_structures"], 1)
        self.assertIsNone(result["performance"]["signal_to_entry_conversion"])

    def test_conflicting_duplicate_is_error_not_silent_rewrite(self):
        first, other = observation(), observation()
        other["reference_price"] = 100.1
        with self.assertRaisesRegex(ValueError, "conflicting_duplicate_observation"):
            compare.compare_observations([first, other], **FUNCTIONS)

    def test_future_snapshot_is_not_historical_evidence(self):
        row = observation()
        row["source_observed_at"] = "2026-10-17T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "source_observed_after_decision"):
            compare.compare_observations([row], **FUNCTIONS)

    def test_unknown_coverage_not_in_quality_denominator(self):
        result = compare.compare_observations([observation("known"), observation("unknown", state="UNKNOWN")], **FUNCTIONS)
        self.assertEqual(result["paired_known_decision_denominator"], 1)
        self.assertEqual(result["paired_known_A_approval_rate"], 1)
        self.assertEqual(result["paired_known_B_approval_rate"], 1)
        self.assertEqual(result["candidate_B_unknown_observations"], 1)

    def test_json_duplicate_nonfinite_and_naive_time_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                compare.decode_json(raw)
        with self.assertRaisesRegex(ValueError, "timestamp_timezone_required"):
            compare.instant("2026-10-16T14:00:00")
        with self.assertRaises(ValueError):
            compare.finite(True)

    def test_network_guard_blocks_connect_and_restores_socket(self):
        original = socket.socket.connect
        with compare.offline_only():
            with self.assertRaisesRegex(RuntimeError, "forbids_network"):
                socket.create_connection(("example.invalid", 443))
        self.assertIs(socket.socket.connect, original)

    def test_retained94_aggregate_is_not_reconstructed_as_rows(self):
        reasons = [("pre_nearest_resistance_below_2r", 28), ("pre_entry_inside_unresolved_price_zone", 16),
                   ("pre_price_structure_fails_risk_reward", 13), ("pre_invalid_rounded_levels", 12),
                   ("pre_insufficient_confirmed_price_zones", 10), ("pre_entry_not_above_completed_high", 8),
                   ("pre_waiting_regular_session", 6), ("ai_hold", 1)]
        data = {"result": {"start": "2026-10-16T19:09:58Z", "end_exclusive": "2026-10-16T20:05:07Z",
                          "funnel": {"review_summary": {"clipped": False, "rows": [{"review_rows": 94, "unique_tickers": 88, "unique_scans": 2}]},
                                     "review_groups": {"clipped": False, "rows": [{"reject_reason": k, "n": n} for k, n in reasons]}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic_aggregate.json"
            path.write_text(json.dumps(data))
            result = compare.retained_funnel(path)
        self.assertEqual(result["observations"], 94)
        self.assertEqual(result["structural_rejections"], 87)
        self.assertAlmostEqual(result["structural_rejection_observation_rate"], 87 / 94)
        self.assertEqual(result["paired_VCP_rescues"], 0)

    def test_history_cache_loader_marks_reference_and_coverage(self):
        split = {"columns": ["Open", "High", "Low", "Close", "Volume"],
                 "index": ["2026-09-24T00:00:00.000", "2026-09-25T00:00:00.000"],
                 "data": [[100, 101, 99, 100, 500000], [100, 102, 99, 101, 500000]]}
        data = {"schema": 1, "fetched_at": datetime(2026, 9, 26, tzinfo=timezone.utc).timestamp(),
                "histories": {"SYNTH": json.dumps(split)}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic_cache.gz"
            with gzip.open(path, "wt") as stream:
                json.dump(data, stream)
            rows, provenance = compare.load_history_cache(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(provenance["symbols_with_253_bars"], 0)
        self.assertEqual(rows[0]["reference_kind"], "DAILY_CLOSE_REFERENCE_NOT_LIVE_ENTRY")

    def test_retained_source_hash_uses_original_spaced_json_contract(self):
        source = dict(atr=1.0, data_as_of="2026-10-05", zones=[])
        source_hash = hashlib.sha256(json.dumps(source, sort_keys=True, allow_nan=False).encode()).hexdigest()
        self.assertNotEqual(source_hash, compare.fingerprint(source))
        case = dict(fingerprint="synthetic_saved", ticker="SYNTH", action="BUY", strategy="single",
                    decided_at="2026-10-06T14:00:37Z", source_observed_at=datetime(2026, 10, 5, 20, 10, tzinfo=timezone.utc).timestamp(),
                    source_inputs=source, source_inputs_sha256=source_hash,
                    quote=dict(price=100.0, as_of="2026-10-06T14:00:00Z"))
        packet = dict(read_only_evidence=dict(result=dict(read_only="on", isolation="repeatable read", case=case)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic_case.json"
            path.write_text(json.dumps(packet))
            rows, provenance = compare.frozen_case_rows(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_inputs_sha256"], source_hash)
        self.assertFalse(provenance["OHLCV_available"])


class ActualPureAdapterTests(unittest.TestCase):
    """Synthetic fixtures through the real isolated target/VCP modules only."""
    @staticmethod
    def dataset():
        fixtures = SCRIPT.parents[1] / "fixtures"
        if str(fixtures) not in sys.path:
            sys.path.insert(0, str(fixtures))
        from vcp_comparison_fixture import build_dataset
        return build_dataset()

    def test_real253bar_fixture_keeps_coverage_separate_from_quality(self):
        data = self.dataset()
        original = copy.deepcopy(data)
        with compare.offline_only():
            result = compare.compare_observations(data["observations"])
        self.assertEqual(result["baseline_A_structurally_approved_observations"], 4)
        self.assertEqual(result["candidate_B_structurally_approved_observations"], 2)
        self.assertEqual(result["candidate_B_unique_approved_structures"], 1)
        self.assertEqual(result["candidate_B_unknown_observations"], 1)
        self.assertEqual(result["candidate_B_rescued_A_rejections"], 0)
        self.assertEqual(result["vcp_states_all_observed_sources"], {"CONFIRMED": 3, "FORMING": 1, "UNKNOWN": 1})
        self.assertEqual(data, original)
        self.assertEqual(result["performance"]["status"], "DATA_INSUFFICIENT")

    def test_future_candle_does_not_change_source_dedupe_or_decisions(self):
        row = self.dataset()["observations"][0]
        future = copy.deepcopy(row)
        future["bars"].append(dict(date="2026-10-07", Open=900, High=1000, Low=800, Close=950, Volume=99999999))
        with compare.offline_only():
            before = compare.compare_observations([row])
            after = compare.compare_observations([future])
        self.assertEqual(before, after)

    def test_unfinished_source_cannot_become_completed_by_advancing_clock(self):
        row = self.dataset()["observations"][0]
        row["source_observed_at"] = "2026-10-05T17:00:00Z"
        with compare.offline_only():
            result = compare.compare_observations([row])
        self.assertEqual(result["baseline_reasons"], {"source_not_available_at_observation": 1})
        self.assertEqual(result["candidate_B_structurally_approved_observations"], 0)

    def test_individual_future_availability_excludes_trigger_from_both_arms(self):
        row = self.dataset()["observations"][0]
        for bar in row["bars"]:
            bar["available_at"] = bar["date"] + "T20:05:00Z"
        row["bars"][-1]["available_at"] = "2026-10-07T20:05:00Z"
        with compare.offline_only():
            result = compare.compare_observations([row])
        self.assertEqual(result["vcp_states_all_observed_sources"], {"UNKNOWN": 1})
        self.assertEqual(result["baseline_reasons"], {"structure_after_available_history": 1})

    def test_cold_CLI_imports_under_offline_guard(self):
        # Regression for optional calendar/market-data dependency imports under
        # the subprocess guard. The child only processes invented local bars.
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--synthetic-fixture", "--summary-only"],
                                capture_output=True, text=True, check=True, timeout=20)
        output = json.loads(result.stdout)
        self.assertTrue(output["dataset"]["synthetic"])
        self.assertEqual(output["candidate_B_unique_approved_structures"], 1)
        self.assertEqual(output["safety"]["DB_calls"], 0)


if __name__ == "__main__":
    unittest.main()
