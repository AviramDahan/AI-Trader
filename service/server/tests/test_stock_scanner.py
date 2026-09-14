import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stock_scanner


def history(direction="up", stale=False):
    close = np.linspace(100, 140, 75) if direction == "up" else np.linspace(140, 100, 75)
    if stale:
        end = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=10)
    else:
        end = pd.Timestamp.utcnow().tz_localize(None)
    index = pd.bdate_range(end=end, periods=75)
    return pd.DataFrame({"Open": close, "High": close + 2, "Low": close - 2,
                         "Close": close, "Volume": np.full(75, 2_000_000)}, index=index)


def config():
    value = stock_scanner.settings()
    value.update(min_dollar_volume=1_000_000, min_atr_pct=.1, max_atr_pct=20,
                 min_technical_score=5, min_risk_reward=2, paper_notional=100,
                 max_symbol_exposure=250, max_total_exposure=1000)
    return value


class StockScannerTests(unittest.TestCase):
    def test_technical_scanner_detects_bullish_and_bearish_candidates(self):
        buy = stock_scanner.analyze_history("AAPL", "Apple", history("up"), config())
        sell = stock_scanner.analyze_history("MSFT", "Microsoft", history("down"), config())
        self.assertEqual(buy["technical_direction"], "BUY")
        self.assertEqual(sell["technical_direction"], "SELL")
        for value in (buy, sell):
            self.assertIn("rsi14", value)
            self.assertIn("macd_histogram", value)
            self.assertIn("realized_volatility_pct", value)
            self.assertGreater(value["average_dollar_volume"], 1_000_000)

    def test_stale_or_filtered_history_produces_no_candidate(self):
        self.assertIsNone(stock_scanner.analyze_history("AAPL", "Apple", history(stale=True), config()))
        strict = config() | {"min_dollar_volume": 10_000_000_000_000}
        self.assertIsNone(stock_scanner.analyze_history("AAPL", "Apple", history(), strict))
        volatile = config() | {"max_atr_pct": .2}
        self.assertIsNone(stock_scanner.analyze_history("AAPL", "Apple", history(), volatile))

    def test_duplicate_signal_cooldown(self):
        now = 1_000_000
        self.assertTrue(stock_scanner.duplicate_in_cooldown({"AAPL:BUY": now - 10}, "AAPL", "BUY", 24, now))
        self.assertFalse(stock_scanner.duplicate_in_cooldown({"AAPL:BUY": now - 25 * 3600}, "AAPL", "BUY", 24, now))
        self.assertFalse(stock_scanner.duplicate_in_cooldown({}, "AAPL", "BUY", 24, now))

    def test_ai_contract_is_strict_and_direction_bound(self):
        valid = {"action": "BUY", "confidence": .9, "news_sentiment": .3, "news_relevance": .8,
                 "time_horizon": "1-4 weeks", "reason": "Aligned evidence"}
        self.assertEqual(stock_scanner.validate_ai_decision(valid, "BUY")["action"], "BUY")
        for change in ({"action": "SELL"}, {"confidence": True}, {"news_relevance": 2},
                       {"time_horizon": "forever"}, {"reason": ""}):
            with self.assertRaises(ValueError):
                stock_scanner.validate_ai_decision(valid | change, "BUY")

    def test_levels_and_required_signal_format(self):
        target, stop, rr = stock_scanner.levels("BUY", 100, 2, 2)
        self.assertEqual((target, stop, rr), (106, 97, 2))
        candidate = {"ticker": "AAPL", "company": "Apple", "atr_pct": 2.1, "average_dollar_volume": 1e9}
        decision = {"action": "BUY", "confidence": .9, "time_horizon": "1-4 weeks", "reason": "Reason",
                    "news_sentiment": .3, "news_relevance": .9}
        news = [{"title": "Headline", "publisher": "Source", "published_at": "2026-01-01T00:00:00+00:00"}]
        content = stock_scanner.format_signal(candidate, decision, news, 100, 106, 97, 2, "2026-01-01T00:00:00+00:00")
        for label in ("Ticker:", "Company:", "Action:", "Entry:", "Take Profit:", "Stop Loss:",
                      "Risk/Reward:", "Confidence:", "Time Horizon:", "Reason:", "Relevant News:", "Timestamp:"):
            self.assertIn(label, content)
        self.assertIn("PAPER TRADING ONLY", content)

    def test_news_must_be_current_and_ticker_relevant(self):
        response = Mock()
        response.json.return_value = {"news": [
            {"title": "Relevant", "link": "https://example.test/1", "publisher": "Source",
             "providerPublishTime": int(time.time()) - 60, "relatedTickers": ["AAPL"]},
            {"title": "Stale", "link": "https://example.test/2", "publisher": "Source",
             "providerPublishTime": int(time.time()) - 10 * 86400, "relatedTickers": ["AAPL"]},
            {"title": "Wrong company", "link": "https://example.test/3", "publisher": "Source",
             "providerPublishTime": int(time.time()), "relatedTickers": ["MSFT"]},
        ]}
        session = Mock(headers={})
        session.get.return_value = response
        with patch.object(stock_scanner.requests, "Session", return_value=session):
            items = stock_scanner.fetch_recent_news("AAPL", "Apple", 72)
        self.assertEqual([item["title"] for item in items], ["Relevant"])

    def test_full_pipeline_publishes_original_paper_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            api_session = Mock(headers={})
            orders = []
            def request(method, url, **kwargs):
                response = Mock()
                if url.endswith("/positions"):
                    response.json.return_value = {"positions": [], "cash": 100000}
                elif url.endswith("/signals/realtime"):
                    orders.append(kwargs["json"])
                    response.json.return_value = {"signal_id": 99, "price": 140}
                return response
            api_session.request.side_effect = request
            news = [{"title": "Current relevant headline", "publisher": "Wire",
                     "published_at": "2026-01-01T00:00:00+00:00", "url": "https://example.test/news",
                     "age_hours": 1, "relevance": 1}]
            decision = {"action": "BUY", "confidence": .91, "news_sentiment": .4, "news_relevance": .9,
                        "time_horizon": "1-4 weeks", "reason": "Trend, momentum and relevant news align."}
            histories = {"AAPL": history(), "SPY": history(), "QQQ": history()}
            environment = {"STOCK_SCANNER_TOKEN": "test-only", "STOCK_SCANNER_CANDIDATE_LIMIT": "1",
                           "STOCK_SCANNER_MIN_DOLLAR_VOLUME": "1000000", "STOCK_SCANNER_MIN_ATR_PCT": "0.1",
                           "STOCK_SCANNER_MIN_TECHNICAL_SCORE": "5"}
            with patch.object(stock_scanner, "STATE_FILE", state_file), \
                 patch.dict(os.environ, environment), \
                 patch.object(stock_scanner, "load_universe", return_value={"AAPL": {"company": "Apple", "indexes": ["S&P 500"], "market_cap": 1e12}}), \
                 patch.object(stock_scanner, "_download_history", return_value=histories), \
                 patch.object(stock_scanner, "fetch_recent_news", return_value=news), \
                 patch.object(stock_scanner, "ai_review", return_value=decision), \
                 patch.object(stock_scanner, "current_intraday_quote", return_value=(140, "2026-01-01T00:00:00+00:00")), \
                 patch.object(stock_scanner.requests, "Session", return_value=api_session):
                state = stock_scanner.run_scan()
            self.assertEqual(state["signals_published"], 1)
            self.assertEqual(orders[0]["market"], "us-stock")
            self.assertEqual(orders[0]["symbol"], "AAPL")
            self.assertEqual(orders[0]["action"], "buy")
            self.assertLessEqual(orders[0]["quantity"] * 140, 100)
            self.assertIn("Take Profit:", orders[0]["content"])
            self.assertEqual(state["last_signal"]["signal_id"], 99)

    def test_status_redacts_internal_execution_and_credentials(self):
        hidden = {"token": "secret", "cooldowns": {"AAPL:BUY": 1}, "order_pending": {"ticker": "AAPL"},
                  "events": [], "next_scan_at": 0}
        with patch.object(stock_scanner, "read_state", return_value=hidden):
            status = stock_scanner.public_status()
        for key in ("token", "cooldowns", "order_pending"):
            self.assertNotIn(key, status)
        self.assertTrue(status["paper_only"])


if __name__ == "__main__":
    unittest.main()
