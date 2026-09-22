"""Audit original paper positions; --apply backs up and adopts only coherent records.

Stop AI-Trader before --apply. Original position rows and original cash are
preserved. No historical replay, entry execution or Telegram test is performed.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service/server"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        import requests
        try:
            requests.get("http://127.0.0.1:8000/health", timeout=2).raise_for_status()
        except requests.ConnectionError:
            pass
        else:
            raise SystemExit("Stop the backend before adoption.")
        backups = ROOT / ".runtime/backups"
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / ("pre-legacy-adoption-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".db")
        with sqlite3.connect(ROOT / "service/server/data/clawtrader.db") as source, sqlite3.connect(backup) as target:
            source.backup(target)
        from database import init_database
        init_database()
        from scanner_legacy import adopt_positions
        print(json.dumps({"backup": str(backup), **adopt_positions()}, indent=2))
    else:
        from scanner_legacy import audit_positions
        print(json.dumps([{"ticker": row["position"]["symbol"], "eligible": row["eligible"],
                           "issues": row["issues"], "adopted": row.get("adopted")}
                          for row in audit_positions()], indent=2))


if __name__ == "__main__":
    main()
