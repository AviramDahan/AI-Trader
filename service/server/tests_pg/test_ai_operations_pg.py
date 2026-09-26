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
    result=Mock();result.json.return_value={'data':{'usage_monthly':19,'limit':25,'limit_remaining':6}}
    monkeypatch.setattr(ops.requests,'get',Mock(return_value=result))
    first=ops.reconcile();ops.reconcile()
    assert first['discrepancy']==19 and first['news']==0
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT count(*) n FROM admin_alerts WHERE dedupe_key LIKE 'budget:%'").fetchone()['n']==1
