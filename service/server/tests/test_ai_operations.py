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
    assert result['projected'] is None and result['days_until_cap'] is None
    assert 'אין מספיק נתונים' in ops.notification(result)


def test_community_cost_is_separate_but_in_monthly_total():
    result=ops.calculate([{'task':'news_analysis','actual_cost':2},
                          {'task':'community_discussion','actual_cost':.01}],{'usage_monthly':3})
    assert result['community']==.01 and result['news']==2
    assert abs(result['local_total']-2.01)<1e-9 and abs(result['discrepancy']-.99)<1e-9
    assert 'Community discussion' in ops.notification(result)

def test_forecast_uses_measured_delta_not_historical_unassigned_spend():
    from datetime import timedelta
    start=datetime(2026,9,11,tzinfo=timezone.utc)
    samples=[dict(timestamp=(start+timedelta(hours=i)).isoformat(),usage=10+i/24) for i in range(169)]
    result=ops.calculate([],{'usage_monthly':17},start+timedelta(days=7),samples)
    assert result['average_daily_burn']==1
    assert result['projected']==30
    assert result['discrepancy']==17
    assert ops.calculate([],{'usage_monthly':17},start+timedelta(days=7),[samples[0],samples[-1]])['projected'] is None

def test_missing_usage_is_not_zero():
    result=ops.calculate([],{},datetime(2026,9,1,tzinfo=timezone.utc))
    assert result['total'] is None and result['projected'] is None

def test_private_alert_never_falls_back_to_public_chat():
    with patch.dict('os.environ',{'TELEGRAM_ADMIN_CHAT_ID':'','TELEGRAM_CHAT_ID':'public'}),patch.object(ops.requests,'post') as post:
        ops.send_one()
        post.assert_not_called()

def test_reconciliation_failure_does_not_block_admin_delivery():
    import asyncio
    from unittest.mock import MagicMock,AsyncMock
    import pytest
    connection=MagicMock()
    connection.__enter__.return_value.execute.return_value.fetchone.return_value=None
    with patch('database.get_db_connection',return_value=connection),patch.object(ops,'reconcile',side_effect=RuntimeError()),patch.object(ops,'enqueue'),patch.object(ops,'health'),patch.object(ops,'send_one') as send,patch.object(ops.asyncio,'sleep',new=AsyncMock(side_effect=RuntimeError('end-test'))):
        with pytest.raises(RuntimeError,match='end-test'):asyncio.run(ops.operations_loop())
        send.assert_called_once()
