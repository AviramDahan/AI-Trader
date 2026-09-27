-- Additive news-only state. Original scanner inputs and trading tables are unchanged.
CREATE TABLE IF NOT EXISTS news_evidence (
    cache_key TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_published_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    content_version TEXT NOT NULL,
    raw_source_text TEXT NOT NULL,
    selected_excerpt TEXT NOT NULL,
    issuer_cik TEXT NOT NULL,
    ticker TEXT NOT NULL,
    accession TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_evidence_attempts (
    cache_key TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    http_status INTEGER,
    next_attempt_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_review_cache (
    cache_key TEXT PRIMARY KEY,
    content_version TEXT NOT NULL,
    result_json TEXT,
    terminal_error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_publication_audit (
    news_id INTEGER PRIMARY KEY,
    content_version TEXT NOT NULL,
    evidence_key TEXT,
    reasons_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_ai_call_links (
    call_id TEXT PRIMARY KEY,
    news_id INTEGER NOT NULL,
    content_version TEXT NOT NULL,
    stage TEXT NOT NULL,
    source_excerpt_hash TEXT NOT NULL,
    source_excerpt_chars INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_ai_links_item ON news_ai_call_links(news_id,content_version);
CREATE TABLE IF NOT EXISTS news_evidence_observations (
    news_id INTEGER NOT NULL,
    content_version TEXT NOT NULL,
    reason TEXT NOT NULL,
    eligible INTEGER NOT NULL,
    elapsed_seconds REAL NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    PRIMARY KEY(news_id,content_version)
);
CREATE TABLE IF NOT EXISTS news_quality_checks (
    news_id INTEGER NOT NULL,
    content_version TEXT NOT NULL,
    stage TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY(news_id,content_version,stage)
);
CREATE INDEX IF NOT EXISTS idx_evidence_observed_at ON news_evidence_observations(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_evidence_quality_at ON news_quality_checks(checked_at);
