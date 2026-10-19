"""Presentation allowlist only; execution/accounting contracts are untouched."""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from entry_rejection import CODES, order_reason, reason_code


@pytest.mark.parametrize('value',[None,'',{'fill_rr_below_2':True},'private://credential','unknown_future_reason','__proto__'])
def test_unknown_or_private_text_is_not_public_execution_evidence(value):
    assert reason_code(value) is None


def test_each_known_reason_is_projected_without_raw_execution_settings():
    for code in CODES:
        order=dict(purpose='entry',status='invalid',plan_json=json.dumps(dict(entry_rejection_reason=code,secret='private')))
        before=dict(order)
        assert order_reason(order)==code and order==before
        for key,value in [('purpose','close_long'),('status','pending'),('status','filled')]:
            assert order_reason(dict(order,**{key:value})) is None
    for text in ('{broken','[]','null'):
        assert order_reason(dict(purpose='entry',status='invalid',plan_json=text)) is None


def test_new_strategy_wait_reasons_have_specific_hebrew_and_do_not_claim_fill():
    from entry_strategy_execution import PRICE_REASONS
    from paper_execution_presentation import order_update_lines
    for code in PRICE_REASONS:
        lines = order_update_lines('pending', 'BUY', price_wait={'reason': code})
        assert any('סיבת דחיית המחיר' in line for line in lines)
        assert 'לא נפתחה פוזיציה חדשה מהפקודה הזאת.' in lines
        assert any('הסטופ, היעד והתוקף לא השתנו' in line for line in lines)
