"""Create the local-only admin account, configuration, and credential backup."""

from __future__ import annotations

import base64
import os
import secrets
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_FILE = ROOT / "PRIVATE_SETUP_CREDENTIALS.txt"
ENCRYPTED_FILE = ROOT / "PRIVATE_SETUP_CREDENTIALS.encrypted"
ENV_FILE = ROOT / ".env"
DB_FILE = ROOT / "service" / "server" / "data" / "clawtrader.db"
ADMIN_NAME = "ai-trader-admin"
ADMIN_EMAIL = "ai-trader-admin@localhost.invalid"
PAGES_ORIGIN = "https://aviramdahan.github.io"


def _protect_for_current_windows_user(data: bytes) -> bytes | None:
    if os.name != "nt":
        return None
    script = (
        "Add-Type -AssemblyName System.Security;"
        "$bytes=[Convert]::FromBase64String($env:AI_TRADER_PLAINTEXT_B64);"
        "$protected=[Security.Cryptography.ProtectedData]::Protect("
        "$bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser);"
        "[Convert]::ToBase64String($protected)"
    )
    env = os.environ.copy()
    env["AI_TRADER_PLAINTEXT_B64"] = base64.b64encode(data).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return base64.b64decode(result.stdout.strip())


def _restrict_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return
    identity = subprocess.run(
        ["whoami"], capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(F)"],
        capture_output=True,
        check=False,
    )


def _write_local_env() -> None:
    content = "\n".join(
        [
            "ENVIRONMENT=development",
            "DATABASE_URL=",
            "ALPHA_VANTAGE_API_KEY=demo",
            "OLLAMA_BASE_URL=http://127.0.0.1:11434",
            "OLLAMA_MODEL=qwen3.5:9b-q4_K_M",
            "OLLAMA_TIMEOUT_SECONDS=120",
            "CLAWTRADER_CORS_ORIGINS=http://localhost:3000,https://aviramdahan.github.io",
            "AI_TRADER_ADMIN_AGENTS=ai-trader-admin",
            "AI_TRADER_API_BACKGROUND_TASKS=true",
            "ALLOW_SYNC_PRICE_FETCH_IN_API=true",
            "API_STDERR_LOG=false",
            "REDIS_ENABLED=false",
            "",
        ]
    )
    ENV_FILE.write_text(content, encoding="utf-8")
    _restrict_permissions(ENV_FILE)


def _create_admin() -> tuple[str, str]:
    sys.path.insert(0, str(ROOT / "service" / "server"))
    from database import init_database
    from utils import hash_password

    init_database()
    password = secrets.token_urlsafe(30)
    token = secrets.token_urlsafe(40)
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            "SELECT id FROM agents WHERE name = ?", (ADMIN_NAME,)
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE agents SET email = ?, password_hash = ?, token = ?, role = 'admin' WHERE id = ?",
                (ADMIN_EMAIL, hash_password(password), token, row[0]),
            )
        else:
            connection.execute(
                """
                INSERT INTO agents (name, email, password_hash, token, role, cash)
                VALUES (?, ?, ?, ?, 'admin', 100000.0)
                """,
                (ADMIN_NAME, ADMIN_EMAIL, hash_password(password), token),
            )
    return password, token


