import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests
import budget_reports as reports
import ai_operations


NOW = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)  # 12:00 Israel


@pytest.fixture
def budget_db(monkeypatch):
    import database
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE scanner_settings(key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);
        CREATE TABLE admin_alerts(dedupe_key TEXT PRIMARY KEY,message TEXT,created_at TEXT);
    ''')
    @contextmanager
    def connection():
        with conn:
            yield conn
    monkeypatch.setattr(database, 'get_db_connection', connection)
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID', '123')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '456')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-only')
    yield conn
    conn.close()


def command(ident=100, chat=123, text='/budget', age=0):
    return dict(update_id=ident, message=dict(chat=dict(id=chat), text=text,
                date=int(NOW.timestamp())-age, **{'from': {'is_bot': False}}))


@pytest.mark.parametrize('hour', [8, 12, 20, 23])
@pytest.mark.parametrize('month,offset', [(9, 3), (12, 2)])
def test_four_israel_slots_with_dst(hour, month, offset):
    at = datetime(2026, month, 27, hour-offset, tzinfo=timezone.utc)
    assert reports.scheduled_slot(at) == f'2026-{month:02d}-27:{hour}'


def test_schedule_persistent_dedupe_restart_and_no_old_replay(budget_db):
    for at in (NOW, NOW+timedelta(seconds=30), NOW+timedelta(minutes=59)):
        reports.schedule_reports(at)
    reports.schedule_reports(NOW+timedelta(hours=1))
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 1
    reports.schedule_reports(NOW+timedelta(days=1))
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 2


def test_private_command_atomic_offset_and_restart_dedupe(budget_db):
    updates = [command(), command(101, chat=456), command(102, text='/budget@OtherBot'),
               command(103, age=3601), command(104, text='/budget@OurBot')]
    reports.handle_updates(updates, '123', 'OurBot', NOW)
    reports.handle_updates(updates, '123', 'OurBot', NOW)
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 2
    assert reports.read_setting(budget_db, reports.POLL_KEY)['offset'] == 105
    assert budget_db.execute('SELECT message FROM admin_alerts LIMIT 1').fetchone()[0].endswith(
        'Timestamp: 27/09/2026 12:00 (Israel)')


def test_command_and_offset_rollback_together(budget_db, monkeypatch):
    original = reports.write_setting
    monkeypatch.setattr(reports, 'write_setting', Mock(side_effect=RuntimeError('db_failed')))
    with pytest.raises(RuntimeError):
        reports.handle_updates([command()], '123', 'OurBot', NOW)
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 0
    monkeypatch.setattr(reports, 'write_setting', original)
    reports.handle_updates([command()], '123', 'OurBot', NOW)
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 1


def test_bot_and_edited_command_ignored():
    update = command()
    update['message']['from']['is_bot'] = True
    assert not reports.is_budget_command(update, '123', 'OurBot', NOW)
    assert not reports.is_budget_command({'edited_message': command()['message']}, '123', 'OurBot', NOW)


@pytest.mark.parametrize('chat', ['', '456'])
def test_no_missing_admin_or_public_fallback(budget_db, monkeypatch, chat):
    monkeypatch.setenv('TELEGRAM_ADMIN_CHAT_ID', chat)
    get = Mock(); monkeypatch.setattr(reports.requests, 'get', get)
    reports.schedule_reports(NOW); reports.poll_commands(NOW)
    get.assert_not_called()
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 0


def test_report_separates_credits_tasks_discrepancy_and_stale_data(budget_db):
    state = ai_operations.calculate([
        {'task': 'news_analysis', 'actual_cost': 2},
        {'task': 'final_stock_review', 'actual_cost': 1},
        {'task': 'retry_repair', 'actual_cost': .5}], {'usage_monthly': 4},
        NOW-timedelta(hours=2), credit_data={'credit_balance': .8})
    reports.write_setting(budget_db, 'ai_cost_reconciliation', state, NOW)
    message = reports.report(budget_db, NOW)
    for text in ('AI budget: $4.00 / $25', 'News: $2.00', 'Final stock: $1.00',
                 'Retries/repairs: $0.50', 'balance: $0.80', 'remaining: $21.00',
                 'OpenRouter: $0.50', 'אין מספיק נתונים', 'אינם עדכניים'):
        assert text in message


def test_poll_retry_after_and_no_ai_calls(budget_db, monkeypatch):
    reports.write_setting(budget_db, reports.POLL_KEY, {'username': 'OurBot', 'offset': 90}, NOW)
    response = requests.Response(); response.status_code = 429
    response.headers['Retry-After'] = '600'; response._content = b'{"parameters":{"retry_after":700}}'
    get = Mock(side_effect=requests.HTTPError(response=response))
    monkeypatch.setattr(reports.requests, 'get', get)
    reports.poll_commands(NOW)
    state = reports.read_setting(budget_db, reports.POLL_KEY)
    assert state['next_at'] == NOW.timestamp()+700 and state['offset'] == 90
    reports.poll_commands(NOW+timedelta(seconds=699))
    assert get.call_count == 1
    good = Mock(); good.json.return_value = {'ok': True, 'result': [command()]}
    get.side_effect = None; get.return_value = good
    reports.poll_commands(NOW+timedelta(seconds=701))
    assert reports.read_setting(budget_db, reports.POLL_KEY)['failures'] == 0
    assert get.call_args.args[0].endswith('/getUpdates')
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 1


def test_poll_conflict_slow_probe_does_not_block_scheduler(budget_db, monkeypatch):
    response = requests.Response(); response.status_code = 409
    monkeypatch.setattr(reports.requests, 'get', Mock(side_effect=requests.HTTPError(response=response)))
    reports.poll_commands(NOW)
    assert reports.read_setting(budget_db, reports.POLL_KEY)['next_at'] == NOW.timestamp()+3600
    reports.schedule_reports(NOW)
    assert budget_db.execute('SELECT count(*) FROM admin_alerts').fetchone()[0] == 1
