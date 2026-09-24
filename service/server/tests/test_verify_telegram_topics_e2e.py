import importlib.util
import os
from pathlib import Path
from unittest.mock import Mock, call, patch


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_telegram_topics_e2e.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("telegram_topics_e2e_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {}, clear=False), patch("dotenv.dotenv_values", return_value={}):
        spec.loader.exec_module(module)
    return module


def test_status_refresh_honors_full_retry_after_in_bounded_chunks():
    module = _load_script()
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [
        {"last_error": "Too Many Requests: retry after 121"},
    ]
    with patch.object(module, "refresh_telegram_status_cards", side_effect=[
        {"signals_status": "failed"}, {"signals_status": "updated"},
    ]), patch.object(module.database, "get_db_connection", return_value=connection), \
            patch.object(module.time, "sleep") as sleeper:
        result = module._refresh_status_with_retry()
    assert result == {"signals_status": "updated"}
    assert sleeper.call_args_list == [call(60), call(60), call(2)]
    connection.close.assert_called_once_with()
