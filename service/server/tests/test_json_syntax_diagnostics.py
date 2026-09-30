import json
from unittest.mock import Mock,patch
import pytest
from retry_policy import validation_detail,safe_json_diagnostic,alert_failure_detail
from news_events.admin_outcome import message

@pytest.mark.parametrize('text,code',[
 ('{"secret":"DO_NOT_LOG" "x":1}','missing_comma'),
 ('{"secret" "DO_NOT_LOG"}','missing_colon'),
 ('{"secret":"DO_NOT_LOG','unterminated_string'),
 ('{"secret":DO_NOT_LOG}','expected_value'),
 ('{DO_NOT_LOG:1}','property_name_not_quoted'),
 ('{} DO_NOT_LOG','extra_data'),
 ('{"secret":"DO_NOT_LOG\\q"}','invalid_escape'),
 ('{"secret":"DO_NOT_LOG\\uXXXX"}','invalid_unicode_escape'),
 ('{"secret":"DO_NOT_LOG\n"}','invalid_control_character')])
def test_diagnostics_contain_no_response_content(text,code):
 try:json.loads(text)
 except json.JSONDecodeError as exc:
  raw=validation_detail(exc)
  diagnostic=json.loads(raw)['json_diagnostic']
  assert diagnostic=={'code':code,'line':exc.lineno,'column':exc.colno,'position':exc.pos,'output_chars':len(text)}
  assert 'DO_NOT_LOG' not in raw
  assert 'secret' not in raw
  assert json.loads(alert_failure_detail(raw))['json_diagnostic']==diagnostic

def test_admin_diagnostics_revalidated_no_arbitrary_strings_or_numbers():
 bad={'code':'missing_comma','line':'SECRET','column':True,'position':-1,'output_chars':10**50,'doc':'SECRET'}
 assert safe_json_diagnostic(bad)=={'code':'missing_comma'}
 assert safe_json_diagnostic({'code':'SECRET'})=={}
 assert safe_json_diagnostic({'code':[]})=={}
 call={'success':False,'stage':'quality_review','failure_reason':'invalid_json','json_diagnostic':bad}
 assert 'SECRET' not in message('failed',None,[call])
 assert 'אבחון JSON: missing_comma' in message('failed',None,[call])

def test_transport_persists_coordinates_without_extra_attempt():
 import ai_provider
 response=Mock();response.json.return_value={'choices':[{'message':{'content':'{"SECRET":1 "b":2}'}}]}
 usage={}
 with patch.dict('os.environ',{'OPENROUTER_API_KEY':'fake','OPENROUTER_MODEL':'fake'}), \
      patch('ai_budget.check'),patch('ai_budget.acquire_request_slot'), \
      patch('ai_provider.requests.post',return_value=response) as post,patch('ai_operations.record') as record:
  with pytest.raises(ValueError,match='openrouter_schema_failed:'):
   ai_provider.json_completion('system',{},max_attempts=1,usage_sink=usage)
 assert post.call_count==1
 assert usage['json_diagnostic']['code']=='missing_comma'
 assert 'SECRET' not in record.call_args.args[5]
 assert json.loads(record.call_args.args[5])['json_diagnostic']==usage['json_diagnostic']

def test_unknown_parser_message_never_echoed():
 raw=validation_detail(json.JSONDecodeError('SECRET','SECRET',1))
 assert 'SECRET' not in raw
 assert json.loads(raw)['json_diagnostic']['code']=='unknown_syntax'
