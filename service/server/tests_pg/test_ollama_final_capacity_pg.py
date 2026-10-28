"""Actual isolated PostgreSQL admission/accounting; all inference is synthetic."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_signal_inputs import clock
from test_ollama_final_capacity import test_large_local_review_reaches_real_pending_entry_exit_without_paid_call as exercise


def test_pg_large_local_review_real_signal_order_fill_exit_restart(pg,clock,monkeypatch):
    exercise(pg,clock,monkeypatch)


def test_pg_capacity_fallback_provenance_no_cooldown_or_duplicate_job(pg,monkeypatch):
    import database,ai_routing,final_ai
    from test_ai_routing import cloud,DECISION
    from test_ollama_final_capacity import guarded_health
    monkeypatch.setenv('AI_TRADER_CLOUD','true');monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','true')
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic');monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','openrouter')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_MODEL','synthetic')
    monkeypatch.setattr(ai_routing,'_until',0)
    monkeypatch.setattr(ai_routing,'relay',lambda method,path,*a,**k:guarded_health() if path=='/health' else (_ for _ in ()).throw(ai_routing.LocalCapacity()))
    monkeypatch.setattr('ai_budget.check',Mock());monkeypatch.setattr('ai_budget.acquire_request_slot',Mock())
    paid=Mock(return_value=cloud(DECISION));monkeypatch.setattr('requests.post',paid)
    trace=final_ai.new_trace('synthetic','FIXTURE',1);token=final_ai.TRACE.set(trace)
    try:assert final_ai.review([{'role':'user','content':'synthetic'}],lambda v:v)==DECISION
    finally:final_ai.TRACE.reset(token)
    final_ai.persist(trace)
    with database.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM scanner_final_ai_telemetry').fetchone()['n']==1
        attempts=json.loads(c.execute('SELECT attempts_json FROM scanner_final_ai_telemetry').fetchone()['attempts_json'])
        assert len(attempts)==2 and attempts[0]['reject_reason']=='local_context_capacity'
        assert attempts[1]['fallback_reason']=='local_context_capacity'
        costs=c.execute('SELECT model,actual_cost FROM ai_call_usage').fetchall()
        assert len(costs)==2 and sum(row['actual_cost'] for row in costs)==.001
        assert sum(row['model'].startswith('ollama/') and row['actual_cost']==0 for row in costs)==1
        for table in ('scanner_signals','scanner_orders','scanner_trades','scanner_fills','scanner_telegram_outbox'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0
    assert paid.call_count==1 and ai_routing._until==0
