-- Additive news-only cutover metadata. Trading rows and Phase 1 remain intact.
CREATE TABLE ne_control (
 id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode IN ('phase1','canonical')),
 not_before TEXT NOT NULL DEFAULT '', epoch INTEGER NOT NULL DEFAULT 0,
 changed_at TEXT NOT NULL, reason TEXT NOT NULL
);
INSERT INTO ne_control(id,mode,changed_at,reason) VALUES(1,'phase1',CURRENT_TIMESTAMP::text,'migration_disabled');
CREATE TABLE ne_projection (
 event_id TEXT PRIMARY KEY REFERENCES ne_events(event_id),
 news_id INTEGER UNIQUE NOT NULL REFERENCES scanner_news(id)
);
CREATE TABLE ne_outbox (
 dedupe_key TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES ne_events(event_id),
 version TEXT NOT NULL, topic TEXT NOT NULL, epoch INTEGER NOT NULL,
 UNIQUE(event_id,version,topic)
);
CREATE TABLE ne_cutover_receipts (
 source_url TEXT NOT NULL, topic TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(source_url,topic)
);
CREATE TABLE ne_ai_call_links (
 call_id TEXT PRIMARY KEY REFERENCES ai_call_usage(call_id),
 event_id TEXT NOT NULL REFERENCES ne_events(event_id), version TEXT NOT NULL,
 stage TEXT NOT NULL
);
CREATE INDEX ne_ai_event ON ne_ai_call_links(event_id,version);
