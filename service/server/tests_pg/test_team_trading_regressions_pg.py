"""The same trading audit boundaries in isolated PostgreSQL test_* schemas."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import test_team_trading_regressions as cases


@pytest.mark.usefixtures('pg')
class TestTeamTradingRegressionsPostgres(cases.TestTeamTradingRegressions):
    pass


@pytest.mark.usefixtures('pg')
class TestTeamLegacyCloseRegressionsPostgres(cases.TestTeamLegacyCloseRegressions):
    pass
