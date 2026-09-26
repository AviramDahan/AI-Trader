"""No external calls; PostgreSQL-only tests live in tests_pg, opt-in explicitly."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import active_snapshot
import ai_provider
import cloud_runtime
import final_ai


def test_cloud_roles_are_disjoint_and_monitor_has_no_ai():
    tasks = [set(v.split(',')) for v in cloud_runtime.ROLES.values()]
    assert all(not a & b for i,a in enumerate(tasks) for b in tasks[i+1:])
    assert tasks[1] == {'stock_signal_monitor','stock_quote_refresh'}


def test_cloud_final_refuses_local_fallback(monkeypatch):
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','ollama')
    with pytest.raises(ValueError,match='cloud_requires_openrouter'):
        final_ai.configuration()


def test_cloud_news_no_key_no_network(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    request = Mock()
    monkeypatch.setattr(ai_provider.requests,'post',request)
    with pytest.raises(ValueError):
        ai_provider.json_completion('Translate',{})
    request.assert_not_called()


def test_openrouter_capabilities_can_omit_temperature_disable_reasoning(monkeypatch):
    monkeypatch.setenv('OPENROUTER_TEMPERATURE','')
    monkeypatch.setenv('OPENROUTER_REASONING_EFFORT','none')
    assert ai_provider.request_options() == {'reasoning': {'enabled': False}}


@pytest.mark.parametrize('failure',['schema','timeout'])
def test_cloud_news_one_shared_retry_only(monkeypatch,failure):
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','test/model')
    monkeypatch.setenv('OPENROUTER_API_KEY','test-key')
    post = Mock(side_effect=requests.Timeout()) if failure=='timeout' else Mock(return_value=Mock(json=lambda:{'choices':[{'message':{'content':'bad json'}}]}))
    monkeypatch.setattr(ai_provider.requests,'post',post)
    monkeypatch.setattr(ai_provider.time,'sleep',lambda _:None)
    with pytest.raises(ValueError):
        ai_provider.json_completion('Translate',{})
    assert post.call_count == 2
    assert all('openrouter.ai' in call.args[0] for call in post.call_args_list)


def test_cloud_news_validates_schema(monkeypatch):
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','test/model')
    monkeypatch.setenv('OPENROUTER_API_KEY','test-key')
    response=Mock(json=lambda:{'choices':[{'message':{'content':'{"summary":"תקציר"}'}}]})
    post=Mock(return_value=response)
    monkeypatch.setattr(ai_provider.requests,'post',post)
    schema={'type':'object','properties':{'summary':{'type':'string'}},'required':['summary'],'additionalProperties':False}
    assert ai_provider.json_completion('Translate',{},schema=schema)['summary']=='תקציר'
    assert post.call_args.kwargs['json']['response_format']['json_schema']['strict'] is True


def test_snapshot_rejects_checksum_tampering():
    data={'version':1,'tables':{t:[] for t in active_snapshot.TABLES},'snapshot_id':'wrong'}
    with pytest.raises(ValueError,match='checksum'):
        active_snapshot.validate(data)


def test_docker_context_excludes_secrets():
    root=Path(__file__).resolve().parents[3]
    content=(root/'.dockerignore').read_text()
    assert content.startswith('**\n')
    assert '!service/server/*.py' in content
    assert '!deploy/secrets' not in content and '!service/server/data' not in content
