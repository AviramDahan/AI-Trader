import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import news_quality as quality
import news_pipeline


def draft():
    return dict(related=True,title_he='עדכון רשמי של החברה',summary_he='החברה פרסמה עדכון רשמי.',
                interpretation_he='ההשפעה האפשרית אינה ודאית.',sentiment='neutral',materiality='low',relevance=.8)


def review(**changes):
    return dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,duplicate_of=0,
                material_new_fact=False,explanation='Source supported',**changes)


def row():
    return dict(id=7,title='Company official update',published_at='2026-09-25T10:00:00Z',
                scope='market',thesis='BUY because of MACD and RSI',
                source_facts_json=json.dumps({'source_excerpt':'Official update only'}))


def test_durable_goods_does_not_become_appliances_or_previous_estimate():
    facts={'title':'US AUG DURABLES ORDERS UNCHANGED (CONSENSUS -0.4%)'}
    value=draft() | {'title_he':'הזמנות מכשירי חשמל עמידים ללא שינוי'}
    assert not quality.terminology_grounded(value,facts)
    value['title_he']='הזמנות מוצרים בני קיימא ללא שינוי (הערכה מקדימה)'
    assert not quality.terminology_grounded(value,facts)
    value['title_he']='הזמנות מוצרים בני קיימא ללא שינוי, לעומת תחזית האנליסטים'
    assert quality.terminology_grounded(value,facts)


def test_source_translation_cannot_see_thesis_or_previous_generated_text():
    value=row() | {'summary_he':'invented previous text'}
    with patch('news_quality.recent_events',return_value=[]), patch('scanner_engine._ollama_json',
            side_effect=[draft(),review(),{'thesis_effect':'unchanged'}]) as model:
        result=quality.analyze_one(value)
    assert result['quality_version']==2
    for call in model.call_args_list[:2]:
        assert 'MACD' not in json.dumps(call.args[1])
        assert 'invented previous' not in json.dumps(call.args[1])
    assert model.call_args_list[-1].args[1]['historical_thesis']==value['thesis']


def test_invalid_boolean_fails_closed():
    with pytest.raises(ValueError,match='boolean'):
        quality.validate_object(draft() | {'related':'false'},quality.ANALYSIS_SCHEMA)


