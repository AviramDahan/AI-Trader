import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import scanner_engine
import stock_scanner
from database import get_db_connection


@pytest.mark.parametrize('expired', [False, True])
def test_sec_activity_postgres_claim_sends_once_or_marks_expired_unknown(pg, monkeypatch, expired):
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(minutes=1)).isoformat().replace('+00:00', 'Z')
    monkeypatch.setenv('SEC_INTELLIGENCE_MODE', 'paper')
    monkeypatch.setenv('SEC_INTELLIGENCE_KILL_SWITCH', 'false')
    monkeypatch.setenv('STOCK_SCANNER_TELEGRAM_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_OWNERSHIP_ACTIVITY_THREAD_ID', '41')
    monkeypatch.setenv('TELEGRAM_BUYBACK_ACTIVITY_THREAD_ID', '42')
    monkeypatch.setenv('SEC_ACTIVITY_TOPICS_NOT_BEFORE', stamp)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100123')
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    payload = json.dumps({'version': 1, 'thread': 41, 'accepted_at': stamp, 'text': 'Synthetic filing'})
    with get_db_connection() as conn:
        conn.execute("""INSERT INTO scanner_telegram_outbox
            (dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at)
            VALUES('sec-activity:test','ownership_activity',?,?,0,?,?)""",
            (payload, 'sec_topic_sending' if expired else 'sec_topic_pending', stamp, stamp))
        conn.commit()

    response = Mock()
    response.json.return_value = {'ok': True, 'result': {
        'message_id': 100, 'chat': {'id': -100123}, 'message_thread_id': 41}}
    session = Mock()
    session.post.return_value = response
    monkeypatch.setattr(stock_scanner.requests, 'Session', lambda: session)
    assert scanner_engine.process_telegram_outbox()['sent'] == int(not expired)
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert session.post.call_count == int(not expired)
    with get_db_connection() as conn:
        row = conn.execute("""SELECT status,last_error FROM scanner_telegram_outbox
            WHERE dedupe_key='sec-activity:test'""").fetchone()
        assert row['status'] == ('failed' if expired else 'sent')
        assert row['last_error'] == ('sec_activity_delivery_unknown_manual_review' if expired else None)
