import sys
import unittest
import tempfile
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paper_agent
import market_intel


class PaperSafetyTests(unittest.TestCase):
    def cycle(self, action, *, pending=False, execution_error=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'paper.json'
            path.write_text(json.dumps({"order_pending": pending}), encoding="utf-8")
            session = Mock()
            session.headers = {}
            orders = []
            def request(method, url, **kwargs):
                data = {}
                if '/price?' in url:
                    data = {"price": 100000}
                elif url.endswith('/positions'):
                    data = {"positions": [], "cash": 100000}
                elif url.endswith('/signals/realtime'):
                    orders.append(kwargs['json'])
                    if execution_error:
                        raise paper_agent.requests.Timeout()
                response = Mock()
                response.json.return_value = data
                return response
            session.request.side_effect = request
            model = Mock()
            model.json.return_value = {"message": {"content": json.dumps({"action": action, "confidence": .9, "reason": "Controlled test"})}}
            now = datetime.now(timezone.utc).isoformat()
            news = {"created_at": now, "items": [{"title": "Test data", "source": "Test", "time_published": now}]}
            with patch.object(paper_agent, 'STATE_FILE', path), \
                 patch.dict(paper_agent.os.environ, {'PAPER_AGENT_TOKEN': 'test-only'}), \
                 patch.object(paper_agent.requests, 'Session', return_value=session), \
                 patch.object(paper_agent.requests, 'post', return_value=model), \
                 patch.object(market_intel, '_load_latest_news_snapshot', return_value=news):
                if execution_error:
                    with self.assertRaises(paper_agent.requests.Timeout):
                        paper_agent.run_cycle()
                else:
                    paper_agent.run_cycle()
                state = paper_agent.read_state()
            return state, orders

    def test_hold_is_logged_without_order(self):
        state, orders = self.cycle('hold')
        self.assertEqual(orders, [])
        self.assertEqual(state['last_decision'], 'HOLD')
        self.assertEqual(state['status'], 'waiting')

    def test_valid_buy_uses_original_paper_endpoint(self):
        state, orders = self.cycle('buy')
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['symbol'], 'BTC')
        self.assertLessEqual(orders[0]['price'] * orders[0]['quantity'], 25)
        self.assertEqual(state['last_decision'], 'BUY')
        self.assertFalse(state['order_pending'])

    def test_uncertain_order_is_persisted_and_never_retried(self):
        state, orders = self.cycle('buy', execution_error=True)
        self.assertTrue(state['order_pending'])
        self.assertEqual(len(orders), 1)
        state, orders = self.cycle('buy', pending=True)
        self.assertEqual(orders, [])
        self.assertTrue(state['order_pending'])

    def test_ai_output_is_strict_and_fails_closed(self):
        for payload in ({"action": "transfer", "confidence": 1, "reason": "x"},
                        {"action": "buy", "confidence": float("nan"), "reason": "x"},
                        {"action": "buy", "confidence": True, "reason": "x"},
                        {"action": "buy", "confidence": 1, "reason": ""}):
            with self.assertRaises(ValueError):
                paper_agent.validate_decision(payload)

    def test_risk_caps(self):
        quantity = paper_agent.allowed_quantity("buy", .9, 100000, 0, 100000, 0)
        self.assertLessEqual(quantity * 100000, 25)
        self.assertEqual(paper_agent.allowed_quantity("buy", .7, 100000, 0, 100000, 0), 0)
        self.assertEqual(paper_agent.allowed_quantity("buy", 1, 100000, .001, 100000, 0), 0)
        self.assertEqual(paper_agent.allowed_quantity("buy", 1, 100000, 0, 100000, 4), 0)
        self.assertEqual(paper_agent.allowed_quantity("sell", 1, 100000, 0, 100000, 0), 0)
        self.assertEqual(paper_agent.allowed_quantity("buy", 1, float("nan"), 0, 100000, 0), 0)
        self.assertEqual(paper_agent.allowed_quantity("hold", 1, 100000, 0, 100000, 0), 0)

    def test_status_exposes_only_allowlist(self):
        with patch.object(paper_agent, "read_state", return_value={"token": "not-for-ui", "events": [], "next_run_at": 0}):
            self.assertNotIn("token", paper_agent.public_status())
            self.assertTrue(paper_agent.public_status()["stale"])

    def test_rss_keeps_attribution_and_does_not_invent_sentiment(self):
        response = Mock(content=b'<rss><channel><item><title>Official release</title><link>https://example.com/news</link><pubDate>Mon, 14 Sep 2020 10:00:00 GMT</pubDate></item></channel></rss>')
        with patch.object(market_intel.requests, "get", return_value=response):
            items = market_intel._fetch_rss_news("macro")
        self.assertEqual(items[0]["source"], "Federal Reserve")
        self.assertEqual(items[0]["overall_sentiment_label"], "unassessed")
        self.assertTrue(items[0]["time_published"].startswith("2020-09-14"))

    def test_invalid_feed_fails_not_empty_success(self):
        with patch.object(market_intel.requests, "get", return_value=Mock(content=b'<rss/>')):
            with self.assertRaises(RuntimeError):
                market_intel._fetch_rss_news("crypto")


if __name__ == "__main__":
    unittest.main()
