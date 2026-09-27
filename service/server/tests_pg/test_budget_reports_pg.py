from datetime import datetime, timezone
from unittest.mock import Mock

import budget_reports as reports
import ai_operations
import database


def test_budget_schedule_command_restart_private_delivery(pg, monkeypatch):
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID', '123')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '456')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-only')
    now = datetime(2026, 9, 27, 9, tzinfo=timezone.utc)
    updates = [{'update_id': 1, 'message': {'chat': {'id': 123}, 'text': '/budget',
                'date': int(now.timestamp()), 'from': {'is_bot': False}}},
               {'update_id': 2, 'message': {'chat': {'id': 456}, 'text': '/budget',
                'date': int(now.timestamp())}}]
    for _ in range(2):
        reports.schedule_reports(now)
        reports.handle_updates(updates, '123', 'OurBot', now)
    response = Mock(); response.json.return_value = {'ok': True, 'result': {'message_id': 10}}
    post = Mock(return_value=response); monkeypatch.setattr(ai_operations.requests, 'post', post)
    for _ in range(3):
        ai_operations.send_one()
    assert post.call_count == 2
    assert all(call.kwargs['json']['chat_id'] == '123' for call in post.call_args_list)
    with database.get_db_connection() as conn:
        assert reports.read_setting(conn, reports.POLL_KEY)['offset'] == 3
        assert conn.execute("SELECT count(*) n FROM admin_alerts WHERE status='sent'").fetchone()['n'] == 2
        assert conn.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n'] == 0
