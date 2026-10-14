"""Real isolated PostgreSQL atomic episodes, restart and private delivery mocks."""
import importlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import database
import ollama_connectivity_watch as watch


def test_private_connectivity_alerts_atomic_restart_and_delivery(pg, monkeypatch):
    import ai_operations
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    monkeypatch.setenv('AI_TRADER_ROLE', 'telegram')
    monkeypatch.setenv('AI_INFERENCE_MODE', 'ollama_first')
    now = datetime(2026, 10, 14, 8, tzinfo=timezone.utc)
    bad = {'status':'failed', 'reason':'private_relay_unreachable'}
    monkeypatch.setattr(watch, 'probe', Mock(return_value=bad))
    with database.get_db_connection() as c:
        tables = ('scanner_signals','scanner_orders','scanner_trades','scanner_fills','scanner_telegram_outbox','ai_call_usage')
        before = {t:c.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in tables}
    for i in range(8):
        watch.check(now+timedelta(minutes=i))
    importlib.reload(watch)
    monkeypatch.setattr(watch, 'probe', Mock(return_value={'status':'ready', 'reason':None}))
    for i in range(8,12):
        watch.check(now+timedelta(minutes=i))
    with database.get_db_connection() as c:
        alerts = c.execute('SELECT * FROM admin_alerts ORDER BY created_at').fetchall()
        assert len(alerts) == 2
        assert all(r['message'].splitlines()[-1].startswith('Timestamp:') for r in alerts)
        assert not json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(watch.KEY,)).fetchone()['value_json'])['active']
        assert {t:c.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in tables} == before
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID','private-fixture')
    monkeypatch.setenv('TELEGRAM_CHAT_ID','public-fixture')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','synthetic')
    result = Mock(); result.json.return_value = {'ok':True,'result':{'message_id':123}}
    post = Mock(return_value=result); monkeypatch.setattr(ai_operations.requests,'post',post)
    ai_operations.send_one(); ai_operations.send_one(); ai_operations.send_one()
    assert post.call_count == 2
    assert all(call.kwargs['json']['chat_id']=='private-fixture' for call in post.call_args_list)


def test_atomic_failure_does_not_consume_an_episode_without_its_alert(pg, monkeypatch):
    import pytest
    import psycopg
    monkeypatch.setenv('AI_TRADER_CLOUD','true'); monkeypatch.setenv('AI_TRADER_ROLE','telegram')
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setattr(watch,'probe',Mock(return_value={'status':'failed','reason':'private_relay_unreachable'}))
    now = datetime(2026,10,14,8,tzinfo=timezone.utc)
    watch.check(now); watch.check(now+timedelta(minutes=1))
    # Only disposable test schema: force the INSERT to fail and verify rollback.
    with database.get_db_connection() as c:
        c.execute("ALTER TABLE admin_alerts ADD CONSTRAINT reject_test_alert CHECK(dedupe_key NOT LIKE 'ollama-connectivity:%')")
    with pytest.raises(psycopg.errors.CheckViolation):watch.check(now+timedelta(minutes=2))
    with database.get_db_connection() as c:
        state=json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(watch.KEY,)).fetchone()['value_json'])
        assert not state['active'] and state['failed_checks']==2
        c.execute('ALTER TABLE admin_alerts DROP CONSTRAINT reject_test_alert')
    watch.check(now+timedelta(minutes=2))
    with database.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM admin_alerts').fetchone()['n']==1


def test_concurrent_observers_cannot_double_count_one_probe_time(pg, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    monkeypatch.setenv('AI_TRADER_CLOUD','true'); monkeypatch.setenv('AI_TRADER_ROLE','telegram')
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    bad={'status':'failed','reason':'private_relay_unreachable'}
    now=datetime(2026,10,14,8,tzinfo=timezone.utc)
    monkeypatch.setattr(watch,'probe',lambda:bad)
    watch.check(now); watch.check(now+timedelta(minutes=1))
    barrier=Barrier(2)
    def simultaneous_probe():
        barrier.wait(timeout=5)
        return bad
    monkeypatch.setattr(watch,'probe',simultaneous_probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(watch.check,[now+timedelta(minutes=2)]*2))
    assert all(r['generation']==1 and r['failed_checks']==3 for r in results)
    with database.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM admin_alerts').fetchone()['n']==1
