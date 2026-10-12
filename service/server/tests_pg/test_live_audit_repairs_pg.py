"""Same application paths on isolated PostgreSQL, never live data/network."""
import pytest
import sys
from pathlib import Path
import database
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_live_audit_repairs as fixture
from test_signal_research import seed_journal


@pytest.mark.parametrize('code',['sec_document_too_large','submissions_issuer_mismatch'])
def test_pg_safe_discovery_error(pg,monkeypatch,code):
    fixture.test_discovery_retains_known_safe_error_not_raw_exception(database.get_db_connection,monkeypatch,code)


@pytest.mark.parametrize('name',['not-a-submissions-file.json','CIK0000000002-submissions-001.json'])
def test_pg_invalid_continuation_is_not_a_complete_checkpoint(pg,monkeypatch,name):
    fixture.test_invalid_continuation_cannot_be_skipped_or_completed(database.get_db_connection,monkeypatch,name)


def test_pg_incomplete_checkpoint_304_and_safe_retry(pg,monkeypatch):
    fixture.test_incomplete_sec_catchup_cannot_be_completed_by_not_modified(database.get_db_connection,monkeypatch)


def test_pg_unknown_error_and_rate_limit(pg,monkeypatch):
    fixture.test_sec_unknown_error_is_sanitized_http_retry_is_preserved(database.get_db_connection,monkeypatch)


def test_pg_unknown_date_is_not_completed_history(pg,monkeypatch):
    fixture.test_unknown_acceptance_date_does_not_fake_retention_boundary(database.get_db_connection,monkeypatch)


def test_pg_truthful_research_projection(pg):
    with database.get_db_connection() as c:
        c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
        seed_journal(c)
    fixture.test_research_reports_missing_sec_evidence_and_safe_ai_reason(pg)
