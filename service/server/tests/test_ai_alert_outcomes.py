import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import Mock,MagicMock
import pytest
import requests
import ai_provider,ai_operations,retry_policy

@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','unchanged-test-model')
    monkeypatch.setattr('ai_budget.check',lambda:None)
    monkeypatch.setattr('ai_budget.acquire_request_slot',lambda:None)
    monkeypatch.setattr(ai_provider.time,'sleep',lambda _:None)
    db=MagicMock()
    monkeypatch.setattr('database.get_db_connection',lambda:db)
    alert=Mock();monkeypatch.setattr(ai_operations,'enqueue',alert)
    return alert,db

def response(content,finish='stop'):
    result=Mock()
    result.json.return_value={'choices':[{'message':{'content':content},'finish_reason':finish}],
                              'usage':{'cost':.001,'prompt_tokens':10,'completion_tokens':5}}
    return result

def test_repaired_json_records_both_attempts_without_failure_alert(provider,monkeypatch):
    alert,db=provider
    post=Mock(side_effect=[response('bad SECRET'),response('{"ok":true}')])
    monkeypatch.setattr(ai_provider.requests,'post',post)
    assert ai_provider.json_completion('test',{})=={'ok':True}
    alert.assert_not_called()
    calls=db.__enter__.return_value.execute.call_args_list
    assert len(calls)==2
    assert calls[0].args[1][1]=='news_analysis'
    assert calls[1].args[1][1]=='retry_repair'
    assert 'invalid_json' in calls[0].args[1][11]
    assert 'SECRET' not in calls[0].args[1][11]

def test_terminal_schema_failure_alert_once(provider,monkeypatch):
    alert,db=provider
    monkeypatch.setattr(ai_provider.requests,'post',Mock(return_value=response('bad SECRET')))
    with pytest.raises(ValueError,match='invalid_json'):ai_provider.json_completion('test',{})
    alert.assert_called_once()
    assert 'invalid_json' in alert.call_args.args[1]
    assert 'SECRET' not in alert.call_args.args[1]

def test_truncation_reason_and_single_retry(provider,monkeypatch):
    alert,db=provider
    post=Mock(return_value=response('{}','length'))
    monkeypatch.setattr(ai_provider.requests,'post',post)
    with pytest.raises(ValueError,match='ai_output_truncated'):ai_provider.json_completion('test',{})
    assert post.call_count==2
    alert.assert_called_once()

def test_timeout_recovery_no_active_error(provider,monkeypatch):
    alert,_=provider
    monkeypatch.setattr(ai_provider.requests,'post',Mock(side_effect=[requests.Timeout(),response('{}')]))
    assert ai_provider.json_completion('test',{})=={}
    alert.assert_not_called()

def test_schema_metadata_does_not_leak_instance():
    import jsonschema
    try:jsonschema.validate({'secret':'PRIVATE'},{'type':'object','additionalProperties':False})
    except jsonschema.ValidationError as exc:
        detail=retry_policy.validation_detail(exc)
        assert 'PRIVATE' not in detail and 'secret' not in detail
        assert json.loads(detail)['validator']=='additionalProperties'

def test_alert_sanitizes_untrusted_fields():
    assert retry_policy.alert_failure_detail('{"reason":"PRIVATE","http_status":429,"body":"SECRET"}')=='{"http_status": 429}'
