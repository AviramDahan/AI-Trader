import json
from unittest.mock import Mock,patch
import pytest
from retry_policy import response_structure_detail,validation_detail,alert_failure_detail
from news_events.admin_outcome import message

@pytest.mark.parametrize('body,expected',[
 ([], 'body_not_object'), ({'error':{'message':'SECRET'}},'provider_error_envelope'),
 ({},'choices_missing'),({'choices':None},'choices_not_list'),
 ({'choices':[]},'choices_empty'),({'choices':[None]},'choice_not_object'),
 ({'choices':[{}]},'message_missing'),({'choices':[{'message':None}]},'message_not_object'),
 ({'choices':[{'message':{}}]},'content_missing'),
 ({'choices':[{'message':{'content':None}}]},'content_null'),
 ({'choices':[{'message':{'content':[]}}]},'content_not_text'),
 ({'choices':[{'message':{'content':'  '}}]},'content_empty'),
 ({'choices':[{'message':{'content':'SECRET'}}]},'structure_unspecified')])
def test_fixed_labels_only(body,expected):
 assert response_structure_detail(body)==expected
 detail=validation_detail(KeyError('SECRET'),body)
 assert 'SECRET' not in detail
 assert json.loads(detail)['reason']=='invalid_response_structure'

def test_admin_allowlist_rejects_untrusted_diagnostic():
 call={'success':False,'stage':'editorial_repair','failure_reason':'invalid_response_structure',
       'structure_detail':'provider_error_envelope'}
 assert 'provider_error_envelope' in message('failed',None,[call])
 call['structure_detail']='SECRET'
 assert 'SECRET' not in message('failed',None,[call])
 assert 'SECRET' not in alert_failure_detail(json.dumps({'structure_detail':'SECRET'}))

def test_transport_keeps_one_attempt_and_records_safe_detail():
 import ai_provider
 response=Mock();response.json.return_value={'error':{'message':'SECRET'}}
 usage={}
 with patch.dict('os.environ',{'OPENROUTER_API_KEY':'fake','OPENROUTER_MODEL':'fake'}), \
      patch('ai_budget.check'),patch('ai_budget.acquire_request_slot'), \
      patch('ai_provider.requests.post',return_value=response) as post, \
      patch('ai_operations.record') as record:
  with pytest.raises(ValueError,match='openrouter_schema_failed:'):
   ai_provider.json_completion('system',{},max_attempts=1,usage_sink=usage)
 assert post.call_count==1
 assert usage['structure_detail']=='provider_error_envelope'
 failure=record.call_args.args[5]
 assert json.loads(failure)['structure_detail']=='provider_error_envelope'
 assert 'SECRET' not in failure

def test_null_content_remains_terminal_without_new_retry():
 import ai_provider
 response=Mock();response.json.return_value={'choices':[{'message':{'content':None}}]}
 usage={}
 with patch.dict('os.environ',{'OPENROUTER_API_KEY':'fake','OPENROUTER_MODEL':'fake'}), \
      patch('ai_budget.check'),patch('ai_budget.acquire_request_slot'), \
      patch('ai_provider.requests.post',return_value=response) as post, \
      patch('ai_operations.record'):
  with pytest.raises(TypeError):
   ai_provider.json_completion('system',{},max_attempts=2,usage_sink=usage)
 assert post.call_count==1
 assert usage['structure_detail']=='content_null'
