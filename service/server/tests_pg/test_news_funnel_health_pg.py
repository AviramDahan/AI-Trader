"""Actual PG transaction/aggregate/watch proof in disposable test schemas only."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

NOW = datetime(2026,10,23,12,tzinfo=timezone.utc)


def seed(c, count=50):
    stamp=(NOW-timedelta(hours=4)).isoformat()
    for i in range(count):
        c.execute('INSERT INTO ne_events VALUES(?,?,?,?,?,?,?)',
                  (f'funnel-{i}','{}','new','blocked','identity_unverified',stamp,stamp))
    # Old analysis and route records must not certify the current version.
    c.execute('INSERT INTO ne_analysis VALUES(?,?,?,?,?,?,?,?,?)',
              ('funnel-0','old','done','{}',None,stamp,stamp,0,'synthetic'))
    c.execute('INSERT INTO ne_delivery VALUES(?,?,?,?,?,?)',
              ('funnel-0','old','market_news','[]','outbox',stamp))


def test_funnel_real_pg_is_readonly_current_version_and_numeric_safe(pg):
    from database import get_db_connection
    from news_events.funnel_health import snapshot
    with get_db_connection() as c: seed(c)
    with get_db_connection() as c:
        observed=snapshot(c,NOW)
        assert observed['status']=='review_required'
        assert observed['counts']['events']==50
        assert observed['counts']['current_analysis_done']==0
        assert observed['counts']['routed_events']==0
        assert c.execute('SHOW transaction_read_only').fetchone()[0]=='on'
        assert c.execute('SHOW transaction_isolation').fetchone()[0]=='repeatable read'
        json.dumps(observed,allow_nan=False)
        with pytest.raises(Exception):
            c.execute("UPDATE ne_events SET status='pending'")
    with get_db_connection() as c:
        assert c.execute("SELECT count(*) n FROM ne_events WHERE status='blocked'").fetchone()['n']==50


def test_funnel_real_watch_and_private_projection_never_failback_or_write_trades(pg,monkeypatch):
    from database import get_db_connection
    from news_events import watch
    import ai_operations
    import admin_system_status as ops
    with get_db_connection() as c:
        seed(c)
        c.execute("UPDATE ne_control SET mode='canonical',not_before=? WHERE id=1",
                  ((NOW-timedelta(hours=6)).isoformat(),))
        c.execute('INSERT INTO scanner_service_status VALUES(?,?,?,?,?)',
                  ('news_feed','ok',NOW.isoformat(),NOW.isoformat(),'synthetic'))
    monkeypatch.setattr(watch,'fail_back',Mock(side_effect=AssertionError('No recall-triggered safety failback')))
    monkeypatch.setattr(ai_operations,'enqueue',Mock())
    result=watch.check(NOW)
    assert result['alarms']==[]
    assert result['funnel']['status']=='review_required'
    watch.fail_back.assert_not_called()
    key,text=ai_operations.enqueue.call_args.args
    assert key==watch.summary_key(NOW) and 'נדרשת בדיקה' in text
    with get_db_connection() as c:
        saved=json.loads(c.execute("SELECT value_json FROM scanner_settings WHERE key='news_canonical_health'").fetchone()['value_json'])
        saved['outcomes']={'synthetic_private_history':'X'*1100000}
        c.execute("UPDATE scanner_settings SET value_json=? WHERE key='news_canonical_health'",(json.dumps(saved),))
    with get_db_connection() as c:
        c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        value=ops.build(c,NOW)
        feed=next(node for node in value['nodes'] if node['id']=='news_feed')
        assert feed['metrics']['news_events_6h']==50
        assert feed['metrics']['news_funnel_review_required'] is True
        assert feed['reason']!='recent_completed_check'
        assert 'synthetic_private_history' not in json.dumps(value)
        assert len(json.dumps(value))<18000
        for table in ('scanner_orders','scanner_trades','scanner_fills','scanner_telegram_outbox','ai_call_usage'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0
