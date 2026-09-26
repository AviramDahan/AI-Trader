CREATE TABLE IF NOT EXISTS cloud_imports (
    snapshot_id TEXT PRIMARY KEY,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    manifest JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scanner_open_ticker
    ON scanner_trades(ticker, agent_id) WHERE status='open';
CREATE INDEX IF NOT EXISTS idx_scanner_outbox_due_cloud
    ON scanner_telegram_outbox(next_attempt_at, id) WHERE status IN ('pending','retry');
