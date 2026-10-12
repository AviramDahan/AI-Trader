"""Input snapshot before AI, real PostgreSQL admission/fills/restart; mocked IO."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_review_evidence import clock
from test_review_evidence import test_actual_scanner_persists_input_before_ai_and_preserves_lifecycle as exercise

@pytest.mark.parametrize('action',['BUY','HOLD','ERROR'])
def test_pg_review_evidence_through_actual_application(pg,clock,monkeypatch,action):
    exercise(pg,clock,monkeypatch,action)
