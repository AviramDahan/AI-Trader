"""Transport only: no payload, timestamp, error or private route changes."""
import unittest

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from scanner_read_compression import ScannerReadCompression


class ScannerCompressionTest(unittest.IsolatedAsyncioTestCase):
    async def test_public_only_and_payload_unchanged(self):
        app = FastAPI()
        app.add_middleware(ScannerReadCompression)
        app.add_middleware(CORSMiddleware, allow_origins=["https://example.test"])
        data = {"generated_at": "2026-10-10T08:00:00Z", "records": ["fixture" * 100] * 100}
        for path in ("/api/scanner/dashboard", "/api/scanner/research", "/health", "/api/private"):
            app.add_api_route(path, lambda: data, methods=["GET", "POST"])
        app.add_api_route("/api/scanner/quotes", lambda: {"quotes": []})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for path in ("/api/scanner/dashboard", "/api/scanner/research"):
                compressed = await client.get(path, headers={"Accept-Encoding": "gzip", "Origin": "https://example.test"})
                self.assertEqual(compressed.headers["content-encoding"], "gzip")
                self.assertEqual(compressed.json(), data)
                self.assertLess(int(compressed.headers["content-length"]), len(compressed.content) / 10)
                self.assertIn("Accept-Encoding", compressed.headers["vary"])
                self.assertEqual(compressed.headers["access-control-allow-origin"], "https://example.test")
                for coding in ("identity", "gzip;q=0", "gzip;q=invalid"):
                    plain = await client.get(path, headers={"Accept-Encoding": coding})
                    self.assertNotIn("content-encoding", plain.headers)
                    self.assertEqual(plain.json(), data)
                write = await client.post(path, headers={"Accept-Encoding": "gzip"})
                self.assertNotIn("content-encoding", write.headers)
            for path in ("/health", "/api/private", "/api/scanner/quotes"):
                result = await client.get(path, headers={"Accept-Encoding": "gzip"})
                self.assertNotIn("content-encoding", result.headers)

    async def test_errors_and_small_or_preencoded_responses(self):
        app = FastAPI()
        app.add_middleware(ScannerReadCompression)
        app.add_api_route("/api/scanner/dashboard", lambda: JSONResponse({"detail": "unavailable"}, status_code=503))
        app.add_api_route("/api/scanner/research", lambda: JSONResponse({"small": True}, headers={"Content-Encoding": "identity"}))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            failure = await client.get("/api/scanner/dashboard")
            self.assertEqual(failure.status_code, 503)
            self.assertEqual(failure.json(), {"detail": "unavailable"})
            self.assertNotIn("content-encoding", failure.headers)
            existing = await client.get("/api/scanner/research")
            self.assertEqual(existing.headers["content-encoding"], "identity")
            self.assertEqual(existing.json(), {"small": True})
