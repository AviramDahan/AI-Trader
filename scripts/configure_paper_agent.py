"""Idempotently provision a non-admin local agent; never emit credentials."""
import os
import secrets
import sqlite3
import sys
from datetime import date

from bootstrap_private_setup import (ROOT, PRIVATE_FILE, ENCRYPTED_FILE, ENV_FILE, DB_FILE,
                                     _restrict_permissions, _protect_for_current_windows_user)
from dotenv import set_key


def main():
    if not PRIVATE_FILE.exists():
        raise RuntimeError("Initialize the private admin backup first")
    sys.path.insert(0, str(ROOT / "service" / "server"))
    from utils import hash_password
    name = "ollama-paper-agent"
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute("SELECT id, token FROM agents WHERE name=?", (name,)).fetchone()
        if row:
            token = row[1]
            if "Username: ollama-paper-agent" not in PRIVATE_FILE.read_text(encoding="utf-8"):
                raise RuntimeError("Existing paper agent has no backup; refusing to rotate credentials")
        else:
            password, token = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
            cursor = conn.execute("INSERT INTO agents(name,email,password_hash,token,role,cash) VALUES(?,?,?,?,?,?)",
                (name, name + "@localhost.invalid", hash_password(password), token, "agent", 100000))
            section = {"Service": "Local Ollama paper agent", "Purpose": "Automated virtual BTC research and trading",
                "Website": "https://aviramdahan.github.io/AI-Trader/", "Account email": name + "@localhost.invalid",
                "Username": name, "Password": password, "API key": token, "API secret/token": token,
                "Account/project ID": str(cursor.lastrowid), "Free plan/tier": "Local / free",
                "Environment variable name": "PAPER_AGENT_TOKEN, PAPER_AGENT_ENABLED",
                "Where the secret is stored": "Private .env; ignored SQLite; this private backup",
                "Date created": date.today().isoformat(), "Where it is used": "Loopback-only original simulated-trading API",
                "Notes": "Not an admin. No exchange or brokerage account; max $25 virtual order, $100 exposure, four orders/day."}
            with PRIVATE_FILE.open("a", encoding="utf-8") as backup:
                backup.write("\n\n" + "\n".join(f"{k}: {v}" for k, v in section.items()) + "\n")
    for key, value in {"PAPER_AGENT_TOKEN": token, "PAPER_AGENT_ENABLED": "true",
                       "MARKET_NEWS_REFRESH_INTERVAL": "900", "AI_TRADER_API_BACKGROUND_TASKS": "true"}.items():
        set_key(str(ENV_FILE), key, value)
    for file in (ENV_FILE, PRIVATE_FILE, DB_FILE):
        _restrict_permissions(file)
    encrypted = _protect_for_current_windows_user(PRIVATE_FILE.read_bytes())
    if encrypted:
        ENCRYPTED_FILE.write_bytes(encrypted)
        _restrict_permissions(ENCRYPTED_FILE)
    print("Paper agent configured. Existing admin credentials preserved; private backup updated.")


if __name__ == "__main__":
    main()
