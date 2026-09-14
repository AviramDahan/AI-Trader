"""Migrate/provision the non-admin stock scanner without emitting credentials."""
import secrets
import sqlite3
import sys
from datetime import date

from bootstrap_private_setup import (ROOT, PRIVATE_FILE, ENCRYPTED_FILE, ENV_FILE, DB_FILE,
                                     _restrict_permissions, _protect_for_current_windows_user)
from dotenv import dotenv_values, set_key, unset_key

OLD_NAME = "ollama-paper-agent"
NAME = "us-stock-scanner"


def main():
    if not PRIVATE_FILE.exists() or not ENV_FILE.exists():
        raise RuntimeError("Initialize the private setup first")
    sys.path.insert(0, str(ROOT / "service" / "server"))
    from utils import hash_password
    created = False
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute("SELECT id, token FROM agents WHERE name=?", (NAME,)).fetchone()
        if not row:
            old = connection.execute("SELECT id, token FROM agents WHERE name=?", (OLD_NAME,)).fetchone()
            if old:
                connection.execute("UPDATE agents SET name=?, email=? WHERE id=?",
                                   (NAME, NAME + "@localhost.invalid", old[0]))
                row = old
            else:
                password, token = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
                cursor = connection.execute(
                    "INSERT INTO agents(name,email,password_hash,token,role,cash) VALUES(?,?,?,?,?,?)",
                    (NAME, NAME + "@localhost.invalid", hash_password(password), token, "agent", 100000))
                row = (cursor.lastrowid, token)
                created = True
        token = row[1]
    private_text = PRIVATE_FILE.read_text(encoding="utf-8")
    if created:
        section = {"Service": "Local US stock scanner", "Purpose": "Autonomous US-stock PAPER signals",
            "Website": "https://aviramdahan.github.io/AI-Trader/", "Account email": NAME + "@localhost.invalid",
            "Username": NAME, "Password": password, "API key": token, "API secret/token": token,
            "Account/project ID": str(row[0]), "Free plan/tier": "Local / free",
            "Environment variable name": "STOCK_SCANNER_TOKEN, STOCK_SCANNER_ENABLED",
            "Where the secret is stored": "Private .env; ignored SQLite; this private backup",
            "Date created": date.today().isoformat(), "Where it is used": "Loopback-only original simulated-trading API",
            "Notes": "Non-admin; no brokerage credentials; US stocks only; PAPER TRADING ONLY."}
        private_text += "\n\n" + "\n".join(f"{key}: {value}" for key, value in section.items()) + "\n"
    else:
        # Preserve every generated secret while reflecting the renamed identity/purpose.
        private_text = private_text.replace("Username: ollama-paper-agent", "Username: us-stock-scanner")
        private_text = private_text.replace("Account email: ollama-paper-agent@localhost.invalid", "Account email: us-stock-scanner@localhost.invalid")
        private_text = private_text.replace("Service: Local Ollama paper agent", "Service: Local US stock scanner")
        private_text = private_text.replace("Purpose: Automated virtual BTC research and trading", "Purpose: Autonomous US-stock PAPER signals")
        private_text = private_text.replace("PAPER_AGENT_TOKEN, PAPER_AGENT_ENABLED", "STOCK_SCANNER_TOKEN, STOCK_SCANNER_ENABLED")
        private_text = private_text.replace("max $25 virtual order, $100 exposure, four orders/day.",
            "US stocks only; configurable filters and position caps; no brokerage credentials.")
    PRIVATE_FILE.write_text(private_text, encoding="utf-8")
    set_key(str(ENV_FILE), "STOCK_SCANNER_TOKEN", token)
    defaults = {"STOCK_SCANNER_ENABLED": "true", "STOCK_SCANNER_UNIVERSE": "sp500,nasdaq100",
        "STOCK_SCANNER_SCAN_INTERVAL": "1800", "STOCK_SCANNER_CANDIDATE_LIMIT": "8",
        "STOCK_SCANNER_MAX_SIGNALS_PER_SCAN": "3", "STOCK_SCANNER_MIN_DOLLAR_VOLUME": "50000000",
        "STOCK_SCANNER_MIN_ATR_PCT": "1.0", "STOCK_SCANNER_MAX_ATR_PCT": "8.0",
        "STOCK_SCANNER_MIN_CONFIDENCE": "0.80", "STOCK_SCANNER_MIN_RISK_REWARD": "2.0",
        "STOCK_SCANNER_DUPLICATE_COOLDOWN_HOURS": "24", "STOCK_SCANNER_NEWS_MAX_AGE_HOURS": "72",
        "STOCK_SCANNER_PAPER_NOTIONAL": "100", "STOCK_SCANNER_MAX_SYMBOL_EXPOSURE": "250",
        "STOCK_SCANNER_MAX_TOTAL_EXPOSURE": "1000", "STOCK_SCANNER_MIN_TECHNICAL_SCORE": "5"}
    current = dotenv_values(ENV_FILE)
    for key, value in defaults.items():
        if not current.get(key):
            set_key(str(ENV_FILE), key, value)
    set_key(str(ENV_FILE), "PAPER_AGENT_ENABLED", "false")
    if current.get("PAPER_AGENT_TOKEN"):
        unset_key(str(ENV_FILE), "PAPER_AGENT_TOKEN")
    for file in (ENV_FILE, PRIVATE_FILE, DB_FILE):
        _restrict_permissions(file)
    encrypted = _protect_for_current_windows_user(PRIVATE_FILE.read_bytes())
    if encrypted:
        ENCRYPTED_FILE.write_bytes(encrypted)
        _restrict_permissions(ENCRYPTED_FILE)
    print("US stock scanner configured. Existing credentials preserved and BTC-only agent disabled.")


if __name__ == "__main__":
    main()
