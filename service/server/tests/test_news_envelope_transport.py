import json
from unittest.mock import Mock
import pytest
import ai_provider
from news_structured_envelope import FUNCTION_NAME

SCHEMA={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','unchanged')
    check=Mock();slot=Mock();record=Mock()
    monkeypatch.setattr('ai_budget.check',check)
    monkeypatch.setattr('ai_budget.acquire_request_slot',slot)
    monkeypatch.setattr('ai_operations.record',record)
    post=Mock();monkeypatch.setattr(ai_provider.requests,'post',post)
    monkeypatch.setattr('news_forensics.capture',Mock())
    return post,check,slot,record

def envelope(arguments='{"ok":true}',content=None):
    return {'choices':[{'finish_reason':'tool_calls','message':{'content':content,'tool_calls':[
        {'type':'function','function':{'name':FUNCTION_NAME,'arguments':arguments}}]}}],
        'usage':{'cost':.001,'prompt_tokens':10,'completion_tokens':5}}

def call():
    return ai_provider.json_completion('test',{},schema=SCHEMA,max_attempts=1,structured_news=True)

def test_forced_contract_budget_and_single_cost_record(client):
    post,check,slot,record=client
    post.return_value.json.return_value=envelope()
    assert call()=={'ok':True}
    wire=post.call_args.kwargs['json']
    assert 'response_format' not in wire
    assert wire['tool_choice']['function']['name']==FUNCTION_NAME
    assert wire['tools'][0]['function']['strict'] is True
    check.assert_called_once();slot.assert_called_once();record.assert_called_once()

@pytest.mark.parametrize('arguments,content', [('{}','SECRET prose'),('{"ok":true} {}',None),('{"ok":"bad"}',None)])
def test_malformed_no_nested_retry(client,arguments,content):
    post,_,_,record=client
    post.return_value.json.return_value=envelope(arguments,content)
    with pytest.raises(ValueError,match='openrouter_schema_failed') as exc:call()
    assert 'SECRET' not in str(exc.value)
    post.assert_called_once();record.assert_called_once()

def test_budget_block_no_network(client):
    post,check,_,_=client
    check.side_effect=RuntimeError('budget_exhausted')
    with pytest.raises(RuntimeError):call()
    post.assert_not_called()

def test_legacy_contract_unchanged(client):
    post,_,_,_=client
    post.return_value.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
    assert ai_provider.json_completion('test',{},schema=SCHEMA,max_attempts=1)=={'ok':True}
    assert 'tools' not in post.call_args.kwargs['json']
    assert post.call_args.kwargs['json']['response_format']['type']=='json_schema'

def test_globe_ipv4_preference_provider_local():
    from news_events.providers import Config
    from news_events.press_feed import PressFeedProvider
    for pid in ('globenewswire','prnewswire'):
        p=PressFeedProvider(Config(pid,'https://example.com/rss',pid))
        assert p.transport.prefer_ipv4==(pid=='globenewswire')

def test_ipv4_selection_single_connect(monkeypatch):
    import news_events.providers as mod
    monkeypatch.setattr(mod,'resolve_public',lambda _:['2606:4700::1111','8.8.8.8'])
    connect=Mock(side_effect=OSError(101,'SECRET inaccessible'))
    monkeypatch.setattr(mod.socket,'create_connection',connect)
    with pytest.raises(mod.ProviderFailure,match='transport_connect_oserror_101'):
        mod.Transport(['example.com'],read_timeout=10,prefer_ipv4=True).request('https://example.com/rss')
    connect.assert_called_once_with(('8.8.8.8',443),timeout=3)
