"""Actual news producer to gateway contract; native generation is mocked."""
import pytest
import news_quality
from test_ollama_on_demand_independent import gateway, Native


def test_actual_strict_news_budget_reaches_native_without_reduction(monkeypatch):
    g=gateway();engine=g.Inference();native=Native(g);engine.http=native
    budgets=[]
    class Captured(Exception):pass
    def source(stage,function,system,payload,predict,**kwargs):
        assert stage=='source_analysis'
        budgets.append(predict)
        engine.complete({'protocol':2,'model':g.MODEL,'digest':g.DIGEST,
            'messages':[{'role':'system','content':system},{'role':'user','content':'synthetic source'}],
            'schema':kwargs['schema'],'predict':predict,'request_id':'synthetic-contract'})
        raise Captured()
    monkeypatch.setattr(news_quality,'news_call',source)
    with pytest.raises(Captured):
        news_quality.analyze_strict({'id':1,'scope':'universe','title':'Synthetic company report',
            'verified_tickers_json':'["FIXTURE"]','source_facts_json':'{}'})
    assert budgets==[2400]
    assert len(native.posts())==1
    assert native.posts()[0][2]['options']['num_predict']==2400
    assert native.posts()[0][2]['options']['num_ctx']==8192
    assert native.posts()[0][2]['truncate'] is False
    assert native.posts()[0][2]['shift'] is False
    assert engine.last_request['budget_seconds']==120


@pytest.mark.parametrize('predict',[450,1000,2048,2400])
def test_existing_clients_keep_exact_output_and_deadline_contract(predict):
    g=gateway();engine=g.Inference();native=Native(g);engine.http=native
    native.loaded=True
    engine.complete({'protocol':2,'model':g.MODEL,'digest':g.DIGEST,
        'messages':[{'role':'user','content':'synthetic'}],
        'schema':None,'predict':predict,'request_id':'synthetic-contract'})
    assert len(native.posts())==1
    assert native.posts()[0][2]['options']['num_predict']==predict
    assert engine.last_request['budget_seconds']==45


@pytest.mark.parametrize('protocol,predict',[(1,2049),(2,2401),(2,True),(2,0),(2,2400.5)])
def test_protocol_limits_still_fail_before_model_load(protocol,predict):
    g=gateway();engine=g.Inference();native=Native(g);engine.http=native
    with pytest.raises(ValueError,match='invalid_predict'):
        engine.complete({'protocol':protocol,'model':g.MODEL,'digest':g.DIGEST,
            'messages':[{'role':'user','content':'synthetic'}],
            'schema':None,'predict':predict,'request_id':'synthetic-contract'})
    assert native.calls==[] and not engine.slot.locked()
