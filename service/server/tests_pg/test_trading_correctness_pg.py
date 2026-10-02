"""Identical regression scenarios on an isolated PostgreSQL test_* schema."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_trading_correctness as cases

@pytest.mark.usefixtures('pg')
class TestTradingCorrectnessPostgres(cases.TradingCorrectnessTests):
    pass
