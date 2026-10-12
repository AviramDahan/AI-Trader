"""Full application rationale repair on isolated PostgreSQL; all IO mocked."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_signal_inputs import clock
from test_entry_rationale import test_actual_scanner_invalid_hold_never_creates_order as exercise

@pytest.mark.parametrize('repair_action',['HOLD','BUY'])
def test_pg_entry_rationale_preserves_decision_and_no_orders(pg,clock,monkeypatch,repair_action):
    exercise(pg,clock,monkeypatch,repair_action)
