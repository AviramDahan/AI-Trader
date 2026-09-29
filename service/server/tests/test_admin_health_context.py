import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from admin_health_context import snapshot, incident, summary

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
