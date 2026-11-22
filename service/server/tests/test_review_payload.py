"""Synthetic evidence conservation; no AI, providers or trading writes."""
import copy
import json

import pytest

from review_payload import compact, expand


def fixture():
    rows = [dict(title='Synthetic results', publisher='Issuer', published_at='2026-11-20T14:00:00Z',
                 relevance=.8, source_excerpt='Explicit full source facts retained. ' * 40,
                 url='https://example.invalid/source', provenance=[{'source': 'synthetic'}])]
    zones = [dict(low=98., high=99., touches=3, pivots=[
        dict(price=98.5, date='2026-11-01', kind='low', confirmed_at='2026-11-03T21:00:00Z')])]
    return dict(candidate=dict(ticker='SYN', news=rows, price_zones=[{
        **z, 'pivots': [{k: v for k, v in p.items() if k != 'confirmed_at'} for p in z['pivots']]}
        for z in zones]), recent_news=[{k: r[k] for k in
            ('title', 'publisher', 'published_at', 'relevance')} for r in rows],
        validated_target_plan=dict(zones=zones, entry=100., stop=97., targets=[106.], rr=[2.]),
        review_evidence_context={'entry_quote': {'price': 100., 'fresh': True}})


def test_exact_round_trip_and_no_mutation():
    original = fixture()
    before = copy.deepcopy(original)
    projected, moves = compact(original)
    assert moves == ['news', 'price_zones']
    assert expand(projected, moves) == original == before
    assert projected['recent_news'] == original['candidate']['news']
    assert projected['validated_target_plan'] == original['validated_target_plan']
    assert projected['review_evidence_context'] == original['review_evidence_context']
    assert len(json.dumps(projected)) < len(json.dumps(original))


@pytest.mark.parametrize('field,value', [('title', 'Different'), ('publisher', 'Different'),
                                     ('published_at', '2026-11-19'), ('relevance', .2)])
def test_different_news_copy_is_not_discarded(field, value):
    original = fixture()
    original['recent_news'][0][field] = value
    projected, moves = compact(original)
    assert 'news' not in moves
    assert projected['candidate']['news'] == original['candidate']['news']
    assert expand(projected, moves) == original


@pytest.mark.parametrize('mutation', ['price', 'time', 'order', 'touches'])
def test_different_zone_evidence_is_not_discarded(mutation):
    original = fixture()
    zone = original['candidate']['price_zones'][0]
    if mutation == 'price':
        zone['low'] = 97.
    elif mutation == 'time':
        zone['pivots'][0]['date'] = '2026-11-02'
    elif mutation == 'order':
        original['candidate']['price_zones'].append(copy.deepcopy(zone))
    else:
        zone['touches'] = 4
    projected, moves = compact(original)
    assert 'price_zones' not in moves
    assert expand(projected, moves) == original


def test_idempotent_and_incomplete_evidence_is_preserved():
    original = fixture()
    first, moves = compact(original)
    assert compact(first) == (first, [])
    for key in ('news', 'price_zones'):
        broken = copy.deepcopy(original)
        broken['candidate'][key] = None
        projected, changes = compact(broken)
        assert key not in changes
        assert expand(projected, changes) == broken


def test_actual_ai_review_sends_each_source_once_without_losing_facts(monkeypatch):
    from unittest.mock import Mock
    import stock_scanner as scanner
    from test_review_evidence import candidate, held
    monkeypatch.setenv('STOCK_SCANNER_PRICE_NEWS_CONTEXT_ENABLED', 'false')
    original = fixture()
    row = candidate()
    row.update(original['candidate'], validated_target_plan=original['validated_target_plan'])
    before = copy.deepcopy(row)
    model = Mock(return_value=held())
    monkeypatch.setattr(scanner.final_ai, 'review', model)
    scanner.ai_review(row, row['news'], {})
    messages = model.call_args.args[0]
    sent = json.loads(messages[1]['content'])
    assert 'news' not in sent['candidate']
    assert 'price_zones' not in sent['candidate']
    assert sent['recent_news'] == row['news']
    assert sent['validated_target_plan'] == row['validated_target_plan']
    assert row == before
    assert model.call_count == 1
