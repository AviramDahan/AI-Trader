"""Same full application cases, isolated PostgreSQL test_* schema; no network."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_paper_execution_alerts as cases


@pytest.mark.usefixtures('pg')
class TestPaperExecutionAlertsPostgres(cases.PaperExecutionAlertTests):
    pass
