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
    parser.add_argument("--paper-trade", action="store_true", help="Submit one simulated BTC order")
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
        require(
            session.get(f"{backend_url}/api/market-intel/overview", timeout=30),
            "market data and dashboard overview",
        )
        require(
            session.get(
                f"{backend_url}/api/price",
                params={"symbol": "BTC", "market": "crypto"},
                headers=headers,
                timeout=30,
            ),
            "public crypto quote",
        )
        require(
            session.get(f"{backend_url}/api/experiments", headers=headers, timeout=20),
            "experiments admin",
        )
        require(
            session.get(f"{backend_url}/api/positions", headers=headers, timeout=30),
            "positions",
        )

        if not args.paper_trade:
            print("PASS read-only API verification; paper trade not requested")
            return

        paper_trade = session.post(
            f"{backend_url}/api/signals/realtime",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "market": "crypto",
                "action": "buy",
                "symbol": "BTC",
                "price": 1,
                "quantity": 0.0001,
                "content": "Automated end-to-end paper-trading verification",
                "executed_at": "now",
            },
            timeout=30,
        )
        require(paper_trade, "paper trade submission")

        positions = session.get(f"{backend_url}/api/positions", headers=headers, timeout=30)
        require(positions, "paper position after trade")
        if not positions.json().get("positions"):
            raise RuntimeError("Paper trade did not create a position")
        print("PASS end-to-end paper position persisted")

    print("End-to-end API verification completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
