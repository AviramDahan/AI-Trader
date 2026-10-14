"""Identical projection regressions on genuine disposable PostgreSQL schemas."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
import test_team_admin_monitor_regressions as cases
from datetime import timedelta


@pytest.mark.usefixtures('pg')
class TestTeamAdminProjectionPostgres(cases.TeamAdminProjectionTests):
    def test_real_missing_role_lease_is_not_downgraded_by_bar_freshness(self):
        self.pending()
        self.cursor('IFF', cases.NOW-timedelta(days=2))
        node = self.snapshot(roles=(11, 13))['monitor']
        assert node['lease_holders'] == 0
        assert (node['state'], node['reason']) == ('failed', 'lease_missing')
