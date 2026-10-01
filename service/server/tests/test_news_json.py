import json
from unittest.mock import Mock,patch
import pytest
from news_json import parse

@pytest.mark.parametrize('text,mode',[
 ('{"ok":true}',None),
 ('```json\n{"ok":true}\n```','code_fence'),
 ('{"ok":true}\n{"ok":true}','identical_objects'),
 ('```json\n{"ok":true} {"ok":true}\n```','fenced_identical_objects')])
def test_lossless_wrappers_only(text,mode):assert parse(text)==({'ok':True},mode)

@pytest.mark.parametrize('text',[
 '{"ok":true}{"ok":false}', '{"ok":true}{"ok":1}',
 '{"ok":true} commentary', 'Here is JSON: {"ok":true}',
 '```json\n{"ok":true}\n``` extra', '{"ok":true,"ok":false}',
 '{"ok":NaN}', '{}'*4, '{"ok":true}{}', '```json\n{"ok":true\n```'])
def test_ambiguous_or_changed_content_fails_closed(text):
 with pytest.raises((ValueError,json.JSONDecodeError)):parse(text)

def test_transport_opt_in_schema_enforced_no_extra_call():
 import ai_provider
 response=Mock();response.json.return_value={'choices':[{'message':{'content':'{"ok":true}{"ok":true}'},'finish_reason':'stop'}],'usage':{'cost':.001}}
 schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
 with patch.dict('os.environ',{'OPENROUTER_API_KEY':'fake','OPENROUTER_MODEL':'fake'}),patch('ai_budget.check'),patch('ai_budget.acquire_request_slot'),patch('ai_provider.requests.post',return_value=response) as post,patch('ai_operations.record') as record:
  usage={}
  assert ai_provider.json_completion('system',{},schema=schema,max_attempts=1,news_json_wrapping=True,usage_sink=usage)=={'ok':True}
  assert usage['json_normalization']=='identical_objects'
  assert post.call_count==record.call_count==1
  with pytest.raises(ValueError,match='invalid_json'):
   ai_provider.json_completion('system',{},schema=schema,max_attempts=1)
  response.json.return_value['choices'][0]['message']['content']='{"ok":"yes"}{"ok":"yes"}'
  with pytest.raises(ValueError,match='schema_validation_failed'):
   ai_provider.json_completion('system',{},schema=schema,max_attempts=1,news_json_wrapping=True)
  response.json.return_value['choices'][0]['finish_reason']='length'
  with pytest.raises(ValueError,match='ai_output_truncated'):
   ai_provider.json_completion('system',{},schema=schema,max_attempts=1,news_json_wrapping=True)
  assert post.call_count==record.call_count==4
