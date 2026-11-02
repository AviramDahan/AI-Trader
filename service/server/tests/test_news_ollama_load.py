"""Offline regressions: no native model, paid API or production database."""
import copy
from unittest.mock import Mock
import pytest
import jsonschema
import requests

from test_ai_routing import fixture, native
import ai_provider
import ai_routing as routing
import news_pipeline
import news_local_backoff as backoff


@pytest.fixture(autouse=True)
def isolated_backoff(monkeypatch):
    monkeypatch.setattr(backoff,"_until",0.)
    monkeypatch.setattr(backoff,"_streak",0)
    token=backoff.begin_story()
    yield
    backoff.end_story(token)
from ai_schema_guidance import numeric_guidance, repair_guidance

SCHEMA={'type':'object','properties':{'relevance':{'type':'number','minimum':0,'maximum':1}},
        'required':['relevance'],'additionalProperties':False}


def test_numeric_bounds_come_from_schema_without_touching_source():
    schema=copy.deepcopy(SCHEMA)
    text=numeric_guidance(schema)
    assert 'relevance: number, at least 0, at most 1' in text
    assert 'never a percentage' in text
    assert schema==SCHEMA
    assert numeric_guidance(None)==''
    assert numeric_guidance({'type':'object','properties':{'ok':{'type':'boolean'}}})==''
    feedback=repair_guidance(SCHEMA,'{"validator":"maximum","private_output":"DO_NOT_COPY"}')
    assert 'violated maximum' in feedback and 'DO_NOT_COPY' not in feedback


def test_invalid_scale_gets_one_targeted_repair_not_rescaled(fixture,monkeypatch):
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    calls=[]
    def local(messages,schema,predict):
        calls.append(copy.deepcopy(messages))
        value={'relevance':90} if len(calls)==1 else {'relevance':.9}
        return value,native(value)
    monkeypatch.setattr(routing,'local_completion',local)
    payload={'source':'keep all original facts','amount':90}
    original=copy.deepcopy(payload)
    assert ai_provider.json_completion('Source only.',payload,schema=SCHEMA)=={'relevance':.9}
    assert len(calls)==2 and 'at most 1' in calls[0][0]['content']
    assert 'violated maximum' in calls[1][-1]['content']
    assert payload==original and '"amount": 90' in calls[1][1]['content']
    assert backoff.remaining()==0
    fixture[1].assert_not_called()


def test_repeated_invalid_scale_stays_rejected_and_backs_off(fixture,monkeypatch):
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    local=Mock(return_value=({'relevance':90},native({'relevance':90})))
    monkeypatch.setattr(routing,'local_completion',local)
    with pytest.raises(ValueError,match='schema_failed'):
        ai_provider.json_completion('Source only.',{},schema=SCHEMA)
    assert local.call_count==2 and backoff.remaining()>119
    assert fixture[4].call_count==2
    assert all(c.args[4] is False for c in fixture[4].call_args_list)
    fixture[1].assert_not_called()


def test_transport_failure_does_not_generate_an_immediate_repair(fixture,monkeypatch):
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    local=Mock(side_effect=requests.ConnectionError('synthetic transport failure'))
    monkeypatch.setattr(routing,'local_completion',local)
    with pytest.raises(routing.LocalUnavailable):
        ai_provider.json_completion('Source only.',{},schema=SCHEMA)
    assert local.call_count==1 and backoff.remaining()>119
    fixture[1].assert_not_called()


def test_intermediate_valid_stage_does_not_clear_repeated_failure_cooldown(fixture,monkeypatch):
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    value={'relevance':.7}
    monkeypatch.setattr(routing,'local_completion',Mock(return_value=(value,native(value))))
    backoff.failed()
    assert ai_provider.json_completion('Source only.',{},schema=SCHEMA)==value
    assert backoff.remaining()>119
    backoff.failed()
    assert backoff.remaining()>239


def test_cooldown_increases_caps_and_only_valid_story_completion_resets(monkeypatch):
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    monkeypatch.setattr(backoff,'_until',0)
    clock=[100.]
    monkeypatch.setattr(routing.time,'monotonic',lambda:clock[0])
    for wanted in [120,240,480,900,900]:
        backoff.failed()
        assert backoff.remaining()==wanted
        clock[0]+=wanted+1
    backoff.story_completed()
    assert backoff._streak==4
    backoff.validated_stage()
    backoff.story_completed()
    assert backoff.remaining()==0
    backoff.failed()
    assert backoff.remaining()==120


