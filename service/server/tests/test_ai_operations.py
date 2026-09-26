from datetime import datetime,timezone
from unittest.mock import patch
import ai_operations as ops

def test_cost_split_does_not_assign_provider_discrepancy():
    rows=[{'task':'news_analysis','actual_cost':2}, {'task':'news_translation','actual_cost':1},
          {'task':'final_stock_review','actual_cost':4},{'task':'retry_repair','actual_cost':.5},
          {'task':'news_analysis','actual_cost':None}]
    result=ops.calculate(rows,{'usage_monthly':10,'limit':25,'limit_remaining':15},
                         datetime(2026,9,11,tzinfo=timezone.utc))
    assert result['news']==3 and result['final']==4 and result['retry']==.5
    assert result['discrepancy']==2.5 and result['missing_cost_calls']==1
    assert result['projected']==30 and result['days_until_cap']==15

def test_missing_usage_is_not_zero():
    result=ops.calculate([],{},datetime(2026,9,1,tzinfo=timezone.utc))
    assert result['total'] is None and result['projected'] is None

def test_private_alert_never_falls_back_to_public_chat():
    with patch.dict('os.environ',{'TELEGRAM_ADMIN_CHAT_ID':'','TELEGRAM_CHAT_ID':'public'}),patch.object(ops.requests,'post') as post:
        ops.send_one()
        post.assert_not_called()
