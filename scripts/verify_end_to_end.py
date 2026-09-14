"""Verify the deployed API path without displaying private credentials."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
DB_FILE = ROOT / "service" / "server" / "data" / "clawtrader.db"
URL_FILE = ROOT / ".runtime" / "backend-url.txt"
PAGES_ORIGIN = "https://aviramdahan.github.io"


def require(response: requests.Response, label: str) -> None:
    if not response.ok:
        raise RuntimeError(f"{label} failed with HTTP {response.status_code}")
    if response.request.method != "OPTIONS":
        response.json()  # Reject tunnel warning pages masquerading as HTTP 200.
    print(f"PASS {label}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", "-BackendUrl")
    parser.add_argument("--require-stock-signal", action="store_true",
                        help="Require an already-published live scanner signal and tracked paper position")
    args = parser.parse_args()
    if not URL_FILE.exists():
        raise RuntimeError("Backend URL is missing; run scripts/start-ai-trader.ps1 first")
    backend_url = (args.backend_url or URL_FILE.read_text(encoding="utf-8")).strip().rstrip("/")
    hostname = urlparse(backend_url).hostname
    if not hostname:
        raise RuntimeError("Invalid backend URL")

    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            "SELECT token FROM agents WHERE name = ?", ("ai-trader-admin",)
        ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("Admin agent token is missing")

    session = requests.Session()
    session.trust_env = False
    headers = {"Authorization": f"Bearer {row[0]}"}

    with nullcontext():  # Use the same normal DNS path as visitors.
        require(session.get(f"{backend_url}/health", timeout=20), "HTTPS backend health")

        cors = session.options(
            f"{backend_url}/api/signals/feed",
            headers={
                "Origin": PAGES_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
            timeout=20,
        )
        require(cors, "GitHub Pages CORS preflight")
        if cors.headers.get("access-control-allow-origin") != PAGES_ORIGIN:
            raise RuntimeError("CORS response does not allow the GitHub Pages origin")
        print("PASS GitHub Pages CORS origin")

        require(session.get(f"{backend_url}/api/claw/agents/count", timeout=20), "agents")
        require(session.get(f"{backend_url}/api/signals/feed", timeout=20), "signals")
        require(session.get(f"{backend_url}/api/trending", timeout=20), "dashboard trending")
        overview = session.get(f"{backend_url}/api/market-intel/overview", timeout=30)
        require(overview, "market-intel endpoint connectivity")
        overview_available = overview.json().get("available", False)
        if not overview_available:
            print("GAP Financial Events: no market-intelligence snapshot is available")
        stock_quote = session.get(
                f"{backend_url}/api/price",
                params={"symbol": "AAPL", "market": "us-stock"},
                headers=headers,
                timeout=30,
            )
        require(stock_quote, "current US-stock quote")
        if float(stock_quote.json().get("price") or 0) <= 0:
            raise RuntimeError("US-stock quote is invalid")
        require(
            session.get(f"{backend_url}/api/experiments", headers=headers, timeout=20),
            "experiments admin",
        )
        require(
            session.get(f"{backend_url}/api/positions", headers=headers, timeout=30),
            "positions",
        )

        activity = session.get(f"{backend_url}/api/runtime/activity", timeout=20)
        require(activity, "stock scanner status")
        activity_data = activity.json()
        if not activity_data.get("paper_only") or activity_data.get("agent") != "us-stock-scanner":
            raise RuntimeError("US-stock paper scanner is not active")

        if not args.require_stock_signal:
            print("PASS read-only API verification; no test signal was injected")
            if not overview_available:
                raise RuntimeError("Incomplete E2E: Financial Events has no snapshot")
            return
        with sqlite3.connect(DB_FILE) as connection:
            scanner = connection.execute("SELECT id, token FROM agents WHERE name=?", ("us-stock-scanner",)).fetchone()
        if not scanner:
            raise RuntimeError("Scanner identity is missing")
        scanner_headers = {"Authorization": f"Bearer {scanner[1]}"}
        signals = session.get(f"{backend_url}/api/signals/{scanner[0]}?message_type=operation&limit=50", timeout=30).json().get("signals", [])
        signal = next((item for item in signals if item.get("market") == "us-stock" and
                       str(item.get("content") or "").startswith("US STOCK SCANNER | PAPER TRADING ONLY")), None)
        if not signal:
            raise RuntimeError("No live strong stock signal has been published yet")
        for field in ("Ticker:", "Company:", "Action:", "Entry:", "Take Profit:", "Stop Loss:",
                      "Risk/Reward:", "Confidence:", "Time Horizon:", "Reason:", "Relevant News:", "Timestamp:"):
            if field not in signal["content"]:
                raise RuntimeError(f"Stock signal is missing {field}")
        positions = session.get(f"{backend_url}/api/positions", headers=scanner_headers, timeout=30)
        require(positions, "scanner paper positions")
        if not any(item.get("symbol") == signal.get("symbol") for item in positions.json().get("positions", [])):
            raise RuntimeError("Live scanner signal is not represented in paper positions")
        print("PASS live stock signal format, UI feed record and paper position")

    if not overview_available:
        raise RuntimeError("Incomplete E2E: trading checks passed but Financial Events has no snapshot")
    print("End-to-end API verification completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