def test_backoff_leaves_news_queue_and_attempts_untouched(monkeypatch):
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    monkeypatch.setattr(backoff,'remaining',lambda:240)
    forbidden=Mock(side_effect=AssertionError('No queue or model work while cooling down'))
    monkeypatch.setattr(news_pipeline,'get_db_connection',forbidden)
    monkeypatch.setattr('news_events.control.active',forbidden)
    result=news_pipeline.analyze_news_jobs()
    assert result['deferred'] and result['retry_after_seconds']==240
    forbidden.assert_not_called()
    assert not news_pipeline.NEWS_ANALYSIS_LOCK.locked()


def test_cooldown_resets_only_after_complete_story_with_live_valid_stage(monkeypatch):
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    clock=[100.]
    monkeypatch.setattr(backoff.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr('news_events.control.active',lambda:False)
    backoff.failed()
    clock[0]=221.
    monkeypatch.setattr(news_pipeline,'_analyze_news_jobs',lambda *args:{'analyzed':1,'errors':[]})
    news_pipeline.analyze_news_jobs()
    assert backoff._streak==1  # An entirely cached result proves no recovery.
    def failed_story(*args):
        backoff.validated_stage()
        return {'analyzed':0,'errors':['quality_failed']}
    monkeypatch.setattr(news_pipeline,'_analyze_news_jobs',failed_story)
    news_pipeline.analyze_news_jobs()
    assert backoff._streak==1
    monkeypatch.setattr(news_pipeline,'_analyze_news_jobs',lambda *args:{'analyzed':1,'errors':[]})
    news_pipeline.analyze_news_jobs()
    assert backoff._streak==1  # Prior failed story's stage cannot count here.
    def valid_story(*args):
        backoff.validated_stage()
        return {'analyzed':1,'errors':[]}
    monkeypatch.setattr(news_pipeline,'_analyze_news_jobs',valid_story)
    news_pipeline.analyze_news_jobs()
    assert backoff._streak==0


def test_news_backoff_does_not_change_shared_route_admission(fixture,monkeypatch):
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    backoff.failed()
    assert routing.ready() is True
    assert backoff.remaining()>119


def test_unrelated_position_context_cannot_change_news_circuit():
    from contextvars import Context
    Context().run(backoff.failed)
    assert backoff.remaining()==0 and backoff._streak==0


def test_nested_batched_news_ranges_remain_explicit():
    schema={'type':'object','properties':{'items':{'type':'array','items':SCHEMA}}}
    assert 'items[].relevance: number, at least 0, at most 1' in numeric_guidance(schema)


def test_sqlite_pending_story_survives_backoff_and_resumes(monkeypatch):
    from test_news_pipeline import NewsPipelineIntegrationTests
    case=NewsPipelineIntegrationTests(methodName='runTest')
    case.setUp()
    try:
        news_pipeline.ingest_items([case.item()],case.clock)
        before={table:case.rows('SELECT * FROM '+table) for table in ['scanner_news','scanner_news_jobs','scanner_telegram_outbox']}
        monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
        monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
        monkeypatch.setattr('news_events.control.active',lambda:False)
        clock=[100.]
        monkeypatch.setattr(backoff.time,'monotonic',lambda:clock[0])
        backoff.failed()
        assert news_pipeline.analyze_news_jobs(at=case.clock)['deferred']
        assert before=={table:case.rows('SELECT * FROM '+table) for table in before}
        clock[0]=221
        analyzer=Mock(side_effect=case.strong_analyzer)
        monkeypatch.setattr(news_pipeline,'_default_analyzer',analyzer)
        result=news_pipeline.analyze_news_jobs(at=case.clock)
        assert result['analyzed']==1 and analyzer.call_count==1
        assert case.rows('SELECT status FROM scanner_news_jobs')[0]['status']=='done'
    finally:
        case.tearDown()


def test_nullable_and_union_schemas_still_pass_to_native_validation(fixture,monkeypatch):
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    schema={'type':'object','properties':{'relevance':{'type':['number','null'],'minimum':0,'maximum':1}},'required':['relevance']}
    assert numeric_guidance(schema)==''
    value={'relevance':None}
    monkeypatch.setattr(routing,'local_completion',Mock(return_value=(value,native(value))))
    assert ai_provider.json_completion('Source only.',{},schema=schema)==value
