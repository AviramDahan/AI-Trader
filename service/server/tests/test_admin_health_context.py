import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from admin_health_context import snapshot, incident, summary, health_message

NOW=datetime(2026,9,30,tzinfo=timezone.utc)


def test_allowlisted_diagnostics_no_raw_secret_or_url():
    row={'status':'error','last_attempt_at':NOW.isoformat(),
         'last_success_at':(NOW-timedelta(minutes=2)).isoformat(),
         'detail':'NVDA:stale_or_missing_bars ReadTimeout https://secret.example?token=SECRET bot-token=SECRET'}
    data=snapshot(row,NOW)
    assert data['last_success_at_age_seconds']==120
    assert data['stale_tickers']==['NVDA']
    assert data['reason_codes']==['ReadTimeout','stale_or_missing_bars']
    assert 'SECRET' not in json.dumps(data)
    assert 'https' not in summary({'monitor':data})


def test_incident_failure_recovery_once_and_retained_context():
    state,change=incident(None,True,{'monitor':snapshot({'status':'error'},NOW)},NOW)
    assert change=='failure' and state['generation']==1
    failure=state['last_failure']
    state,change=incident(state,True,{},NOW)
    assert change is None and state['generation']==1
    state,change=incident(state,False,{},NOW)
    assert change=='recovery' and state['last_failure']==failure
    state,change=incident(state,False,{},NOW)
    assert change is None
    state,change=incident(state,True,{},NOW)
    assert change=='failure' and state['generation']==2


def test_invalid_diagnostic_dates_not_forwarded():
    data=snapshot({'status':'SECRET','last_success_at':'SECRET','detail':'SECRET'},NOW)
    assert data=={'status':'unknown','reason_codes':[],'stale_tickers':[]}


def test_backup_recovery_clear_success_once_not_every_hour():
    failed = {'backup': snapshot({'status': 'error'}, NOW)}
    state, change = incident(None, True, failed, NOW)
    assert change == 'failure'
    success_at = NOW + timedelta(minutes=1)
    observed = success_at + timedelta(seconds=15)
    context = {'backup': snapshot({'status': 'ok', 'last_success_at': success_at.isoformat()}, observed)}
    state, change = incident(state, False, context, observed)
    assert change == 'recovery'
    message = health_message('backup', change, context, state)
    assert '✅ הגיבוי הצליח לאחר התקלה' in message
    assert 'נשמר בהצלחה ביעד הגיבוי המרוחק' in message
    assert '30/09/2026 03:01:00 (שעון ישראל)' in message
    assert 'אין צורך בפעולה כרגע' in message
    assert 'מסלול חדשות' not in message
    from admin_messages import timestamped
    delivered = timestamped(message, observed.isoformat())
    assert delivered.endswith('Timestamp: 30/09/2026 03:01 (Israel)')
    for minutes in (2, 60, 120):
        state, change = incident(state, False, context, NOW + timedelta(minutes=minutes))
        assert change is None


def test_backup_recovery_does_not_claim_stale_missing_or_future_success():
    state = {'last_failure': {'at': NOW.isoformat()},
             'recovered_at': (NOW + timedelta(minutes=1)).isoformat()}
    for stamp in (None, 'invalid', NOW.replace(tzinfo=None).isoformat(),
                  (NOW-timedelta(hours=1)).isoformat(), (NOW+timedelta(hours=1)).isoformat()):
        context = {'backup': snapshot({'status': 'ok', 'last_success_at': stamp}, NOW)}
        message = health_message('backup', 'recovery', context, state)
        assert '✅' not in message
        assert 'לא אומתה מאז התקלה' in message


def test_other_services_and_backup_failure_unchanged():
    context = {'backup': snapshot({'status': 'error'}, NOW)}
    assert health_message('backup', 'failure', context, {}) == 'AI-Trader Admin\nתקלה ברכיב: backup\n'+summary(context)
    context = {'monitor': snapshot({'status': 'ok'}, NOW)}
    assert health_message('monitor', 'recovery', context, {}) == ('AI-Trader Admin\nהשירות התאושש: monitor\n'+summary(context)+'\nהתאוששות שירות אינה מפעילה מחדש מסלול חדשות שנעצר בבדיקת בטיחות.')


