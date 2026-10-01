import json
import os
import subprocess
import time
import shutil
from contextlib import contextmanager
from datetime import datetime,timezone
from unittest.mock import Mock
import pytest
import news_forensics as f
from news_events.call_context import CURRENT

@pytest.fixture
def capture_env(tmp_path,monkeypatch):
 monkeypatch.setattr(f,'ROOT',tmp_path/'capture')
 # Linux lock tested separately; local Windows has no fcntl/O_NOFOLLOW.
 if os.name=='nt':
  @contextmanager
  def lock():
   f.ROOT.mkdir(exist_ok=True);yield
  monkeypatch.setattr(f,'locked',lock)
  monkeypatch.setattr(os,'O_NOFOLLOW',0,raising=False)
 key=tmp_path/'recipient';key.write_text('age1'+'q'*58)
 monkeypatch.setenv('NEWS_FORENSICS_RECIPIENT_FILE',str(key))
 monkeypatch.setenv('NEWS_FORENSICS_UNTIL',datetime.fromtimestamp(time.time()+3600,timezone.utc).isoformat())
 token=CURRENT.set(dict(event_id='event',version='v1',stage='repair_review'))
 encrypt=Mock(return_value=Mock(stdout=b'age-encryption.org/v1\nencrypted'))
 monkeypatch.setattr(subprocess,'run',encrypt)
 yield encrypt
 CURRENT.reset(token)

def save(content='{"ok":true}{"ok":false}'):
 f.capture({'provider':'test','choices':[{'message':{'content':content,'reasoning':'NEVER RETAIN'},'finish_reason':'stop'}]}, {'type':'object'},'test',json.dumps({'reason':'invalid_json'}))

def test_encrypted_redacted_and_no_envelope(capture_env,monkeypatch):
 monkeypatch.setenv('TELEGRAM_BOT_TOKEN','123456789:secretabc')
 save('123456789:secretabc sk-or-v1-private https://host/secret?a=b person@example.com')
 data=json.loads(capture_env.call_args.kwargs['input'])
 assert 'secretabc' not in data['response_content'] and 'private' not in data['response_content']
 assert 'person@' not in data['response_content'] and 'host/' not in data['response_content']
 assert 'reasoning' not in data and 'NEVER RETAIN' not in json.dumps(data)
 assert data['stage']=='repair_review'
 assert len(list(f.ROOT.glob('*.age')))==1
 assert not any(b'secretabc' in p.read_bytes() for p in f.ROOT.iterdir())

def test_max20_never_replenished(capture_env):
 for _ in range(25):save()
 assert capture_env.call_count==20
 for p in f.ROOT.glob('*.age'):os.utime(p,(0,0))
 f.cleanup();save()
 assert not list(f.ROOT.glob('*.age')) and capture_env.call_count==20

@pytest.mark.parametrize('deadline',['','2020-01-01T00:00:00Z','2099-01-01T00:00:00Z','2026-01-01'])
def test_disabled_expired_or_unbounded(capture_env,monkeypatch,deadline):
 monkeypatch.setenv('NEWS_FORENSICS_UNTIL',deadline);save()
 capture_env.assert_not_called()

def test_encryption_failure_no_plaintext(capture_env):
 capture_env.side_effect=subprocess.TimeoutExpired('age',2)
 save();assert not list(f.ROOT.glob('*.age'))
 assert json.loads((f.ROOT/'state.json').read_text())['count']==1

def test_capture_requires_canonical_context(capture_env):
 token=CURRENT.set(None)
 try:save()
 finally:CURRENT.reset(token)
 capture_env.assert_not_called()

def test_bound_input_and_schema(capture_env):
 save('א'*1000000)
 data=json.loads(capture_env.call_args.kwargs['input'])
 assert data['truncated'] and len(capture_env.call_args.kwargs['input'])<=65536
 assert capture_env.call_args.kwargs['timeout']==2

def test_cleanup_independent_of_activation(capture_env,monkeypatch):
 save();p=next(f.ROOT.glob('*.age'));os.utime(p,(0,0))
 monkeypatch.delenv('NEWS_FORENSICS_UNTIL');f.cleanup()
 assert not p.exists()

def test_transport_does_not_change_failure_or_add_requests(capture_env,monkeypatch):
 import ai_provider
 monkeypatch.setenv('OPENROUTER_API_KEY','fake');monkeypatch.setenv('OPENROUTER_MODEL','fake')
 monkeypatch.setattr('ai_budget.check',lambda:None);monkeypatch.setattr('ai_budget.acquire_request_slot',lambda:None)
 record=Mock();monkeypatch.setattr('ai_operations.record',record)
 response=Mock();response.json.return_value={'choices':[{'message':{'content':'{} {} {"conflict":1}'}}]}
 post=Mock(return_value=response);monkeypatch.setattr(ai_provider.requests,'post',post)
 with pytest.raises(ValueError,match='invalid_json'):
  ai_provider.json_completion('test',{},max_attempts=1,news_json_wrapping=True)
 assert post.call_count==record.call_count==capture_env.call_count==1

@pytest.mark.skipif(os.name!='posix' or not shutil.which('age'),reason='real age/Linux required')
def test_real_age_roundtrip_permissions_and_cleanup(tmp_path,monkeypatch):
 identity=tmp_path/'identity'
 subprocess.run(['age-keygen','-o',str(identity)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 recipient=subprocess.run(['age-keygen','-y',str(identity)],check=True,capture_output=True).stdout.decode().strip()
 public=tmp_path/'recipient';public.write_text(recipient)
 monkeypatch.setattr(f,'ROOT',tmp_path/'capture')
 monkeypatch.setenv('NEWS_FORENSICS_RECIPIENT_FILE',str(public))
 monkeypatch.setenv('NEWS_FORENSICS_UNTIL',datetime.fromtimestamp(time.time()+3600,timezone.utc).isoformat())
 token=CURRENT.set(dict(event_id='fixture',version='1',stage='quality_review'))
 try:save()
 finally:CURRENT.reset(token)
 path=next(f.ROOT.glob('*.age'))
 decoded=subprocess.run(['age','-d','-i',str(identity),str(path)],check=True,capture_output=True).stdout
 assert json.loads(decoded)['response_content']=='{"ok":true}{"ok":false}'
 assert path.stat().st_mode & 0o777==0o600
 assert f.ROOT.stat().st_mode & 0o777==0o700
 os.utime(path,(0,0));f.cleanup();assert not path.exists()
