import importlib.util
import os
from pathlib import Path
from unittest.mock import patch


def test_local_telegram_destination_overrides_inherited_windows_destination():
    path = Path(__file__).resolve().parents[3] / "scripts/supervise_ai_trader.py"
    spec = importlib.util.spec_from_file_location("telegram_supervisor_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "wrong", "TELEGRAM_BOT_TOKEN": "old-test-token"}), \
         patch.object(module, "dotenv_values", return_value={"TELEGRAM_CHAT_ID": "intended", "TELEGRAM_BOT_TOKEN": "local-test-token"}):
        env = module.child_environment()
    assert env["TELEGRAM_CHAT_ID"] == "intended"
    assert env["TELEGRAM_BOT_TOKEN"] == "local-test-token"


def test_missing_local_settings_preserve_environment_only_deployments():
    path = Path(__file__).resolve().parents[3] / "scripts/supervise_ai_trader.py"
    spec = importlib.util.spec_from_file_location("telegram_supervisor_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "configured"}), patch.object(module, "dotenv_values", return_value={}):
        assert module.child_environment()["TELEGRAM_CHAT_ID"] == "configured"
