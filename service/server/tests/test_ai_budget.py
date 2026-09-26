import os
import unittest
from unittest.mock import patch, MagicMock
import ai_budget


class BudgetTests(unittest.TestCase):
    def probe(self, usage):
        response=MagicMock()
        response.json.return_value={'data':{'usage_monthly':usage}}
        return response

    def test_local_monitor_has_no_provider_dependency(self):
        with patch.dict(os.environ,{'AI_TRADER_CLOUD':'false'}), patch('ai_budget.requests.get') as get:
            ai_budget.check()
            get.assert_not_called()

    def test_under_cap_persists_usage(self):
        with patch.dict(os.environ,{'AI_TRADER_CLOUD':'true','OPENROUTER_API_KEY':'test'}), patch('ai_budget.requests.get',return_value=self.probe(18)), patch('ai_budget.persist') as persist:
            ai_budget.check()
            self.assertEqual(persist.call_args.args[:2],(18,20))

    def test_exhaustion_stops_ai(self):
        with patch.dict(os.environ,{'AI_TRADER_CLOUD':'true','OPENROUTER_API_KEY':'test'}), patch('ai_budget.requests.get',return_value=self.probe(20)), patch('ai_budget.persist'):
            with self.assertRaisesRegex(ai_budget.BudgetUnavailable,'exhausted'):
                ai_budget.check()

    def test_missing_usage_and_network_fail_closed(self):
        for value in (None, -1, float('nan'), True):
            with self.subTest(value=value), patch.dict(os.environ,{'AI_TRADER_CLOUD':'true','OPENROUTER_API_KEY':'test'}), patch('ai_budget.requests.get',return_value=self.probe(value)):
                with self.assertRaises(ai_budget.BudgetUnavailable): ai_budget.check()
        with patch.dict(os.environ,{'AI_TRADER_CLOUD':'true','OPENROUTER_API_KEY':'test'}), patch('ai_budget.requests.get',side_effect=TimeoutError('private detail')):
            with self.assertRaisesRegex(ai_budget.BudgetUnavailable,'verification_failed_closed'): ai_budget.check()

    def test_guard_does_not_retry_blocked_news(self):
        import ai_provider
        with patch.dict(os.environ,{'OPENROUTER_NEWS_MODEL':'model','OPENROUTER_API_KEY':'test'}), patch('ai_budget.check',side_effect=ai_budget.BudgetUnavailable('exhausted')), patch('ai_provider.requests.post') as post:
            with self.assertRaises(ai_budget.BudgetUnavailable): ai_provider.json_completion('system',{})
            post.assert_not_called()

    def test_cutover_boundary_blocks_old_news_only(self):
        import scanner_engine
        cur=MagicMock()
        cur.fetchone.return_value=None
        with patch.dict(os.environ,{'TELEGRAM_NEWS_NOT_BEFORE':'2026-09-26T10:00:00Z'}):
            for kind in ('market_news','position_news','watchlist_news','stock_news'):
                scanner_engine.enqueue_telegram(cur,'old',kind,'old',published_at='2026-09-25T10:00:00Z')
                scanner_engine.enqueue_telegram(cur,'missing',kind,'unknown')
            cur.execute.assert_not_called()
            scanner_engine.enqueue_telegram(cur,'new','market_news','new',published_at='2026-09-26T10:00:01Z')
            self.assertEqual(cur.execute.call_count,2)
            cur.reset_mock()
            scanner_engine.enqueue_telegram(cur,'fill','tp','lifecycle')
            self.assertEqual(cur.execute.call_count,2)
