"""Actual isolated scanner -> local transport -> order/fill/exit, mocked model."""
import json
from datetime import datetime,timezone
from unittest.mock import Mock

import pytest

from test_signal_inputs import db,clock
from test_signal_admission_chain import prepare,rows
from test_review_evidence import scanner_review
import ai_routing
import scanner_engine as engine
import stock_scanner as scanner


@pytest.mark.parametrize('block',[None,'hold','confidence','quote','session','targets'])
def test_ollama_is_transport_not_permission_to_bypass_admission(db,clock,monkeypatch,block):
    candidate,_,_=prepare(monkeypatch,clock)
    monkeypatch.setattr(scanner,'ai_review',scanner_review)
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','openrouter')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_MODEL','existing-luna')
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-no-paid')
    monkeypatch.setattr(ai_routing,'_until',0)
    paid=Mock(side_effect=AssertionError('Paid request forbidden'))
    monkeypatch.setattr('requests.post',paid)
    decision=dict(action='BUY',confidence=.91,news_sentiment=.3,news_relevance=.9,
        time_horizon='1-4 weeks',reason='Synthetic verified evidence.',
        entry_price_relation='equal',entry_price_concern='none')
    if block=='hold':decision['action']='HOLD'
    if block=='confidence':decision['confidence']=.79
    if block=='quote':monkeypatch.setattr(scanner,'current_intraday_quote',lambda *a:None)
    if block=='session':monkeypatch.setattr(scanner,'regular_session_open',lambda:False)
    if block=='targets':candidate['price_zones']=[]
    calls=[]
    def relay(method,path,payload=None,**kwargs):
        if path=='/health':return dict(protocol=1,ready=True,model=ai_routing.MODEL,digest=ai_routing.DIGEST,capacity=1)
        calls.append(payload)
        return dict(done=True,done_reason='stop',model=ai_routing.MODEL,model_digest=ai_routing.DIGEST,
            message={'content':json.dumps(decision)},prompt_eval_count=12,eval_count=8)
    monkeypatch.setattr(ai_routing,'relay',relay)
    result=scanner.run_scan();paid.assert_not_called()
    if block:
        assert result['signals_published']==0
        assert not rows('SELECT id FROM scanner_orders') and not rows('SELECT id FROM scanner_fills')
        return
    assert result['signals_published']==1 and len(calls)==1
    assert rows('SELECT status FROM scanner_orders')==[{'status':'pending'}]
    assert not rows('SELECT id FROM scanner_trades')
    clock.instant=datetime(2026,10,6,14,10,tzinfo=timezone.utc)
    entry=dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.5,close=100)
    engine.process_bar('TEST',entry)
    clock.instant=datetime(2026,10,6,14,15,tzinfo=timezone.utc)
    exit_bar=dict(at='2026-10-06T14:10:00Z',open=104.5,high=105,low=104,close=104.5)
    engine.process_bar('TEST',exit_bar);engine.initialize_runtime()
    engine.process_bar('TEST',entry);engine.process_bar('TEST',exit_bar)
    scanner.run_scan()
    assert len(rows('SELECT id FROM scanner_orders'))==1 and len(rows('SELECT id FROM scanner_fills'))==2
    assert len(calls)==1 and engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
