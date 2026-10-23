"""Synthetic exact-token safety and retained-coverage regressions; no I/O."""
from dataclasses import replace

import pytest

from news_events.model import IdentityResolver, Source


UNIVERSE = {'ABCD': {'company': 'Example Devices Incorporated', 'cik': '12345'}}


def source(title):
    return Source('investing', 'synthetic', 'https://example.invalid/article',
                  'Synthetic publisher', '2026-10-23T07:00:00Z',
                  '2026-10-23T07:01:00Z', title, '', tickers=('ABCD',),
                  event_type='earnings', rights='approved')


@pytest.mark.parametrize('title', [
    '$ABCDjunk reports earnings',
    'NYSE:ABCDjunk reports earnings',
    'NASDAQ:ABCDjunk reports earnings',
    '$ABCD_legacy reports earnings',
    '$ABCDé reports earnings',
])
def test_explicit_company_token_must_not_match_a_longer_identifier(title):
    assert IdentityResolver(UNIVERSE).resolve(source(title)) == []


@pytest.mark.parametrize('title', [
    '$ABCD reports earnings',
    'NYSE:ABCD reports earnings',
    'NASDAQ: ABCD reports earnings',
    'The issuer (NYSE:ABCD) reports earnings',
    '$ABCD. The issuer reports earnings',
])
def test_exact_explicit_company_tokens_keep_existing_positive_authority(title):
    actual = IdentityResolver(UNIVERSE).resolve(source(title))
    assert [(x['ticker'], x['basis']) for x in actual] == [('ABCD', 'exchange_ticker')]


def test_related_ticker_is_not_verified_identity_and_cik_stays_independent():
    candidate = source('ABCD reports earnings')
    assert IdentityResolver(UNIVERSE).resolve(candidate) == []
    assert IdentityResolver(UNIVERSE).resolve(replace(candidate, cik='0000012345'))[0]['basis'] == 'cik'


def test_yahoo_subject_and_provider_ticker_rules_are_not_relaxed():
    candidate = replace(source('Generic sector roundup mentions ABCD'),
                        provider_id='yahoo_priority',
                        raw_metadata={'provider_tickers': ['ABCD']})
    assert IdentityResolver(UNIVERSE).resolve(candidate) == []
