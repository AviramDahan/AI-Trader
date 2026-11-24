"""Editorial decisions use original source headlines, without model calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_only_editorial import watchlist_parts
from news_watchlist_editorial import decision


def classify(title, ticker='NVDA', company='NVIDIA Corporation'):
    return decision({'title': title}, ticker, company)


@pytest.mark.parametrize(('left', 'right'), [
    ('Micron raises FY2027 revenue outlook to $30 billion',
     'Micron lifts FY2027 sales guidance to $30bn'),
    ('U.S. Commerce Department imposes export restrictions on Nvidia H200 chips to China',
     'BIS imposes export curbs on Nvidia H200 chips to China'),
    ('Google agrees to buy Wiz for $32 billion', 'Google signs deal to acquire Wiz for $32bn'),
])
def test_equivalent_named_events(left, right):
    ticker, company = (
        ('MU', 'Micron Technology Inc.') if left.startswith('Micron') else
        ('GOOGL', 'Alphabet Inc.') if left.startswith('Google') else ('NVDA', 'NVIDIA Corporation'))
    reason, event = classify(left, ticker, company)
    assert reason is None and event
    assert classify(right, ticker, company) == (None, event)


@pytest.mark.parametrize(('first', 'update'), [
    ('Micron raises FY2027 revenue outlook to $30 billion',
     'Micron raises FY2027 revenue outlook to $35 billion'),
    ('Micron raises FY2027 revenue outlook to $30 billion',
     'Micron raises Q1 FY2027 revenue outlook to $30 billion'),
    ('U.S. imposes export restrictions on Nvidia H200 chips to China',
     'U.S. imposes export restrictions on Nvidia H20 chips to China'),
    ('U.S. imposes export restrictions on Nvidia H200 chips to China',
     'U.S. lifts export restrictions on Nvidia H200 chips to China'),
    ('U.S. imposes export restrictions on Nvidia H200 chips to China',
     'U.S. imposes export restrictions on Nvidia H200 chips to China, with a new exception'),
    ('Google agrees to buy Wiz for $32 billion', 'Google completes its acquisition of Wiz for $32 billion'),
])
def test_new_fact_is_distinct(first, update):
    ticker, company = (
        ('MU', 'Micron Technology Inc.') if first.startswith('Micron') else
        ('GOOGL', 'Alphabet Inc.') if first.startswith('Google') else ('NVDA', 'NVIDIA Corporation'))
    initial = classify(first, ticker, company)[1]
    reason, later = classify(update, ticker, company)
    assert initial and reason is None
    assert initial != later


def test_watchlist_related_customer_action_and_irrelevant_reactions():
    assert classify("Amazon shares jump after it orders Nvidia GPUs for new data centers")[0] is None
    assert classify("Qualcomm jumps as chip stocks rally on Nvidia news")[0] == 'watchlist_incidental_subject'
    assert classify("Asia chipmaking stocks soar tracking Nvidia rally")[0] == 'watchlist_incidental_subject'
    assert classify("Goldman says Huang return positive for Nvidia and broader AI ecosystem")[0] == 'watchlist_commentary'
    assert classify("Google signs a multiyear data-center supply contract", 'GOOGL', 'Alphabet Inc.')[0] is None
    assert classify("JUST IN: Jensen Huang admitted to additional affairs during talks with Nvidia board")[0] == 'watchlist_commentary'
    assert classify("U.S. may impose export restrictions on Nvidia H200 chips to China")[1] is None


def test_short_watchlist_message_preserves_extra_facts():
    assert watchlist_parts('MU', 'מיקרון העלתה תחזית',
                           'מיקרון העלתה תחזית\nהתחזית החדשה היא 30 מיליארד דולר.',
                           headline_only=False) == [
        'MU · מיקרון העלתה תחזית', 'התחזית החדשה היא 30 מיליארד דולר.']


def test_vetted_source_excerpt_preserves_new_terms():
    row = {'title': 'U.S. imposes export restrictions on Nvidia H200 chips to China'}
    baseline = decision(row, 'NVDA', 'NVIDIA Corporation')[1]
    row['source_facts_json'] = json.dumps({'source_excerpt': 'The new exception applies to confirmed preorders.'})
    assert baseline
    assert decision(row, 'NVDA', 'NVIDIA Corporation') == (None, None)


def test_company_investment_retained_when_first_clause_is_commentary():
    assert classify("Coherent is the real winner of the rally. Nvidia paid $2 billion for its stock")[0] is None
