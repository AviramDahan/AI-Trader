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
                    'idx_si_snapshot_lookup', 'idx_si_decisions_time'}


def assert_sec_schema7(conn):
    versions = [int(row['version']) for row in conn.execute(
        'SELECT version FROM schema_migrations ORDER BY version').fetchall()]
    if not versions or versions[-1] != 7 or 6 not in versions or versions.count(7) != 1:
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
