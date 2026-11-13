"""Synthetic, isolated funnel telemetry; never contacts providers or Telegram."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from news_events.store import Store
from news_events.funnel_health import snapshot, projection, summary

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / 'funnel.sqlite'
    def connect():
        c = sqlite3.connect(path); c.row_factory = sqlite3.Row
        return c
    Store(connect, sandbox=True).install()
    c = connect()
    c.execute('CREATE TABLE scanner_telegram_outbox(dedupe_key TEXT PRIMARY KEY,event_type TEXT,status TEXT,sent_at TEXT)')
    c.execute('CREATE TABLE ne_outbox(dedupe_key TEXT PRIMARY KEY,event_id TEXT,version TEXT,topic TEXT,epoch INTEGER)')
    yield c
    c.close()


def event(c, key, status='blocked', reason='identity_unverified', age=2, version='v1'):
    at = (NOW - timedelta(hours=age)).isoformat()
    c.execute('INSERT INTO ne_events VALUES(?,?,?,?,?,?,?)', (str(key),'{}',version,status,reason,at,at))


def analysis(c, key, status='done', version='v1'):
    c.execute('INSERT INTO ne_analysis VALUES(?,?,?,?,?,?,?,?,?)',
              (str(key),version,status,'{}',None,NOW.isoformat(),NOW.isoformat(),0,'synthetic'))


def delivery(c, key, version='v1', sent=True):
    key = str(key)
    c.execute('INSERT INTO ne_delivery VALUES(?,?,?,?,?,?)',
              (key,version,'market_news','[]','outbox',NOW.isoformat()))
    c.execute('INSERT INTO ne_outbox VALUES(?,?,?,?,?)', ('notice:'+key,key,version,'market_news',1))
    c.execute('INSERT INTO scanner_telegram_outbox VALUES(?,?,?,?)',
              ('notice:'+key,'market_news','sent' if sent else 'pending',(NOW-timedelta(seconds=1)).isoformat() if sent else None))


def test_large_collection_empty_queue_is_review_not_success(conn):
    key = 0
    for status,reason,n in [('blocked','identity_unverified',360),('blocked','unsupported_or_noise',41),
                          ('blocked','insufficient_information',27),('blocked','stale_or_future',4),
                          ('analyzed','irrelevant',20),('analyzed','low_importance',4),
                          ('quality_failed','fixture_quality_reason',4)]:
        for _ in range(n):
            event(conn,key,status,reason)
            if status in ('analyzed','quality_failed'): analysis(conn,key,'done' if status=='analyzed' else 'failed')
            key += 1
    # A sent notice in the same clock window is NOT a new-cohort success.
    event(conn,'older','analyzed',None,age=8); analysis(conn,'older'); delivery(conn,'older')
    data = snapshot(conn,NOW)
    assert data['status'] == 'review_required'
    assert data['counts']['events'] == 460
    assert data['counts']['identity_unverified'] == 360
    assert data['counts']['current_analysis_done'] == 24
    assert data['counts']['current_analysis_failed'] == 4
    assert data['counts']['routed_events'] == data['counts']['cohort_sent_events'] == 0
    assert data['counts']['sent_window_notices'] == 1
    assert data['advisories'] == ['high_preanalysis_loss_no_routing']
    assert 'נדרשת בדיקה' in summary(data)


def test_no_input_is_not_zero_success_or_a_quota(conn):
    data = snapshot(conn,NOW)
    assert data['status'] == 'no_input' and data['advisories'] == []
    assert data['preanalysis_loss_ratio'] is None
    assert data['counts']['events'] == 0


def test_current_version_only_and_future_old_events_excluded(conn):
    event(conn,'revised','pending',None,version='v2'); analysis(conn,'revised',version='v1')
    delivery(conn,'revised',version='v1')
    event(conn,'future',age=-1); event(conn,'old',age=8)
    data = snapshot(conn,NOW)
    assert data['counts']['events'] == 1
    assert data['counts']['current_analysis_done'] == 0
    assert data['counts']['routed_events'] == data['counts']['cohort_sent_events'] == 0
    assert data['status'] == 'observed'


def test_new_activation_does_not_count_older_cohort(conn):
    event(conn,'old',age=2); event(conn,'new',age=.25)
    data = snapshot(conn,NOW,not_before=NOW-timedelta(hours=1))
    assert data['counts']['events'] == 1
    assert data['window_start'] == (NOW-timedelta(hours=1)).isoformat()


def test_quiet_factual_market_is_investigation_not_automatic_failure(conn):
    for i in range(50): event(conn,i,'analyzed','irrelevant',age=4); analysis(conn,i)
    data = snapshot(conn,NOW)
    assert data['status'] == 'review_required'
    assert data['advisories'] == ['no_publication_with_input']
    assert 'not_a_bug_or_publication_quota' in data['interpretation']


def test_routed_notice_does_not_mean_it_was_sent(conn):
    event(conn,'ready','analyzed',None); analysis(conn,'ready'); delivery(conn,'ready',sent=False)
    data = snapshot(conn,NOW)
    assert data['counts']['routed_events'] == 1
    assert data['counts']['cohort_sent_events'] == data['counts']['sent_window_notices'] == 0
    assert data['status'] == 'observed'


def test_missing_tables_or_bad_clock_are_unknown(conn):
    conn.execute('DROP TABLE ne_analysis')
    assert snapshot(conn,NOW)['status'] == 'unknown'
    assert snapshot(conn,NOW)['counts'] is None
    assert snapshot(conn,NOW.replace(tzinfo=None))['status'] == 'unknown'


def test_public_projection_rejects_stale_future_or_malformed_without_secrets(conn):
    data = snapshot(conn,NOW)
    assert projection(data,NOW)['status'] == 'no_input'
    assert projection(data,NOW+timedelta(seconds=181))['status'] == 'unknown'
    assert projection(data,NOW-timedelta(seconds=6))['status'] == 'unknown'
    assert projection({'status':'review_required','password':'fixture-private'},NOW)['status'] == 'unknown'
    assert 'fixture-private' not in json.dumps(projection(data,NOW))


def test_healthy_provider_wording_is_not_publication_success():
    from news_events.watch import coverage_summary
    text = coverage_summary([{'provider':'investing','status':'ok'}],{})
    assert 'הצינור תקין' not in text
    assert 'חיבורי המקורות' in text


def test_private_admin_projection_observes_funnel_without_hiding_real_failure(conn):
    from admin_system_status import news_funnel
    for i in range(50): event(conn,i,age=2)
    data = snapshot(conn,NOW)
    node = dict(state='healthy',reason='recent_completed_check',metrics={})
    news_funnel(node,{'funnel':data},NOW)
    assert node['state']=='degraded' and node['reason']=='news_funnel_review_required'
    assert node['metrics']['news_identity_blocked_6h']==50
    node.update(state='failed',reason='lease_missing')
    news_funnel(node,{'funnel':data},NOW)
    assert node['state']=='failed' and node['reason']=='lease_missing'
    node.update(state='healthy')
    news_funnel(node,{'funnel':data},NOW+timedelta(minutes=4))
    assert node['state']=='unknown'
    assert node['metrics']['news_events_6h'] is None
    assert node['metrics']['news_funnel_review_required'] is None
