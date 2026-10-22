"""Public selection/outbox invariants on the existing isolated test_* PG schema."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_sec_public_editorial import JOB, seeded_public_process


def test_pg_latest_public_period_keeps_original_evidence_and_dedupe(pg, monkeypatch):
    rows = seeded_public_process(monkeypatch)
    assert len(rows) == 1 and rows[0]["dedupe_key"] == "sec-intelligence:" + JOB["accession"]
    assert rows[0]["status"] == "pending"
    assert "20.0%" in rows[0]["message"] and "300.0%" not in rows[0]["message"]
    assert "2026-09-30" in rows[0]["message"] and "2025-09-30" in rows[0]["message"]
    assert "• מזומן:" not in rows[0]["message"]


@pytest.mark.parametrize("kind", ["uncomparable_latest", "stale_filing"])
def test_pg_silent_publication_retains_processed_filing(pg, monkeypatch, kind):
    assert seeded_public_process(monkeypatch, period_conflict=kind == "uncomparable_latest",
                                 stale=kind == "stale_filing") == []
