import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_topics import destination_fields, thread_id_for_event, with_news_community_link


class TelegramTopicRoutingTests(unittest.TestCase):
    def test_personal_news_split_keeps_market_signals_and_trades_separate(self):
        with patch.dict(os.environ, {'TELEGRAM_PERSONAL_NEWS_THREAD_ID':'114',
                'TELEGRAM_STOCK_NEWS_THREAD_ID':'112', 'TELEGRAM_MARKET_NEWS_THREAD_ID':'111'}, clear=True):
            for event in ('position_news', 'watchlist_news', 'watchlist_news_correction'):
                self.assertEqual(thread_id_for_event(event), 114)
            self.assertEqual(thread_id_for_event('stock_news'), 112)
            self.assertEqual(thread_id_for_event('market_news'), 111)
            self.assertIsNone(thread_id_for_event('entry'))
            self.assertIsNone(thread_id_for_event('new_signal'))

    def test_news_sender_includes_footer_in_mocked_telegram_payload(self):
        import stock_scanner
        session = Mock()
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN':'test', 'TELEGRAM_CHAT_ID':'-123',
                                    'TELEGRAM_COMMUNITY_URL':'https://t.me/+testInvite'}), \
                patch.object(stock_scanner.requests, 'Session', return_value=session):
            self.assertEqual(stock_scanner.send_telegram('news', {'telegram_enabled':True}, 'market_news'), 'sent')
        self.assertIn('https://t.me/+testInvite', session.post.call_args.kwargs['data']['text'])

    def test_community_footer_covers_every_news_route_only_once(self):
        with patch.dict(os.environ, {'TELEGRAM_COMMUNITY_URL':'https://t.me/+testInvite'}):
            for event in ('market_news','position_news','watchlist_news','watchlist_news_correction','stock_news','correction','news_status'):
                message = with_news_community_link('חדשות', event)
                self.assertIn('https://t.me/+testInvite', message)
                self.assertEqual(with_news_community_link(message, event), message)
            for event in ('new_signal','entry','tp','stop','portfolio_status',None):
                self.assertEqual(with_news_community_link('message', event), 'message')

    def test_community_footer_handles_missing_invalid_link_and_unicode_limit(self):
        for link in ('', 'http://t.me/test', 'https://t.me/c/123/4', 'https://evil.test/join'):
            with patch.dict(os.environ, {'TELEGRAM_COMMUNITY_URL':link}):
                self.assertEqual(with_news_community_link('news','market_news'), 'news')
        with patch.dict(os.environ, {'TELEGRAM_COMMUNITY_URL':'https://t.me/+testInvite'}):
            message = with_news_community_link('📰' * 4000,'market_news')
            self.assertLessEqual(len(message.encode('utf-16-le')) // 2, 4096)
            self.assertTrue(message.endswith('https://t.me/+testInvite'))

    def test_news_and_trading_events_route_to_separate_threads(self):
        with patch.dict(os.environ, {
            "TELEGRAM_NEWS_THREAD_ID": "101",
            "TELEGRAM_PERSONAL_NEWS_THREAD_ID": "",
            "TELEGRAM_TRADING_THREAD_ID": "202",
            "TELEGRAM_MARKET_NEWS_THREAD_ID": "111",
            "TELEGRAM_STOCK_NEWS_THREAD_ID": "112",
            "TELEGRAM_SIGNALS_THREAD_ID": "211",
            "TELEGRAM_TRADES_THREAD_ID": "212",
            "TELEGRAM_PORTFOLIO_THREAD_ID": "303",
        }, clear=False):
            self.assertEqual(thread_id_for_event("market_news"), 111)
            for event in ("position_news", "watchlist_news", "watchlist_news_correction", "stock_news", "correction", "news_status"):
                self.assertEqual(thread_id_for_event(event), 112)
            self.assertEqual(thread_id_for_event("new_signal"), 211)
            self.assertEqual(thread_id_for_event("signals_status"), 211)
            for event in ("entry", "entry_chart", "tp", "stop", "sell", "stop_change"):
                self.assertEqual(thread_id_for_event(event), 212)
            self.assertEqual(thread_id_for_event("portfolio_status"), 303)

    def test_missing_or_invalid_thread_falls_back_to_general_chat(self):
        with patch.dict(os.environ, {
            "TELEGRAM_NEWS_THREAD_ID": "invalid",
            "TELEGRAM_PERSONAL_NEWS_THREAD_ID": "",
            "TELEGRAM_TRADING_THREAD_ID": "",
            "TELEGRAM_MARKET_NEWS_THREAD_ID": "",
            "TELEGRAM_STOCK_NEWS_THREAD_ID": "",
            "TELEGRAM_SIGNALS_THREAD_ID": "",
            "TELEGRAM_TRADES_THREAD_ID": "",
            "TELEGRAM_PORTFOLIO_THREAD_ID": "",
        }, clear=False):
            self.assertEqual(destination_fields("-1001", "position_news"), {"chat_id": "-1001"})
            self.assertEqual(destination_fields("-1001", "entry"), {"chat_id": "-1001"})
            self.assertEqual(destination_fields("-1001", "portfolio_status"), {"chat_id": "-1001"})
            self.assertEqual(destination_fields("-1001", None), {"chat_id": "-1001"})

    def test_new_routes_fall_back_to_legacy_topic_ids_during_upgrade(self):
        with patch.dict(os.environ, {
            "TELEGRAM_NEWS_THREAD_ID": "101", "TELEGRAM_TRADING_THREAD_ID": "202",
            "TELEGRAM_MARKET_NEWS_THREAD_ID": "", "TELEGRAM_STOCK_NEWS_THREAD_ID": "",
            "TELEGRAM_SIGNALS_THREAD_ID": "", "TELEGRAM_TRADES_THREAD_ID": "",
        }, clear=False):
            self.assertEqual(thread_id_for_event("market_news"), 101)
            self.assertEqual(thread_id_for_event("stock_news"), 101)
            self.assertEqual(thread_id_for_event("new_signal"), 202)
            self.assertEqual(thread_id_for_event("tp"), 202)


if __name__ == "__main__":
    unittest.main()
