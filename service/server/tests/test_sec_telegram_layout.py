"""Synthetic phone-readable SEC copy; no actual issuer notice is a fixture."""
import copy
import re
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sec_intelligence as sec
from telegram_presentation import telegram_text,utf16_length
from test_sec_public_editorial import JOB,comparison,isolated,seeded_public_process


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    monkeypatch.setattr(sec,'fetch',lambda *_a,**_k:pytest.fail('No SEC request'))
    monkeypatch.setattr(requests.sessions.Session,'request',lambda *_a,**_k:pytest.fail('No network'))
    monkeypatch.setenv('SEC_INTELLIGENCE_MATERIAL_CHANGE_PCT','10')
    monkeypatch.setenv('SEC_INTELLIGENCE_MATERIAL_MARGIN_PP','2')


def facts():
    return [comparison('revenue',year=2025,value=1_260_000_000,previous=1_000_000_000,start_month='01-01',end_month='12-31'),
            comparison('operating_income',year=2025,value=115_000_000,previous=100_000_000,start_month='01-01',end_month='12-31'),
            comparison('operating_cash_flow',year=2025,value=900_000_000,previous=750_000_000,start_month='01-01',end_month='12-31')]


def render(values):
    return sec._public_financial_text(JOB,{'kind':'financial','comparisons':values})


def clean(value):
    return re.sub('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]','',value)


def test_dense_metric_sentences_become_separate_phone_blocks():
    text=render(facts())
    assert [line for line in text.splitlines() if line.startswith('• ')]==[
        '• הכנסות','• רווח תפעולי','• תזרים מפעילות שוטפת']
    assert 'נוכחי: 1,260,000,000 USD' in text.splitlines()
    assert 'קודם: 1,000,000,000 USD' in text.splitlines()
    assert 'תקופת הדיווח: 2025-01-01 עד 2025-12-31' in text.splitlines()
    assert 'תקופת ההשוואה: 2024-01-01 עד 2024-12-31' in text.splitlines()
    assert '\n\n• רווח תפעולי\n' in text
    assert max(map(len,text.splitlines()))<=130


def test_rounded_change_is_explicit_not_an_exact_amount_or_new_threshold():
    text=render([comparison(value=123_456,previous=100_000)])
    assert 'נוכחי: 123,456 USD' in text
    assert 'שינוי: עלייה של כ־23.5%' in text
    assert '23.456%' not in text
    assert render([comparison(value=105_000,previous=100_000)]) is None


def test_mixed_periods_are_repeated_per_metric_not_assumed_shared():
    annual=facts()[0]
    quarter=comparison('operating_income',value=200,previous=100)
    text=render([annual,quarter])
    revenue,operating=text.split('\n\n')[:2]
    assert '2025-01-01 עד 2025-12-31' in revenue
    assert '2026-07-01 עד 2026-09-30' in operating
    assert not any(label in text for label in ('רבעון','Q1','Q2','Q3','Q4','FY'))


def test_balance_dates_and_margin_units_are_not_presented_as_flows_or_currency():
    cash=render([comparison('operating_cash_flow',value=200,previous=100),
                 comparison('cash',value=300,previous=100)])
    block=next(block for block in cash.split('\n\n') if block.startswith('• מזומן'))
    assert 'ליום 2026-09-30' in block and 'בהשוואה ליום 2025-09-30' in block
    assert 'תקופת הדיווח:' not in block
    margin=render([comparison('operating_margin',value=5,previous=-2)])
    assert 'נוכחי: 5%' in margin and 'קודם: -2%' in margin
    assert 'כ־7.0 נקודות אחוז' in margin and 'USD' not in margin


def test_negative_reported_result_keeps_its_sign_and_zero_base_stays_silent():
    text=render([comparison('operating_income',value=-50,previous=100)])
    assert 'נוכחי: -50 USD' in text and 'קודם: 100 USD' in text
    assert 'שינוי: ירידה של כ־150.0%' in text
    assert render([comparison('operating_income',value=100,previous=0)]) is None


def test_real_bidi_wire_preserves_every_selected_fact_without_clipping():
    values=facts();frozen=copy.deepcopy(values)
    body=render(values)
    wire=telegram_text('📑 דיווח SEC מהותי\n\nחברה: Synthetic Example\nסימול: SYN\n\n'+body+
                       '\n\nנקלט ב־SEC: 20/10/2026 15:00 (שעון ישראל)\n\nקהילת בדיקה: https://example.invalid/')
    assert values==frozen and clean(wire).count('• ')==3
    assert all(str(part) in clean(wire) for part in ('1,260,000,000 USD','1,000,000,000 USD',
        '115,000,000 USD','100,000,000 USD','900,000,000 USD','750,000,000 USD'))
    assert not any(char in wire for char in ('…','→','←','↔'))
    assert wire.count('\u2066')==wire.count('\u2069')
    assert utf16_length(wire)<=4096 and telegram_text(wire)==wire


def test_actual_enqueue_labels_acceptance_not_delivery_clock(isolated,monkeypatch):
    rows=seeded_public_process(monkeypatch)
    assert len(rows)==1 and rows[0]['status']=='pending'
    assert 'נקלט ב־SEC:' in rows[0]['message'] and 'דווח:' not in rows[0]['message']
    assert 'נשלח:' not in rows[0]['message']
    assert '\nבפועל:' in rows[0]['message']
