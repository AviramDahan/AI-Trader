"""Cloud role entrypoint: explicit tasks, database singleton, fail-stop readiness."""
import asyncio
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

ROLES = {
    "scanner": "telegram_news_stream,stock_scanner,stock_position_news,stock_news_feed,stock_news_ai,stock_news_translation",
    "monitor": "stock_signal_monitor,stock_quote_refresh",
    "telegram": "stock_telegram_outbox,stock_telegram_status",
}
ROLE_KEYS = {"scanner": 11, "monitor": 12, "telegram": 13}
SCHEMA_VERSION = 2
ACTIVE_LEASE = None


def assert_schema():
    from database import get_db_connection, using_postgres
    if not using_postgres():
        raise RuntimeError("cloud_requires_postgresql")
    with get_db_connection() as conn:
        row = conn.cursor().execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        if row["version"] != SCHEMA_VERSION:
            raise RuntimeError("run_numbered_migrations_before_start")


class RoleLease:
    """Session advisory lock has no expiry that could overlap a slow worker.

    Lost connection terminates the whole process (including in-flight threads).
    Never release on SIGTERM before blocking work has ended.
    """
    def __init__(self, role):
        import psycopg
        from config import DATABASE_URL
        self.connection = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=5,
                                         options="-c statement_timeout=5000")
        self.mutex = threading.Lock()
        acquired = self.connection.execute("SELECT pg_try_advisory_lock(719322,%s)", (ROLE_KEYS[role],)).fetchone()[0]
        if not acquired:
            self.connection.close()
            raise RuntimeError("role_already_owned:" + role)

    def check(self):
        with self.mutex:
            self.connection.execute("SELECT 1")

    def close(self):
        self.connection.close()


def guard_lease():
    if ACTIVE_LEASE is not None:
        try:
            ACTIVE_LEASE.check()
        except Exception:
            os._exit(71)  # Do not let old worker threads survive lost ownership.


def probe(role):
    assert_schema()
    from database import get_db_connection
    with get_db_connection() as conn:
        row = conn.cursor().execute("""SELECT count(*) n FROM agents a
            JOIN scanner_accounts c ON c.agent_id=a.id WHERE a.name='us-stock-scanner'""").fetchone()
        if row['n'] != 1:
            raise RuntimeError("active_portfolio_not_initialized")
    if role == "api":
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3).close()
    else:
        state = json.loads(Path("/tmp/role-health.json").read_text())
        if state["role"] != role or time.time() - state["at"] > 30:
            raise RuntimeError("role_heartbeat_stale")
        if role == 'monitor' and time.time() - state['started_at'] > 90:
            from datetime import datetime
            with get_db_connection() as conn:
                status = conn.cursor().execute("SELECT status,last_attempt_at FROM scanner_service_status WHERE component='monitor'").fetchone()
            maximum_age = 2 * int(os.getenv('STOCK_SCANNER_LEVEL_MONITOR_INTERVAL','300')) + 180
            if not status or status['status'] == 'error' or not status['last_attempt_at']:
                raise RuntimeError('monitor_not_ready')
            if time.time() - datetime.fromisoformat(status['last_attempt_at'].replace('Z','+00:00')).timestamp() > maximum_age:
                raise RuntimeError('monitor_progress_stale')


async def run_role(role):
    global ACTIVE_LEASE
    assert_schema()
    ACTIVE_LEASE = RoleLease(role)
    if os.getenv("STOCK_SCANNER_ENABLED", "false").lower() != "true":
        raise RuntimeError("workers_disabled_enable_only_after_snapshot_validation")
    if role == 'scanner' and not all(os.getenv(key) for key in (
            'OPENROUTER_API_KEY','OPENROUTER_NEWS_MODEL','STOCK_SCANNER_FINAL_AI_MODEL')):
        raise RuntimeError('cloud_ai_configuration_missing')
    names = ROLES[role].split(',')
    if "telegram_news_stream" in names:
        from telegram_news_reader import streaming_enabled
        if not streaming_enabled():
            names.remove("telegram_news_stream")
    os.environ["AI_TRADER_BACKGROUND_TASKS"] = ','.join(names)
    from tasks import start_background_tasks
    tasks = start_background_tasks()
    started_at = time.time()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signame, stop.set)
    while not stop.is_set():
        guard_lease()
        if any(task.done() for task in tasks):
            os._exit(72)
        Path("/tmp/role-health.json").write_text(json.dumps({"role":role,"at":time.time(),'started_at':started_at}))
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
    # Terminate all background threads before the OS releases the PG lock.
    # Persistent transaction/cursor/outbox recovery handles interrupted work.
    os._exit(0)


def main():
    import config  # Load server-only secret files before any provider imports.
    role = sys.argv[1]
    os.environ['AI_TRADER_ROLE'] = role
    if role == "health":
        probe(sys.argv[2]); return
    if os.getenv("AI_TRADER_CLOUD") != "true":
        raise RuntimeError("cloud_entrypoint_requires_explicit_cloud_mode")
    if role == "migrate":
        from migrations import migrate
        migrate(); return
    if role == "api":
        assert_schema()
        os.environ["AI_TRADER_API_BACKGROUND_TASKS"] = "false"
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, workers=1)
        return
    if role not in ROLES:
        raise ValueError("unknown_cloud_role")
    asyncio.run(run_role(role))


if __name__ == "__main__":
    # Keep one module instance when database imports the guard.
    sys.modules["cloud_runtime"] = sys.modules[__name__]
    main()
