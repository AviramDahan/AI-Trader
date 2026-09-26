"""Reuse all original news scheduling/deduplication tests with real PostgreSQL."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_news_pipeline as news_tests


@pytest.mark.usefixtures('pg')
class TestNewsOnPostgres(news_tests.NewsPipelineIntegrationTests):
    pass
