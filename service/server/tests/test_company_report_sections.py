"""Approved compact report presentation, isolated synthetic accounting values."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sec_intelligence as sec
from test_sec_public_editorial import JOB, comparison, isolated, seeded_public_process


def render(facts):
    original = sec._public_financial_text(JOB, {'comparisons': facts})
    return sec._company_report_text(original)


def test_expectations_and_results_are_separate_and_prior_is_not_consensus():
    body = render([comparison(value=120_000_000, previous=100_000_000)])
    expected = body.split('🔮 ציפיות האנליסטים\n', 1)[1].split('📋 התוצאות בפועל', 1)[0]
    assert 'לא זמין' in expected
    assert '100' not in expected and '120' not in expected
    actual = body.split('📋 התוצאות בפועל\n', 1)[1]
    assert '120 מיליון דולר' in actual and '100 מיליון דולר' in actual
    assert 'מעל הצפי' not in body and 'מתחת לצפי' not in body
    assert 'רווח למניה' not in body  # The source supplied no EPS.


@pytest.mark.parametrize('value,expected', [
    (120_000_000, '120 מיליון דולר'), (1_200_000_000, '1.2 מיליארד דולר'),
    (-75_000_000, '-75 מיליון דולר'), (250_000, '250 אלף דולר'),
    (0, '0 דולר'), (1.2, '1.2 דולר'),
    (1_350_000_001.25, 'כ־1.35 מיליארד דולר'),
    (999_999_999, 'כ־1 מיליארד דולר'), (0.0004, '0.0004 דולר'),
    (-0.0, '0 דולר'), (999_999, 'כ־1 מיליון דולר'),
])
def test_compact_amounts_have_explicit_units_and_honest_rounding(value, expected):
    assert sec._public_compact_usd(value) == expected


def test_margin_keeps_percentage_points_not_currency_or_earnings_surprise():
    body = render([comparison('operating_margin', value=-2.25, previous=3)])
    assert '-2.25%' in body and 'נקודות אחוז' in body
    assert 'דולר' not in body and 'מעל הצפי' not in body


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_amount_never_becomes_public_zero(value):
    with pytest.raises(ValueError, match='public_nonfinite_amount'):
        sec._public_compact_usd(value)


def test_actual_outbox_uses_approved_sections_without_replay(isolated, monkeypatch):
    rows = seeded_public_process(monkeypatch)
    assert len(rows) == 1 and rows[0]['status'] == 'pending'
    body = rows[0]['message']
    assert body.index('🔮 ציפיות האנליסטים') < body.index('📋 התוצאות בפועל')
    assert 'לא זמין' in body and '120 דולר' in body
    assert 'נקלט ב־SEC:' in body and 'תיקון לדיווח קודם' in body