def test_fast_market_uses_one_call_and_no_thesis(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_NEWS_FAST_MARKET','true')
    with patch('news_quality.recent_events',return_value=[]), patch('scanner_engine._ollama_json',
            return_value=draft() | {'needs_review':False}) as model:
        result=quality.analyze_one(row() | {'thesis':None})
    assert model.call_count==1
    assert result['analysis_seconds']>=0 and result['quality_version']==3
    assert 'MACD' not in json.dumps(model.call_args.args)
    assert model.call_args.args[1]['scope']=='market'
    assert 'related=true' in model.call_args.args[0]


@pytest.mark.parametrize('material_new_fact,expected',[(False,3),(True,0)])
def test_fast_semantic_dedup_preserves_material_updates(monkeypatch,material_new_fact,expected):
    monkeypatch.setenv('STOCK_SCANNER_NEWS_FAST_MARKET','true')
    with patch('news_quality.recent_events',return_value=[row() | {'id':3}]), patch('scanner_engine._ollama_json',
            side_effect=[draft() | {'needs_review':False},
                         {'duplicate_of':3,'material_new_fact':material_new_fact}]) as model:
        result=quality.analyze_one(row() | {'thesis':None})
    assert result['duplicate_of']==expected
    assert model.call_count==2


def test_fast_uncertainty_or_bad_numbers_use_strict_path(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_NEWS_FAST_MARKET','true')
    for bad in [draft() | {'needs_review':True}, draft() | {'needs_review':False,'title_he':'מחיר 999'}]:
        with patch('news_quality.recent_events',return_value=[]), patch('scanner_engine._ollama_json',return_value=bad), patch('news_quality.analyze_strict',return_value=draft()) as strict:
            quality.analyze_one(row() | {'thesis':None})
            strict.assert_called_once()


def test_fast_mode_does_not_change_position_analysis(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_NEWS_FAST_MARKET','true')
    with patch('news_quality.analyze_strict',return_value=draft()) as strict, patch('news_quality.analyze_market_fast') as fast:
        quality.analyze_one(row())
        strict.assert_called_once()
        fast.assert_not_called()


def test_foreign_script_corruption_rejected():
    assert not quality.terminology_grounded(draft() | {'title_he':'מחיר الهدف'}, {'title':'price target'})
    assert not quality.terminology_grounded(draft() | {'title_he':'קטayama'}, {'title':'Katayama'})
    assert not quality.terminology_grounded(draft() | {'title_he':'התחזקות הין'}, {'title':'yen depreciation'})
    assert not quality.terminology_grounded(draft() | {'title_he':'יין יפני'}, {'title':'Japanese yen'})
    assert not quality.terminology_grounded(draft() | {'title_he':'תנודתיות אג'}, {'title':'TREASURY VOLATILITY SURGES AS FED BETS SHIFT'})


def test_auction_imbalance_keeps_strict_review(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_NEWS_FAST_MARKET','true')
    with patch('news_quality.analyze_strict',return_value=draft()) as strict:
        quality.analyze_one(row() | {'thesis':None,'title':'MOO IMBALANCE'})
    strict.assert_called_once()


def test_routine_sec_metadata_uses_no_model_but_material_excerpt_does():
    value=row() | {'provider':'sec_edgar','title':'424B2 - Example Inc',
                   'source_facts_json':json.dumps({'source_excerpt':'Filed: 2026-09-25 AccNo: 0001234567-26-000001 Size: 12 KB'})}
    with patch('news_quality.analyze_strict',return_value=draft()) as model:
        assert quality.analyze_one(value)['related'] is False
        model.assert_not_called()
        value['source_facts_json']=json.dumps({'source_excerpt':'Issuer reports an unexpected default.'})
        quality.analyze_one(value)
        model.assert_called_once()


def test_numeric_gate_rejects_invented_time_and_price():
    facts={'title':'Midday: Bitcoin pulls back to $84,000','source_excerpt':''}
    assert quality.numbers_grounded(draft() | {'title_he':'ביטקוין ירד ל־84,000','summary_he':'בצהרי היום'},facts)
    assert not quality.numbers_grounded(draft() | {'title_he':'ביטקוין 86,000','summary_he':'בצהרי היום'},facts)
    assert not quality.numbers_grounded(draft() | {'title_he':'ביטקוין 84,000','summary_he':'בשעה 12:30'},facts)


def test_editor_rejects_unsupported_or_broken_translation_after_bounded_retry():
    bad=review();bad['unsupported_claims']=True
    with patch('news_quality.recent_events',return_value=[]), patch('scanner_engine._ollama_json',
            side_effect=[draft(),bad,draft(),bad]) as model:
        with pytest.raises(ValueError,match='quality_rejected'):quality.analyze_one(row())
    assert model.call_count==4


def test_same_event_suppressed_but_material_new_fact_preserved():
    for changed, expected in [(False,3),(True,0)]:
        verdict=review();verdict.update(duplicate_of=3,material_new_fact=changed)
        with patch('news_quality.recent_events',return_value=[row() | {'id':3}]), patch('scanner_engine._ollama_json',
                side_effect=[draft(),review(),{'duplicate_of':3,'material_new_fact':changed},{'thesis_effect':'unchanged'}]):
            assert quality.analyze_one(row())['duplicate_of']==expected


def test_one_bad_item_does_not_poison_another():
    with patch('news_quality.analyze_one',side_effect=[ValueError('news_schema_missing_fields'),draft() | {'id':8}]):
        result=news_pipeline._default_analyzer([row(),row() | {'id':8}])
    assert result[0]['_error']
    assert result[1]['id']==8 and '_error' not in result[1]
