import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

import position_charts
from routes import create_app


def trade(strategy="single"):
    return {
        "id": 7,
        "ticker": "AAPL",
        "strategy": strategy,
        "entry_price": 100.0,
        "current_stop": 96.0,
        "tp1": 104.0,
        "tp2": 108.0,
        "tp3": 112.0,
        "tp1_pct": 0.25,
        "tp2_pct": 0.35,
        "tp3_pct": 0.40,
        "opened_at": "2026-07-15T14:30:00Z",
    }


def daily_frame():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    index = pd.DatetimeIndex([start + timedelta(days=i) for i in range(55)])
    closes = [98.0 + i * 0.25 for i in range(len(index))]
    return pd.DataFrame(
        {
            "Open": [value - 0.3 for value in closes],
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [10_000_000 for _ in closes],
        },
        index=index,
    )


class PositionChartTests(unittest.TestCase):
    def test_single_and_staged_allocations_match_execution_strategy(self):
        self.assertEqual(position_charts.operational_allocations(trade("single")), [0.0, 1.0, 0.0])
        self.assertEqual(position_charts.operational_allocations(trade("staged")), [0.25, 0.35, 0.40])

    def test_chart_is_a_real_png_with_all_price_levels(self):
        png = position_charts.render_position_chart(trade(), daily_frame())
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 10_000)

    def test_signal_entry_label_distinguishes_planned_from_actual_fill(self):
        base = {
            **trade(), "planned_entry": 101.0, "actual_entry": None,
            "created_at": "2026-07-15T14:30:00Z",
        }
        planned = position_charts.signal_chart_record(base, "single")
        self.assertEqual(planned["entry_price"], 101.0)
        self.assertIn("not filled", planned["entry_label"])
        filled = position_charts.signal_chart_record({**base, "actual_entry": 100.5}, "single")
        self.assertEqual(filled["entry_price"], 100.5)
        self.assertEqual(filled["entry_label"], "Actual paper entry")

    def test_chart_route_returns_png_and_fails_closed(self):
        client = TestClient(create_app())
        with patch("routes_scanner.position_chart_bytes", return_value=b"\x89PNG\r\n\x1a\nchart"):
            response = client.get("/api/scanner/trades/7/chart")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        with patch("routes_scanner.position_chart_bytes", side_effect=LookupError("not open")):
            missing = client.get("/api/scanner/trades/999/chart")
        self.assertEqual(missing.status_code, 404)

    def test_signal_chart_route_returns_png_and_fails_closed(self):
        client = TestClient(create_app())
        with patch("routes_scanner.signal_chart_bytes", return_value=b"\x89PNG\r\n\x1a\nsignal"):
            response = client.get("/api/scanner/signals/7/chart")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        with patch("routes_scanner.signal_chart_bytes", side_effect=LookupError("not found")):
            missing = client.get("/api/scanner/signals/999/chart")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
