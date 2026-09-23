import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_topics import destination_fields, thread_id_for_event


class TelegramTopicRoutingTests(unittest.TestCase):
    def test_news_and_trading_events_route_to_separate_threads(self):
        with patch.dict(os.environ, {
            "TELEGRAM_NEWS_THREAD_ID": "101",
            "TELEGRAM_TRADING_THREAD_ID": "202",
            "TELEGRAM_PORTFOLIO_THREAD_ID": "303",
        }, clear=False):
            for event in ("position_news", "watchlist_news", "watchlist_news_correction", "correction", "news_status"):
                self.assertEqual(thread_id_for_event(event), 101)
            for event in ("new_signal", "entry", "entry_chart", "tp", "stop", "sell", "stop_change"):
                self.assertEqual(thread_id_for_event(event), 202)
            self.assertEqual(thread_id_for_event("portfolio_status"), 303)

    def test_missing_or_invalid_thread_falls_back_to_general_chat(self):
        with patch.dict(os.environ, {
            "TELEGRAM_NEWS_THREAD_ID": "invalid",
            "TELEGRAM_TRADING_THREAD_ID": "",
            "TELEGRAM_PORTFOLIO_THREAD_ID": "",
        }, clear=False):
            self.assertEqual(destination_fields("-1001", "position_news"), {"chat_id": "-1001"})
            self.assertEqual(destination_fields("-1001", "entry"), {"chat_id": "-1001"})
            self.assertEqual(destination_fields("-1001", "portfolio_status"), {"chat_id": "-1001"})
            self.assertEqual(destination_fields("-1001", None), {"chat_id": "-1001"})


if __name__ == "__main__":
    unittest.main()
