import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import test_news_evidence


@pytest.mark.usefixtures('pg')
class TestNewsEvidenceOnPostgres(test_news_evidence.NewsEvidenceTests):
    pass
