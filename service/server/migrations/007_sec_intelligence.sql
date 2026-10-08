-- SEC decision evidence is separate from public news and paper accounting.
-- No existing signal, order, trade or news rows are rewritten.
CREATE TABLE IF NOT EXISTS si_universe_snapshots (
    id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, sources_json TEXT NOT NULL,
    members_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS si_filing_jobs (
    accession TEXT PRIMARY KEY, issuer_cik TEXT NOT NULL, tickers_json TEXT NOT NULL,
    form TEXT NOT NULL, accepted_at TEXT, published_at TEXT, first_seen_at TEXT NOT NULL,
    source_url TEXT NOT NULL, primary_document TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT, document_sha256 TEXT, parser_version TEXT,
    processed_at TEXT, superseded_by TEXT, error_code TEXT,
    evidence_json TEXT NOT NULL DEFAULT '{}', universe_snapshot_id TEXT NOT NULL,
    FOREIGN KEY(universe_snapshot_id) REFERENCES si_universe_snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_si_jobs_due ON si_filing_jobs(status,next_attempt_at,first_seen_at);
CREATE INDEX IF NOT EXISTS idx_si_jobs_issuer ON si_filing_jobs(issuer_cik,accepted_at);
CREATE TABLE IF NOT EXISTS si_transactions (
    event_id TEXT PRIMARY KEY, accession TEXT NOT NULL, issuer_cik TEXT NOT NULL,
    transaction_key TEXT NOT NULL, transaction_at TEXT, owners_json TEXT NOT NULL,
    category TEXT NOT NULL, body_json TEXT NOT NULL, effective_available_at TEXT NOT NULL,
    FOREIGN KEY(accession) REFERENCES si_filing_jobs(accession)
);
CREATE INDEX IF NOT EXISTS idx_si_transactions_issuer ON si_transactions(issuer_cik,transaction_at);
CREATE TABLE IF NOT EXISTS si_company_snapshots (
    id TEXT PRIMARY KEY, ticker TEXT NOT NULL, issuer_cik TEXT NOT NULL,
    universe_snapshot_id TEXT NOT NULL, effective_available_at TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    data_confidence REAL NOT NULL, adjustment REAL NOT NULL, status TEXT NOT NULL,
    evidence_json TEXT NOT NULL, evidence_ids_json TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    FOREIGN KEY(universe_snapshot_id) REFERENCES si_universe_snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_si_snapshot_lookup ON si_company_snapshots(ticker,effective_available_at DESC);
CREATE TABLE IF NOT EXISTS si_decisions (
    scan_id TEXT NOT NULL, ticker TEXT NOT NULL, mode TEXT NOT NULL,
    baseline_rank_score REAL NOT NULL, sec_adjustment REAL NOT NULL,
    insider_adjustment REAL NOT NULL DEFAULT 0, filing_adjustment REAL NOT NULL DEFAULT 0,
    enhanced_rank_score REAL NOT NULL, sec_snapshot_id TEXT,
    review_baseline_score REAL, review_enhanced_score REAL,
    evidence_ids_json TEXT NOT NULL, rejection_reason TEXT,
    shortlist_limit INTEGER NOT NULL,
    decided_at TEXT NOT NULL, PRIMARY KEY(scan_id,ticker,mode)
);
CREATE INDEX IF NOT EXISTS idx_si_decisions_time ON si_decisions(decided_at DESC);
CREATE TABLE IF NOT EXISTS si_checkpoints (
    issuer_cik TEXT PRIMARY KEY, last_checked_at TEXT, last_accession TEXT,
    etag TEXT, older_file_index INTEGER NOT NULL DEFAULT 0,
    catchup_active INTEGER NOT NULL DEFAULT 0, catchup_marker TEXT,
    retry_after TEXT, error_code TEXT
);
