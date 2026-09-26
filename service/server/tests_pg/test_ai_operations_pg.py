import time
from unittest.mock import Mock
import ai_operations as ops
import database

def test_records_actual_cost_retry_and_unknown_cost_without_inventing(pg,monkeypatch):
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    body={'id':'generation-test','usage':{'prompt_tokens':12,'completion_tokens':5,
        'completion_tokens_details':{'reasoning_tokens':2},'cost':.012}}
    ops.record('news_analysis','model',body,time.monotonic(),False,'schema',retry=True)
    ops.record('final_stock_review','model',None,time.monotonic(),False,'timeout')
    with database.get_db_connection() as conn:
        rows=conn.execute('SELECT * FROM ai_call_usage ORDER BY timestamp').fetchall()
    assert rows[0]['task']=='retry_repair' and rows[0]['actual_cost']==.012
    assert rows[0]['reasoning_tokens']==2
    assert rows[1]['actual_cost'] is None

def test_admin_dedupe_and_destination_isolation(pg,monkeypatch):
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID','private-test')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','mock')
    monkeypatch.setenv('TELEGRAM_CHAT_ID','public-test')
    result=Mock();result.json.return_value={'ok':True,'result':{'message_id':1}}
    post=Mock(return_value=result);monkeypatch.setattr(ops.requests,'post',post)
    ops.enqueue('budget:month:75','private test')
    ops.enqueue('budget:month:75','private test')
    ops.send_one();ops.send_one()
    assert post.call_count==1
    assert post.call_args.kwargs['json']['chat_id']=='private-test'
    with database.get_db_connection() as conn:
        assert conn.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0

def test_reconciliation_uses_no_ai_and_preserves_discrepancy(pg,monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','mock')
    result=Mock();result.json.return_value={'data':{'usage_monthly':19,'limit':25,'limit_remaining':6,'total_credits':25,'total_usage':19}}
    monkeypatch.setattr(ops.requests,'get',Mock(return_value=result))
    first=ops.reconcile();ops.reconcile()
    assert first['discrepancy']==19 and first['news']==0
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT count(*) n FROM admin_alerts WHERE dedupe_key LIKE 'budget:%'").fetchone()['n']==1

def test_credit_thresholds_dedupe_and_manual_purchase_rearms(pg):
    for balance in (1.9,.9,.8):
        ops.credit_alerts(dict(total_credits=5,credit_balance=balance))
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT count(*) n FROM admin_alerts").fetchone()['n']==2
    ops.credit_alerts(dict(total_credits=10,credit_balance=.9))
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT count(*) n FROM admin_alerts").fetchone()['n']==4

def test_payment_latch_survives_restart_and_clears_only_purchase_or_month(pg,monkeypatch):
    import ai_budget
    import pytest
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    monkeypatch.setattr(ops,'credits',lambda:dict(total_credits=5,credit_balance=.1))
    ai_budget.payment_rejected()
    with pytest.raises(ai_budget.BudgetUnavailable):
        ai_budget.check_payment_latch(dict(total_credits=5))
    ai_budget.check_payment_latch(dict(total_credits=10))
