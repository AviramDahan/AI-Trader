"""Grant an existing agent scanner-only management permission.

The optional token rotation is intentionally silent: secret values are never
printed or written anywhere outside the configured database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "service" / "server"
sys.path.insert(0, str(SERVER_DIR))

import database  # noqa: E402
from services import _issue_agent_token  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="Exact existing agent name")
    parser.add_argument(
        "--rotate-token",
        action="store_true",
        help="Invalidate the current API token without printing the replacement",
    )
    args = parser.parse_args()

    database.init_database()
    conn = database.get_db_connection()
    try:
        row = conn.execute("SELECT id, name FROM agents WHERE name = ?", (args.name.strip(),)).fetchone()
        if not row:
            raise SystemExit("Agent was not found; no permission was changed.")
        agent_id = int(row["id"] if hasattr(row, "keys") else row[0])
        conn.execute(
            "INSERT INTO scanner_operators(agent_id) VALUES(?) ON CONFLICT(agent_id) DO NOTHING",
            (agent_id,),
        )
        conn.commit()
    finally:
        conn.close()

    if args.rotate_token:
        _issue_agent_token(agent_id)
    print(f"Scanner-only permission configured for {args.name.strip()}.")
    if args.rotate_token:
        print("The existing API token was rotated; its value was not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