def _credential_document(password: str, token: str) -> str:
    today = date.today().isoformat()
    sections = [
        {
            "Service": "AI-Trader local application",
            "Purpose": "Paper-trading administrator/test account",
            "Website": "https://aviramdahan.github.io/AI-Trader/",
            "Account email": ADMIN_EMAIL,
            "Username": ADMIN_NAME,
            "Password": password,
            "API key": token,
            "API secret/token": token,
            "Account/project ID": "Local SQLite agent record",
            "Free plan/tier": "Open source / local",
            "Environment variable name": "AI_TRADER_ADMIN_AGENTS (identifier only)",
            "Where the secret is stored": "This file; password hash and API token in ignored local SQLite database",
            "Date created": today,
            "Where it is used": "Existing AI-Trader login, admin experiments, signals and paper trading",
            "Notes": "Paper trading only; no brokerage credentials configured.",
        },
        {
            "Service": "Ollama",
            "Purpose": "Local AI-generated market analysis summaries",
            "Website": "https://ollama.com/",
            "Account email": "Not required",
            "Username": "Not required",
            "Password": "Not required",
            "API key": "Not required",
            "API secret/token": "Not required",
            "Account/project ID": "Local model qwen3.5:9b-q4_K_M",
            "Free plan/tier": "Free / local open-source runtime",
            "Environment variable name": "OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS",
            "Where the secret is stored": "No secret exists; configuration is in the ignored local .env file",
            "Date created": today,
            "Where it is used": "AI-generated stock market-intelligence summaries",
            "Notes": "Runs locally at 127.0.0.1 and falls back to deterministic summaries when unavailable.",
        },
        {
            "Service": "GitHub",
            "Purpose": "Fork and GitHub Pages deployment",
            "Website": "https://github.com/AviramDahan/AI-Trader",
            "Account email": "Existing connected GitHub account",
            "Username": "AviramDahan",
            "Password": "Not created or accessed",
            "API key": "Not created; GitHub CLI uses the existing OS keyring credential",
            "API secret/token": "Not copied into this project",
            "Account/project ID": "AviramDahan/AI-Trader",
            "Free plan/tier": "GitHub Free / GitHub Pages",
            "Environment variable name": "BACKEND_URL (GitHub Actions variable; public URL only)",
            "Where the secret is stored": "No new GitHub secret required; GITHUB_TOKEN is workflow-provided",
            "Date created": today,
            "Where it is used": "Fork, Actions and Pages",
            "Notes": "BACKEND_URL is non-secret and intentionally stored as a repository variable.",
        },
        {
            "Service": "Serveo HTTPS tunnel",
            "Purpose": "HTTPS ingress to the local paper-trading backend",
            "Website": "https://serveo.net/",
            "Account email": "Not required",
            "Username": "Not required",
            "Password": "Not required",
            "API key": "Not required",
            "API secret/token": "Not required",
            "Account/project ID": "Ephemeral anonymous reverse tunnel",
            "Free plan/tier": "Free anonymous tunnel",
            "Environment variable name": "BACKEND_URL (public URL only)",
            "Where the secret is stored": "No tunnel secret exists",
            "Date created": today,
            "Where it is used": "Public HTTPS backend ingress",
            "Notes": "The hostname changes when restarted; start-ai-trader.ps1 updates GitHub Pages automatically. Paper-trading backend only.",
        },
        {
            "Service": "Public market-data providers",
            "Purpose": "Crypto, Polymarket and US-stock paper-market data",
            "Website": "https://api.hyperliquid.xyz; https://polymarket.com; https://finance.yahoo.com",
            "Account email": "Not required",
            "Username": "Not required",
            "Password": "Not required",
            "API key": "Not required",
            "API secret/token": "Not required",
            "Account/project ID": "Not required",
            "Free plan/tier": "Public endpoints / yfinance fallback",
            "Environment variable name": "HYPERLIQUID_API_URL, POLYMARKET_GAMMA_BASE_URL, POLYMARKET_CLOB_BASE_URL",
            "Where the secret is stored": "No secret exists",
            "Date created": today,
            "Where it is used": "Quotes, market data and paper-trade price verification",
            "Notes": "Alpha Vantage remains on the upstream demo setting; yfinance is the no-key US-stock fallback.",
        },
    ]
    lines = ["AI-Trader private setup credentials", "DO NOT COMMIT OR SHARE", ""]
    for section in sections:
        lines.extend(f"{key}: {value}" for key, value in section.items())
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    if PRIVATE_FILE.exists() or ENV_FILE.exists():
        raise RuntimeError("Existing private setup found. Refusing to overwrite configuration or rotate credentials.")
    _write_local_env()
    password, token = _create_admin()
    content = _credential_document(password, token).encode("utf-8")
    PRIVATE_FILE.write_bytes(content)
    _restrict_permissions(PRIVATE_FILE)
    protected = _protect_for_current_windows_user(content)
    if protected:
        ENCRYPTED_FILE.write_bytes(protected)
        _restrict_permissions(ENCRYPTED_FILE)
    print("Private setup initialized without displaying credentials.")


if __name__ == "__main__":
    main()
