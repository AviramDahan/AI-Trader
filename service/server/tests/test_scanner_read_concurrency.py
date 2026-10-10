"""Read-only HTTP handlers must not block the API event loop (no DB/providers)."""
import asyncio
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import routes_scanner


class ScannerReadConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_read_does_not_block_health_or_other_reads(self):
        for endpoint, function in (('dashboard', 'dashboard_payload'), ('quotes', 'quotes_payload')):
            with self.subTest(endpoint=endpoint):
                entered, release = threading.Event(), threading.Event()

                def slow_read():
                    entered.set()
                    release.wait(2)  # Safety bound also makes the old async handler fail.
                    return {'source': 'synthetic', 'market': {'is_open': False}}

                app = FastAPI()
                routes_scanner.register_scanner_routes(app)

                @app.get('/health')
                async def health():
                    return {'status': 'ok'}

                with patch.object(routes_scanner, function, slow_read), patch.object(routes_scanner, 'public_status', return_value={'state': 'retained'}):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated.invalid') as client:
                        heavy = asyncio.create_task(client.get('/api/scanner/' + endpoint))
                        try:
                            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                            response = await client.get('/health')
                            self.assertEqual(response.json(), {'status': 'ok'})
                            self.assertFalse(heavy.done(), 'The read completed before health could run: event loop blocked')
                        finally:
                            release.set()
                            result = await heavy
                        expected = {'source': 'synthetic', 'market': {'is_open': False}}
                        if endpoint == 'dashboard':
                            expected['activity'] = {'state': 'retained'}
                        self.assertEqual(result.status_code, 200)
                        self.assertEqual(result.json(), expected)

    async def test_read_failure_is_not_a_success_or_a_trading_write(self):
        app = FastAPI()
        routes_scanner.register_scanner_routes(app)
        with patch.object(routes_scanner, 'dashboard_payload', side_effect=RuntimeError('synthetic read failure')), \
                patch.object(routes_scanner, 'set_active_strategy') as strategy, \
                patch.object(routes_scanner, 'set_news_watchlist') as watchlist:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://isolated.invalid') as client:
                result = await client.get('/api/scanner/dashboard')
            self.assertEqual(result.status_code, 500)
            strategy.assert_not_called()
            watchlist.assert_not_called()
