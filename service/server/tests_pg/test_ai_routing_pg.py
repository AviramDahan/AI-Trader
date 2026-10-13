"""Real isolated PG provenance/cost/links; model transports fully mocked."""
import json
import time
from unittest.mock import Mock

import pytest


def test_local_zero_spend_call_links_and_trace_restart(pg,monkeypatch):
    import database,ai_routing,ai_provider,final_ai
    from news_events.call_context import CURRENT
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','existing-luna')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','openrouter')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_MODEL','existing-luna')
    monkeypatch.setattr(ai_routing,'_until',0)
    decision=dict(action='HOLD',confidence=.1,news_sentiment=0,news_relevance=.5,
        time_horizon='1-4 weeks',reason='Synthetic fixture.')
    def relay(method,path,payload=None,**kwargs):
        if path=='/health':return dict(protocol=1,ready=True,model=ai_routing.MODEL,digest=ai_routing.DIGEST,capacity=1)
        value=decision if payload['predict']==450 else {'ok':True}
        return dict(done=True,done_reason='stop',model=ai_routing.MODEL,model_digest=ai_routing.DIGEST,
            message={'content':json.dumps(value)},prompt_eval_count=12,eval_count=8)
    monkeypatch.setattr(ai_routing,'relay',relay)
    monkeypatch.setattr('ai_budget.check',Mock(side_effect=AssertionError('Paid budget request forbidden')))
    with database.get_db_connection() as c:
        c.execute("INSERT INTO ne_events(event_id,body_json,evidence_version,status,created_at,updated_at) VALUES('synthetic-event','{}','v1','pending','2026-10-13T00:00:00Z','2026-10-13T00:00:00Z')")
        before={t:c.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in
            ('scanner_signals','scanner_orders','scanner_trades','scanner_fills','scanner_telegram_outbox')}
    token=CURRENT.set(dict(event_id='synthetic-event',version='v1',stage='source_analysis',final_alert_owner=True))
    try:
        ai_provider.json_completion('fixture',{},schema={'type':'object'},max_attempts=1)
    finally:CURRENT.reset(token)
    trace=final_ai.new_trace('synthetic-scan','FIXTURE',1);token=final_ai.TRACE.set(trace)
    try:
        final_ai.review([{'role':'user','content':'fixture'}],lambda v:v)
    finally:final_ai.TRACE.reset(token)
    final_ai.persist(trace) # Restart/idempotent trace persistence.
    with database.get_db_connection() as c:
        calls=c.execute('SELECT model,actual_cost,generation_id FROM ai_call_usage').fetchall()
        assert len(calls)==2 and all(r['actual_cost']==0 and r['model'].startswith('ollama/') for r in calls)
        assert all(r['generation_id'].startswith('ollama:') for r in calls)
        assert c.execute('SELECT count(*) n FROM ne_ai_call_links').fetchone()['n']==1
        saved=c.execute('SELECT provider,model,attempts_json FROM scanner_final_ai_telemetry').fetchall()
        assert len(saved)==1 and saved[0]['provider']=='ollama_relay'
        assert json.loads(saved[0]['attempts_json'])[0]['model_digest']==ai_routing.DIGEST
        after={t:c.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in before}
        assert after==before
