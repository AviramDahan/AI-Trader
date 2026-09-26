import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from admin_messages import timestamped
from unittest.mock import MagicMock, patch
import ai_operations


def test_israel_summer_and_winter():
    assert timestamped('alert','2026-09-27T11:35:00Z').endswith('27/09/2026 14:35 (Israel)')
    assert timestamped('alert','2026-12-27T11:35:00Z').endswith('27/12/2026 13:35 (Israel)')


def test_retry_preserves_event_time_and_single_footer():
    first=timestamped('alert','2026-09-27T11:35:00Z')
    assert timestamped(first,'2026-09-27T11:35:00Z')==first


def test_enqueue_persists_same_creation_time():
    conn=MagicMock()
    with patch('database.get_db_connection',return_value=conn):
        ai_operations.enqueue('test','alert')
    params=conn.__enter__.return_value.execute.call_args.args[1]
    assert params[1]==timestamped('alert',params[2])
