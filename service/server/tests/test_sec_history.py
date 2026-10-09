import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sec_history as history


def test_history_controls_cannot_shorten_decision_context(monkeypatch):
    assert history.history_days() == 400
    for invalid in ('90', '399', '731', 'bad'):
        monkeypatch.setenv('SEC_INTELLIGENCE_HISTORY_DAYS', invalid)
        with pytest.raises(ValueError):
            history.history_days()


def test_companion_paths_cannot_escape_repository(tmp_path):
    for invalid in ('../private.key', 'sec/chunks/../../private.age', 'hourly/data.age', 'sec/chunks/not-a-hash.age'):
        with pytest.raises(ValueError, match='unsafe_sec_archive_path'):
            history.location(tmp_path, invalid)
    assert history.location(tmp_path, 'sec/chunks/' + 'a' * 64 + '.age').is_relative_to(tmp_path)


def test_schema6_backup_is_explicitly_not_sec_coverage(tmp_path):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {'version': 6}
    conn.__enter__.return_value = conn
    with patch('psycopg.connect', return_value=conn):
        assert history.export_archive('isolated', tmp_path, 'synthetic') is None
    assert not (tmp_path / 'sec').exists()
    assert any('READ ONLY' in str(call) for call in conn.execute.call_args_list)


def test_unknown_archive_and_running_workers_fail_closed(tmp_path):
    with pytest.raises(ValueError, match='stopped_workers'):
        history.restore_archive(tmp_path, 'unused', 'unused', 'isolated')
    with pytest.raises(ValueError, match='columns_invalid'):
        history.row_valid('scanner_accounts', {'cash': 1})
