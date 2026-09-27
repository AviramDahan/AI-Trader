-- Sandbox schema only: intentionally NOT registered with production migrations.
CREATE TABLE IF NOT EXISTS ne_events (
 event_id TEXT PRIMARY KEY, body_json TEXT NOT NULL, evidence_version TEXT NOT NULL,
 status TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ne_sources (
 source_key TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES ne_events(event_id),
 provider_id TEXT NOT NULL, content_hash TEXT NOT NULL, body_json TEXT NOT NULL,
 collected_at TEXT NOT NULL, source_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 UNIQUE(provider_id,source_key)
);
CREATE TABLE IF NOT EXISTS ne_anchors (anchor TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES ne_events(event_id));
CREATE TABLE IF NOT EXISTS ne_versions (
 event_id TEXT NOT NULL REFERENCES ne_events(event_id), version TEXT NOT NULL,
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(event_id,version)
);
CREATE TABLE IF NOT EXISTS ne_analysis (
 event_id TEXT NOT NULL REFERENCES ne_events(event_id), version TEXT NOT NULL,
 status TEXT NOT NULL, result_json TEXT, error TEXT, started_at TEXT NOT NULL,
 finished_at TEXT, latency REAL, owner TEXT NOT NULL,
 PRIMARY KEY(event_id,version)
);
CREATE TABLE IF NOT EXISTS ne_delivery (
 event_id TEXT NOT NULL REFERENCES ne_events(event_id), version TEXT NOT NULL,
 topic TEXT NOT NULL, tickers_json TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(event_id,version,topic)
);
CREATE TABLE IF NOT EXISTS ne_provider_state (provider_id TEXT PRIMARY KEY, state_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ne_metrics (
 metric_id TEXT PRIMARY KEY, event_id TEXT, provider_id TEXT, stage TEXT NOT NULL,
 result TEXT NOT NULL, at TEXT NOT NULL, data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ne_evidence_cache (cache_key TEXT PRIMARY KEY, body_json TEXT NOT NULL, collected_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ne_quarantine (
 source_key TEXT PRIMARY KEY, body_json TEXT NOT NULL, reason TEXT NOT NULL,
 candidate_event_ids_json TEXT NOT NULL, collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ne_sources_event ON ne_sources(event_id);
CREATE INDEX IF NOT EXISTS ne_metrics_event ON ne_metrics(event_id,stage);
CREATE INDEX IF NOT EXISTS ne_events_queue ON ne_events(status,created_at);
