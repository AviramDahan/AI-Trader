import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
import pandas as pd
from scanner_targets import structure_plan, swing_zones, validate_plan


def zones(prices):
    return [{"low": p, "high": p, "touches": 1, "pivots": [{"price": p, "date": "2026-01-02", "kind": "swing_high"}]} for p in prices]


class TargetsTests(unittest.TestCase):
    def test_long_targets_follow_observed_zones_not_fixed_multiples(self):
        plan = structure_plan("BUY", 100, 2, zones([98, 104, 108, 112]), 2)
        self.assertEqual(plan["targets"], [103.7, 107.7, 111.7])
        self.assertEqual(plan["stop"], 97)
        self.assertGreater(plan["weighted_rr"], 2)
        self.assertAlmostEqual(sum(plan["fractions"]), 1)
        self.assertEqual(validate_plan(plan, 100, 97, "BUY"), plan)

    def test_short_targets_are_analysis_only_and_descend(self):
        plan = structure_plan("SELL", 100, 2, zones([102, 96, 92, 88]), 2)
        self.assertEqual(plan["targets"], [96.3, 92.3, 88.3])
        self.assertEqual(plan["stop"], 103)

    def test_missing_levels_and_nearby_obstacles_fail_closed(self):
        for prices in ([98, 104], [98, 100.5, 108, 112], [98, 104, 105, 106]):
            with self.assertRaises(ValueError):
                structure_plan("BUY", 100, 2, zones(prices), 2)

    def test_tampered_prices_rejected(self):
        plan = structure_plan("BUY", 100, 2, zones([98, 104, 108, 112]), 2)
        plan["targets"][2] = 1000
        with self.assertRaises(ValueError):
            validate_plan(plan, 100, 97, "BUY")

    def test_pivots_require_two_later_bars_and_record_dates(self):
        frame = pd.DataFrame({"High": [100,101,105,102,101,103,104],
                              "Low": [99,98,97,98,99,97,96]}, index=pd.date_range("2026-01-01", periods=7))
        result = swing_zones(frame, 2)
        prices = [p["price"] for zone in result for p in zone["pivots"]]
        self.assertIn(105, prices)
        self.assertIn(97, prices)
        self.assertNotIn(104, prices)
        self.assertNotIn(96, prices)
