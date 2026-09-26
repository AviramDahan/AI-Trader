from unittest.mock import Mock
import pytest
import time,json
import retry_policy as policy
import ai_budget
import database

def test_provider_cooldown_persists_without_model_calls(pg,monkeypatch):
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    with pytest.raises(policy.DeferredProviderError):
        policy.defer_openrouter(Mock(status_code=429,headers={'Retry-After':'1800'}))
    with pytest.raises(policy.DeferredProviderError):ai_budget.check_provider_cooldown()
    with database.get_db_connection() as c:
        value=json.loads(c.execute("SELECT value_json FROM scanner_settings WHERE key='ai_provider_retry_after'").fetchone()['value_json'])
    assert value['until']>time.time()+1700
    with pytest.raises(policy.DeferredProviderError):
        policy.defer_openrouter(Mock(status_code=429,headers={'Retry-After':'60'}))
    with database.get_db_connection() as c:
        latest=json.loads(c.execute("SELECT value_json FROM scanner_settings WHERE key='ai_provider_retry_after'").fetchone()['value_json'])
    assert latest['until']>=value['until']

@pytest.mark.parametrize('attempts,result,expected',[
    (5,'failed','failed'),(0,'{"terminal":true,"http_status":403}','failed'),
    (0,'{"retry_after":7200,"http_status":429}','retry')])
def test_telegram_bounded_retry_and_dedupe(pg,monkeypatch,attempts,result,expected):
    import scanner_engine as engine
    import stock_scanner
    from datetime import datetime,timezone
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    send=Mock(return_value=result)
    monkeypatch.setattr(stock_scanner,'send_telegram',send)
    with database.get_db_connection() as c:
        c.execute('''INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at)
            VALUES('retry-test','market_news','mock','pending',?,'2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')''',(attempts,))
    engine.process_telegram_outbox();engine.process_telegram_outbox()
    assert send.call_count==1
    with database.get_db_connection() as c:
        row=c.execute("SELECT * FROM scanner_telegram_outbox WHERE dedupe_key='retry-test'").fetchone()
    assert row['status']==expected
    if expected=='retry':
        assert (datetime.fromisoformat(row['next_attempt_at'].replace('Z','+00:00'))-datetime.now(timezone.utc)).total_seconds()>7100
