CREATE TABLE ai_call_usage (
 call_id TEXT PRIMARY KEY, task TEXT NOT NULL, parent_task TEXT NOT NULL, model TEXT NOT NULL,
 input_tokens BIGINT, output_tokens BIGINT, reasoning_tokens BIGINT, actual_cost DOUBLE PRECISION,
 latency DOUBLE PRECISION NOT NULL, timestamp TEXT NOT NULL, success INTEGER NOT NULL,
 failure TEXT, generation_id TEXT
);
CREATE INDEX ai_call_usage_month_task ON ai_call_usage(timestamp,task);
CREATE TABLE admin_alerts (
 dedupe_key TEXT PRIMARY KEY, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, next_at DOUBLE PRECISION NOT NULL DEFAULT 0,
 message_id BIGINT, created_at TEXT NOT NULL
);