def test_health_loop_enqueues_one_backup_recovery_to_private_queue(monkeypatch):
    from unittest.mock import MagicMock, Mock
    import ai_operations as ops
    row = {'component': 'backup', 'status': 'error', 'last_attempt_at': NOW.isoformat(),
           'last_success_at': (NOW-timedelta(hours=1)).isoformat(), 'detail': ''}
    saved = {}
    now = [NOW]
    class Clock(datetime):
        @staticmethod
        def now(tz): return now[0]
    def execute(sql, params=()):
        result = MagicMock()
        if sql.startswith('SELECT component'):
            result.fetchall.return_value = [dict(row)]
        elif sql.startswith('SELECT value_json'):
            result.fetchone.return_value = {'value_json': saved['value']} if saved else None
        elif sql.startswith('INSERT INTO scanner_settings'):
            saved['value'] = params[1]
        else:
            raise AssertionError(sql)
        return result
    db = MagicMock()
    db.__enter__.return_value.execute.side_effect = execute
    monkeypatch.setattr('database.get_db_connection', lambda: db)
    monkeypatch.setattr(ops, 'datetime', Clock)
    queue = Mock()
    monkeypatch.setattr(ops, 'enqueue', queue)
    ops.health()
    ops.health()
    now[0] = NOW + timedelta(minutes=1)
    row.update(status='ok', last_attempt_at=now[0].isoformat(), last_success_at=now[0].isoformat())
    ops.health()
    ops.health()
    now[0] += timedelta(hours=1)
    row.update(last_attempt_at=now[0].isoformat(), last_success_at=now[0].isoformat())
    ops.health()
    assert [c.args[0] for c in queue.call_args_list] == ['health:backup:1', 'health_recovered:backup:1']
    assert '✅ הגיבוי הצליח לאחר התקלה' in queue.call_args_list[1].args[1]


def health_driver(monkeypatch, row, saved=None):
    """Exercise the actual health loop with isolated state and no delivery."""
    from unittest.mock import MagicMock, Mock
    import ai_operations as ops
    state = {'value': json.dumps(saved)} if saved else {}
    class Clock(datetime):
        @staticmethod
        def now(tz): return NOW
    def execute(sql, params=()):
        result = MagicMock()
        if sql.startswith('SELECT component'):
            result.fetchall.return_value = [dict(row)]
        elif sql.startswith('SELECT value_json'):
            result.fetchone.return_value = {'value_json': state['value']} if state else None
        elif sql.startswith('INSERT INTO scanner_settings'):
            state['value'] = params[1]
        else:
            raise AssertionError(sql)
        return result
    db = MagicMock()
    db.__enter__.return_value.execute.side_effect = execute
    monkeypatch.setattr('database.get_db_connection', lambda: db)
    monkeypatch.setattr(ops, 'datetime', Clock)
    queue = Mock()
    monkeypatch.setattr(ops, 'enqueue', queue)
    return ops.health, queue, state


def test_on_demand_ai_idle_age_is_not_a_service_failure(monkeypatch):
    row = dict(component='ollama', status='ok', detail='Reviewed TEST',
               last_attempt_at=(NOW-timedelta(days=3)).isoformat(),
               last_success_at=(NOW-timedelta(days=3)).isoformat())
    check, queue, state = health_driver(monkeypatch, row)
    check(); check()
    queue.assert_not_called()
    assert not json.loads(state['value'])['active']


def test_on_demand_ai_explicit_failure_still_alerts_and_real_success_recovers(monkeypatch):
    row = dict(component='ollama', status='error', detail='ReadTimeout',
               last_attempt_at=(NOW-timedelta(days=2)).isoformat(),
               last_success_at=(NOW-timedelta(days=3)).isoformat())
    check, queue, _ = health_driver(monkeypatch, row)
    check(); check()
    assert queue.call_count == 1 and queue.call_args.args[0] == 'health:ollama:1'
    row.update(status='ok', last_attempt_at=NOW.isoformat(), last_success_at=NOW.isoformat())
    check(); check()
    assert queue.call_count == 2
    assert 'השירות התאושש' in queue.call_args.args[1]


def test_existing_idle_ai_alarm_clears_once_without_claiming_new_call(monkeypatch):
    row = dict(component='ollama', status='ok', detail='Reviewed TEST',
               last_attempt_at=(NOW-timedelta(days=3)).isoformat(),
               last_success_at=(NOW-timedelta(days=3)).isoformat())
    previous = dict(active=True, generation=4,
                    last_failure={'at': (NOW-timedelta(hours=1)).isoformat(),
                                  'context': {'ollama': {'status': 'ok'}}})
    check, queue, state = health_driver(monkeypatch, row, previous)
    check(); check()
    assert queue.call_count == 1
    assert queue.call_args.args[0] == 'health_recovered:ollama:4'
    assert 'התראת חוסר הפעילות' in queue.call_args.args[1]
    assert 'אין כאן הוכחה לקריאת AI חדשה' in queue.call_args.args[1]
    assert 'השירות התאושש' not in queue.call_args.args[1]
    assert not json.loads(state['value'])['active']


def test_ai_unknown_failure_context_does_not_claim_inactivity_or_new_success():
    context = {'ollama': snapshot({'status': 'ok'}, NOW)}
    previous = {'last_failure': {'at': NOW.isoformat(), 'context': {}},
                'recovered_at': NOW.isoformat()}
    message = health_message('ollama', 'recovery', context, previous)
    assert 'הצלחת קריאה חדשה לא אומתה' in message
    assert 'התראת חוסר הפעילות' not in message
    assert 'השירות התאושש' not in message


def test_periodic_monitor_staleness_detection_unchanged(monkeypatch):
    row = dict(component='monitor', status='ok', detail='',
               last_attempt_at=(NOW-timedelta(seconds=901)).isoformat(),
               last_success_at=(NOW-timedelta(seconds=901)).isoformat())
    check, queue, _ = health_driver(monkeypatch, row)
    check()
    assert queue.call_args.args[0] == 'health:monitor:1'
