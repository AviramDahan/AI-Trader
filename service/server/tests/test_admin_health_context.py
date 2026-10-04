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
