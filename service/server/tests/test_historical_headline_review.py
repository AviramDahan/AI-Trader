"""Offline regression checks for the bounded source-only historical repair."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    'historical_review', Path(__file__).resolve().parents[3] / 'scripts/review_historical_headlines.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_sec_form_with_spaces_and_hyphen_preserves_issuer():
    for form in ('8-K', '11-K', 'PRE 14A', 'DEF 14A', '4'):
        result = review.sec_headline({'title': f'{form} - Example Inc (0000123456) (Filer)'})
        assert f'{form} — Example Inc.' in result
        assert 'לא נקבעה השפעה' in result
        assert '0000123456' not in result


def test_unknown_sec_title_is_not_invented():
    assert review.sec_headline({'title': 'Unknown official item'}) is None
