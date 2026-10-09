"""Read-only schema-7 validation for the SEC-safe rollback bridge.

This release does not produce SEC intelligence or run migration 007. It can
start against a completed migration so existing paper roles keep operating.
"""

REQUIRED_COLUMNS = {
    'si_universe_snapshots': {'id', 'observed_at', 'sources_json', 'members_json'},
    'si_filing_jobs': {'accession', 'issuer_cik', 'tickers_json', 'form', 'accepted_at',
        'published_at', 'first_seen_at', 'source_url', 'primary_document', 'status',
        'attempts', 'next_attempt_at', 'document_sha256', 'parser_version', 'processed_at',
        'superseded_by', 'error_code', 'evidence_json', 'universe_snapshot_id'},
    'si_transactions': {'event_id', 'accession', 'issuer_cik', 'transaction_key',
        'transaction_at', 'owners_json', 'category', 'body_json', 'effective_available_at'},
    'si_company_snapshots': {'id', 'ticker', 'issuer_cik', 'universe_snapshot_id',
        'effective_available_at', 'created_at', 'expires_at', 'data_confidence',
        'adjustment', 'status', 'evidence_json', 'evidence_ids_json', 'policy_version'},
    'si_decisions': {'scan_id', 'ticker', 'mode', 'baseline_rank_score', 'sec_adjustment',
        'insider_adjustment', 'filing_adjustment', 'enhanced_rank_score', 'sec_snapshot_id',
        'review_baseline_score', 'review_enhanced_score', 'evidence_ids_json',
        'rejection_reason', 'shortlist_limit', 'decided_at'},
    'si_checkpoints': {'issuer_cik', 'last_checked_at', 'last_accession', 'etag',
        'older_file_index', 'catchup_active', 'catchup_marker', 'retry_after', 'error_code'},
}
REQUIRED_INDEXES = {'idx_si_jobs_due', 'idx_si_jobs_issuer', 'idx_si_transactions_issuer',
                    'idx_si_snapshot_lookup', 'idx_si_decisions_time', 'idx_si_decisions_snapshot',
                    'idx_si_snapshot_evidence_ids', 'idx_si_snapshot_facts'}
# PostgreSQL-only dependency lookups for bounded archive-first maintenance.
# The bridge never executes this DDL; it only verifies a completed schema.
RETENTION_INDEX_SQL = (
    'CREATE INDEX IF NOT EXISTS idx_si_decisions_snapshot ON si_decisions(sec_snapshot_id)',
    'CREATE INDEX IF NOT EXISTS idx_si_snapshot_evidence_ids ON si_company_snapshots USING GIN ((evidence_ids_json::jsonb))',
    'CREATE INDEX IF NOT EXISTS idx_si_snapshot_facts ON si_company_snapshots USING GIN ((evidence_json::jsonb))',
)
REQUIRED_CONSTRAINTS = {
    ('si_universe_snapshots', 'p', ('id',), ''),
    ('si_filing_jobs', 'p', ('accession',), ''),
    ('si_filing_jobs', 'f', ('universe_snapshot_id',), 'si_universe_snapshots'),
    ('si_transactions', 'p', ('event_id',), ''),
    ('si_transactions', 'f', ('accession',), 'si_filing_jobs'),
    ('si_company_snapshots', 'p', ('id',), ''),
    ('si_company_snapshots', 'f', ('universe_snapshot_id',), 'si_universe_snapshots'),
    ('si_decisions', 'p', ('scan_id', 'ticker', 'mode'), ''),
    ('si_checkpoints', 'p', ('issuer_cik',), ''),
}


def assert_sec_schema7(conn):
    versions = [int(row['version']) for row in conn.execute(
        'SELECT version FROM schema_migrations ORDER BY version').fetchall()]
    if versions != list(range(1, 8)):
        raise RuntimeError('sec_schema7_migration_history_incomplete')
    rows = conn.execute("""SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name LIKE 'si_%'""").fetchall()
    columns = {}
    for row in rows:
        columns.setdefault(row['table_name'], set()).add(row['column_name'])
    if any(not required <= columns.get(table, set()) for table, required in REQUIRED_COLUMNS.items()):
        raise RuntimeError('sec_schema7_structure_incomplete')
    indexes = {row['indexname'] for row in conn.execute("""SELECT indexname FROM pg_indexes
        WHERE schemaname=current_schema() AND tablename LIKE 'si_%'""").fetchall()}
    if not REQUIRED_INDEXES <= indexes:
        raise RuntimeError('sec_schema7_indexes_incomplete')
    constraints = conn.execute("""SELECT rel.relname AS table_name, c.contype AS constraint_type,
            array_agg(att.attname ORDER BY key.ordinality) AS column_names,
            COALESCE(refrel.relname, '') AS referenced_table
        FROM pg_constraint c
        JOIN pg_class rel ON rel.oid=c.conrelid
        JOIN pg_namespace ns ON ns.oid=rel.relnamespace
        LEFT JOIN pg_class refrel ON refrel.oid=c.confrelid
        JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS key(attnum,ordinality) ON true
        JOIN pg_attribute att ON att.attrelid=rel.oid AND att.attnum=key.attnum
        WHERE ns.nspname=current_schema() AND rel.relname LIKE 'si_%' AND c.contype IN ('p','f')
        GROUP BY rel.relname,c.contype,c.oid,refrel.relname""").fetchall()
    actual = {(row['table_name'], row['constraint_type'], tuple(row['column_names']),
               row['referenced_table']) for row in constraints}
    if not REQUIRED_CONSTRAINTS <= actual:
        raise RuntimeError('sec_schema7_constraints_incomplete')
