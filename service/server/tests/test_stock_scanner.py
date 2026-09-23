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

    def test_history_cache_avoids_repeat_full_universe_download(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "history.json.gz"
            histories = {"AAPL": history(), "SPY": history(), "QQQ": history()}
            cfg = config() | {"history_cache_ttl": 72000, "history_stale_after": 345600}
            with patch.object(stock_scanner, "HISTORY_CACHE_FILE", cache_file), \
                 patch.object(stock_scanner, "_download_history", return_value=histories) as download:
                first, first_info = stock_scanner.load_historical_data(list(histories), cfg)
                second, second_info = stock_scanner.load_historical_data(list(histories), cfg)
            self.assertEqual(set(first), set(histories))
            self.assertEqual(set(second), set(histories))
            self.assertEqual(first_info["status"], "refreshed")
            self.assertEqual(second_info["status"], "cache_hit")
            download.assert_called_once()

    def test_incomplete_history_refresh_fails_closed_without_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config() | {"history_cache_ttl": 72000, "history_stale_after": 345600}
            symbols = [f"S{i}" for i in range(20)]
            with patch.object(stock_scanner, "HISTORY_CACHE_FILE", Path(directory) / "history.json.gz"), \
                 patch.object(stock_scanner, "_download_history", return_value={symbols[0]: history()}):
                with self.assertRaisesRegex(RuntimeError, "stopped safely"):
                    stock_scanner.load_historical_data(symbols, cfg)

    def test_news_enrichment_covers_broad_shortlist_before_ai_ranking(self):
        candidates = []
        for ticker in ("AAA", "BBB", "CCC"):
            candidates.append({"ticker": ticker, "company": ticker, "technical_direction": "BUY",
                               "technical_score": 6, "average_dollar_volume": 1e9})
        cfg = config() | {"shortlist_limit": 25, "news_cache_ttl": 900, "news_max_age_hours": 72}
        context = {"SPY": {"above_ema20": True, "ema20_above_ema50": True, "return_20d_pct": 3},
                   "QQQ": {"above_ema20": True, "ema20_above_ema50": True, "return_20d_pct": 2}}
        seen = []
        def news(ticker, company, max_age):
            seen.append(ticker)
            title = "Record profit growth" if ticker == "CCC" else "Company update"
            return [{"title": title, "relevance": .9, "published_at": "2026-01-01T00:00:00Z"}]
        with patch.object(stock_scanner, "_read_news_cache", return_value={}), \
             patch.object(stock_scanner, "_write_news_cache"), \
             patch.object(stock_scanner, "fetch_recent_news", side_effect=news):
            ranked, rejected = stock_scanner.enrich_and_rank_candidates(candidates, context, cfg)
        self.assertEqual(set(seen), {"AAA", "BBB", "CCC"})
        self.assertEqual(ranked[0]["ticker"], "CCC")
        self.assertFalse(rejected)

    def test_sell_without_long_is_signal_only_and_never_short(self):
        calls = []
        def api(method, path, **kwargs):
            calls.append((path, kwargs["json"]))
            return {"signal_id": 7}
        candidate = {"ticker": "MSFT", "company": "Microsoft", "atr": 2, "atr_pct": 2,
                     "average_dollar_volume": 1e9, "price_zones": [{"low": p, "high": p, "touches": 1, "pivots": []} for p in (102, 96, 92, 88)]}
        decision = {"action": "SELL", "confidence": .9, "time_horizon": "1-4 weeks", "reason": "Weak trend",
                    "news_sentiment": -.4, "news_relevance": .9}
        signal = stock_scanner._paper_order(candidate, decision, [], (100, "now"),
                                            {"positions": [], "cash": 100000}, config(), api)
        self.assertEqual(calls[0][0], "/signals/strategy")
        self.assertNotIn("short", json.dumps(calls).lower())
        self.assertEqual(signal["paper_execution"], "signal_or_pending_close")
        self.assertEqual(signal["paper_quantity"], 0)

    def test_sell_never_executes_directly_even_with_existing_long(self):
        calls = []
        def api(method, path, **kwargs):
            calls.append((path, kwargs["json"]))
            return {"signal_id": 8, "price": 100}
        candidate = {"ticker": "MSFT", "company": "Microsoft", "atr": 2, "atr_pct": 2,
                     "average_dollar_volume": 1e9, "price_zones": [{"low": p, "high": p, "touches": 1, "pivots": []} for p in (102, 96, 92, 88)]}
        decision = {"action": "SELL", "confidence": .9, "time_horizon": "1-4 weeks", "reason": "Weak trend",
                    "news_sentiment": -.4, "news_relevance": .9}
        portfolio = {"positions": [{"market": "us-stock", "symbol": "MSFT", "side": "long",
                                    "quantity": 1, "entry_price": 110, "current_price": 100}], "cash": 100000}
        signal = stock_scanner._paper_order(candidate, decision, [], (100, "now"), portfolio, config(), api)
        self.assertEqual(calls[0][0], "/signals/strategy")
        self.assertNotIn("action", calls[0][1])
        self.assertEqual(signal["paper_execution"], "signal_or_pending_close")

    def test_telegram_is_safely_disabled_without_credentials(self):
        cfg = config() | {"telegram_enabled": True}
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=False):
            self.assertEqual(stock_scanner.send_telegram("test", cfg), "missing_credentials")

    def test_telegram_text_routes_news_to_configured_forum_topic(self):
        cfg = config() | {"telegram_enabled": True}
        response = Mock(ok=True)
        response.json.return_value = {"ok": True}
        session = Mock(); session.post.return_value = response
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "-1001",
            "TELEGRAM_NEWS_THREAD_ID": "101", "TELEGRAM_TRADING_THREAD_ID": "202",
        }, clear=False), patch.object(stock_scanner.requests, "Session", return_value=session):
            self.assertEqual(stock_scanner.send_telegram("חדשות", cfg, "position_news"), "sent")
        payload = session.post.call_args.kwargs["data"]
        self.assertEqual(payload["chat_id"], "-1001")
        self.assertEqual(payload["message_thread_id"], 101)

    def test_telegram_new_signal_and_entry_alert_paths(self):
        cfg = config() | {"telegram_enabled": True, "telegram_entry_alerts": True}
        signal = {"ticker": "AAPL", "company": "Apple", "action": "BUY", "entry": 100,
                  "take_profit": 106, "stop_loss": 97, "risk_reward": 2, "confidence": .9,
                  "time_horizon": "1-4 weeks", "reason": "Aligned", "relevant_news": [],
                  "timestamp": "2026-01-01T00:00:00Z",
                  "telegram_reason_he": "המגמה חיובית. המומנטום תומך.",
                  "telegram_news_he": []}
        messages = []
        with patch.object(stock_scanner, "send_telegram",
                          side_effect=lambda message, _cfg: messages.append(message) or "sent"):
            state = {}
            stock_scanner._track_signal(state, signal, cfg)
        self.assertEqual(state["tracked_signals"][0]["signal_alert"], "sent")
        self.assertEqual(state["tracked_signals"][0]["entry_alert"], "sent")
        self.assertIn("אות מסחר חזק חדש", messages[0])
        self.assertIn("מחיר הכניסה הושג", messages[1])
        self.assertIn("פעולה: קנייה", messages[0])
        self.assertIn("טווח זמן: 1–4 שבועות", messages[0])
        self.assertIn("המגמה חיובית.\n\nהמומנטום תומך.", messages[0])
        self.assertIn("\n\nסיבה:\n", messages[0])

    def test_telegram_tp_and_sl_alert_paths(self):
        base = {"ticker": "AAPL", "company": "Apple", "action": "BUY", "entry": 100,
                "take_profit": 106, "stop_loss": 97, "risk_reward": 2, "confidence": .9,
                "time_horizon": "1-4 weeks", "reason": "Aligned", "relevant_news": [],
                "timestamp": "2026-01-01T00:00:00Z", "status": "OPEN",
                "telegram_reason_he": "המגמה חיובית.", "telegram_news_he": []}
        cfg = config() | {"telegram_enabled": True, "telegram_level_alerts": True}
        for price, expected, expected_he in ((106.5, "TP", "יעד הרווח הושג"),
                                             (96.5, "SL", "עצירת ההפסד הופעלה")):
            with self.subTest(expected=expected):
                message = stock_scanner._telegram_message(base, f"{expected} REACHED @ ${price:.2f}")
                self.assertIn(expected_he, message)

    def test_telegram_uses_ollama_for_hebrew_reason_and_news(self):
        response = Mock()
        response.json.return_value = {"message": {"content": json.dumps({
            "reason_he": "המגמה חיובית. החדשות תומכות.",
            "news_titles_he": ["מניות האנרגיה עולות לפני פתיחת המסחר"],
        })}}
        signal = {"reason": "The trend is positive. News is supportive.",
                  "relevant_news": [{"title": "Energy stocks advance premarket"}]}
        with patch.object(stock_scanner.requests, "post", return_value=response) as post:
            localized = stock_scanner._localize_telegram_signal(signal)
        self.assertEqual(localized["telegram_reason_he"], "המגמה חיובית. החדשות תומכות.")
        self.assertEqual(localized["telegram_news_he"], ["מניות האנרגיה עולות לפני פתיחת המסחר"])
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:11434/api/chat")

    def test_legacy_monitor_delegates_to_durable_engine(self):
        with patch("scanner_engine.monitor_prices", return_value={"tickers": 1, "bars": 2, "errors": []}):
            result = stock_scanner.monitor_tracked_signals()
        self.assertEqual(result["bars"], 2)

    def test_full_pipeline_publishes_original_paper_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            api_session = Mock(headers={})
            orders = []
            def request(method, url, **kwargs):
                response = Mock()
                if url.endswith("/positions"):
                    response.json.return_value = {"positions": [], "cash": 100000}
                elif url.endswith("/signals/strategy"):
                    orders.append(kwargs["json"])
                    response.json.return_value = {"signal_id": 99}
                return response
            api_session.request.side_effect = request
            news = [{"title": "Current relevant headline", "publisher": "Wire",
                     "published_at": "2026-01-01T00:00:00+00:00", "url": "https://example.test/news",
                     "age_hours": 1, "relevance": 1}]
            decision = {"action": "BUY", "confidence": .91, "news_sentiment": .4, "news_relevance": .9,
                        "time_horizon": "1-4 weeks", "reason": "Trend, momentum and relevant news align."}
            histories = {"AAPL": history(), "SPY": history(), "QQQ": history()}
            environment = {"STOCK_SCANNER_TOKEN": "test-only", "STOCK_SCANNER_SHORTLIST_LIMIT": "20",
                           "STOCK_SCANNER_AI_CANDIDATE_LIMIT": "1",
                           "STOCK_SCANNER_MIN_DOLLAR_VOLUME": "1000000", "STOCK_SCANNER_MIN_ATR_PCT": "0.1",
                           "STOCK_SCANNER_MIN_TECHNICAL_SCORE": "5"}
            with patch.object(stock_scanner, "STATE_FILE", state_file), \
                 patch.dict(os.environ, environment), \
                 patch.object(stock_scanner, "load_universe", return_value={"AAPL": {"company": "Apple", "indexes": ["S&P 500"], "market_cap": 1e12}}), \
                 patch.object(stock_scanner, "load_historical_data", return_value=(histories, {"status": "cache_hit", "age_seconds": 1, "refreshed_symbols": 0})), \
                 patch.object(stock_scanner, "swing_zones", return_value=[{"low": p, "high": p, "touches": 1, "pivots": []} for p in (137,148,156,164)]), \
                 patch.object(stock_scanner, "fetch_recent_news", return_value=news), \
                 patch.object(stock_scanner, "_read_news_cache", return_value={}), \
                 patch.object(stock_scanner, "_write_news_cache"), \
                 patch.object(stock_scanner, "ai_review", return_value=decision), \
                 patch.object(stock_scanner, "current_intraday_quote", return_value=(140, "2026-01-01T00:00:00+00:00")), \
                 patch.object(stock_scanner, "_localize_telegram_signal", side_effect=lambda value: value | {"telegram_reason_he": "סיבה", "telegram_news_he": []}), \
                 patch("scanner_engine.initialize_runtime"), \
                 patch("scanner_engine.record_candidates"), \
                 patch("scanner_engine.record_scan_news"), \
                 patch("scanner_engine.set_service_status"), \
                 patch("scanner_engine.record_signal", return_value={"id": 101, "status": "PENDING_ENTRY"}), \
                 patch.object(stock_scanner.requests, "Session", return_value=api_session):
                state = stock_scanner.run_scan()
            self.assertEqual(state["signals_published"], 1)
            self.assertEqual(orders[0]["market"], "us-stock")
            self.assertEqual(orders[0]["symbols"], "AAPL")
            self.assertIn("Take Profit:", orders[0]["content"])
            self.assertEqual(state["last_signal"]["signal_id"], 99)
            self.assertEqual(state["last_signal"]["paper_execution"], "pending_entry")

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
