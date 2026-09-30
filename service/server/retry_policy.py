"""Safe operational error metadata; never include response bodies or credentials."""
import json
import time
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

def retry_after(value, now=None):
    if not isinstance(value,(str,int,float)):return 0
    try:
        numeric=float(value)
        return max(0,numeric) if math.isfinite(numeric) else 0
    except (ValueError, TypeError):
        try:
            return max(0, (parsedate_to_datetime(value)-(now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0

def detail(exc):
    response=getattr(exc,'response',None)
    return json.dumps({'exception':type(exc).__name__,
        'http_status':getattr(response,'status_code',None),
        'retry_after_seconds':retry_after(response.headers.get('Retry-After')) if response is not None else 0})


STRUCTURE_DETAILS={'body_not_object','provider_error_envelope','choices_missing',
    'choices_not_list','choices_empty','choice_not_object','message_missing',
    'message_not_object','content_missing','content_null','content_not_text',
    'content_empty','structure_unspecified'}


def response_structure_detail(body):
    """Fixed labels only: never serialize keys, values, provider error or text."""
    if not isinstance(body,dict):return 'body_not_object'
    if 'choices' not in body:
        return 'provider_error_envelope' if 'error' in body else 'choices_missing'
    choices=body['choices']
    if not isinstance(choices,list):return 'choices_not_list'
    if not choices:return 'choices_empty'
    choice=choices[0]
    if not isinstance(choice,dict):return 'choice_not_object'
    if 'message' not in choice:return 'message_missing'
    message=choice['message']
    if not isinstance(message,dict):return 'message_not_object'
    if 'content' not in message:return 'content_missing'
    content=message['content']
    if content is None:return 'content_null'
    if not isinstance(content,str):return 'content_not_text'
    if not content.strip():return 'content_empty'
    return 'structure_unspecified'


def validation_detail(exc, body=None):
    """Never serialize model content, validation instances, paths or error text."""
    import jsonschema
    reason='invalid_response_structure'
    if isinstance(exc,json.JSONDecodeError): reason='invalid_json'
    elif isinstance(exc,jsonschema.ValidationError): reason='schema_validation_failed'
    elif isinstance(exc,ValueError) and str(exc) in {'ai_output_truncated','ai_object_required'}:
        reason=str(exc)
    result={'reason':reason}
    if body is not None:
        structure=response_structure_detail(body)
        if structure!='structure_unspecified':result['structure_detail']=structure
    if isinstance(exc,jsonschema.ValidationError):
        allowed={'type','required','additionalProperties','enum','minimum','maximum','minLength','maxLength','pattern','items','anyOf','oneOf','allOf','const'}
        result['validator']=exc.validator if exc.validator in allowed else 'other'
    return json.dumps(result)


def alert_failure_detail(value):
    try:
        data=json.loads(value)
    except (ValueError,TypeError):
        return value if value in {'SchemaFailure','JSONDecodeError','Timeout','ReadTimeout','ConnectTimeout','ConnectionError','schema','timeout'} else 'unclassified_failure'
    if not isinstance(data,dict):return 'unclassified_failure'
    safe={}
    reasons={'invalid_json','schema_validation_failed','ai_output_truncated','ai_object_required','invalid_response_structure'}
    if data.get('reason') in reasons:safe['reason']=data['reason']
    if data.get('structure_detail') in STRUCTURE_DETAILS:safe['structure_detail']=data['structure_detail']
    if type(data.get('http_status')) is int:safe['http_status']=data['http_status']
    if data.get('exception') in {'HTTPError','Timeout','ReadTimeout','ConnectTimeout','ConnectionError','JSONDecodeError'}:safe['exception']=data['exception']
    delay=data.get('retry_after_seconds')
    if type(delay) in (int,float) and math.isfinite(delay) and delay>=0:safe['retry_after_seconds']=delay
    return json.dumps(safe,sort_keys=True) if safe else 'unclassified_failure'

class DeferredProviderError(RuntimeError):
    def __init__(self, status, delay):
        self.retry_after_seconds=delay
        self.status=status
        super().__init__(f'provider_http_{status};retry_after_seconds={delay}')

def defer_openrouter(response):
    """Persist cooldown; do not hold the scanner thread for a provider's long delay."""
    if response.status_code not in {429,500,502,503,504}:return
    delay=retry_after(response.headers.get('Retry-After'))
    if response.status_code==429: delay=max(60,delay)
    if delay<=0:return
    import os
    if os.getenv('AI_TRADER_CLOUD')=='true':
        from database import get_db_connection
        until=time.time()+delay
        with get_db_connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(719324,2)')
            old=c.execute("SELECT value_json FROM scanner_settings WHERE key='ai_provider_retry_after'").fetchone()
            if old:until=max(until,json.loads(old['value_json'])['until'])
            c.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('ai_provider_retry_after',?,?)
              ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
              (json.dumps({'until':until}),datetime.now(timezone.utc).isoformat()))
    raise DeferredProviderError(response.status_code,delay)
