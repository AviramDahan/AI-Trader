"""Decision invariance + isolated durable research evidence. No external requests."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database
import final_ai
import scanner_engine
import single_target_policy
import stock_scanner
import target_evidence


def zone(low, high=None):
    return dict(low=low,high=high if high is not None else low,touches=1,
        pivots=[dict(price=low,date='2026-09-21',kind='swing_high',confirmed_at='2026-09-23T20:05:00Z')])


def candidate(zones=None):
    return dict(ticker='TEST',company='Synthetic',technical_direction='BUY',atr=1,price_as_of='2026-09-25',
                single_target_source=dict(atr=1,data_as_of='2026-09-25',zones=zones or [zone(98,98.4),zone(104.65,105)]))


class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2026,9,28,14,0,tzinfo=timezone.utc)


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','ollama')
    monkeypatch.setenv('BUILD_SHA','synthetic-build')
    monkeypatch.setattr(stock_scanner,'datetime',Clock)
    monkeypatch.setattr(scanner_engine,'lifecycle_settings',lambda:{'active_strategy':'single'})
    monkeypatch.setattr('single_target_activation.enabled',lambda:True)
    monkeypatch.setattr(final_ai.requests,'post',Mock(side_effect=AssertionError('No network')))
    trace=final_ai.new_trace('synthetic-scan','TEST',1)
    token=final_ai.TRACE.set(trace)
    yield trace
    final_ai.TRACE.reset(token)


@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DATABASE_URL','')
    monkeypatch.setattr(database,'_SQLITE_DB_PATH',str(tmp_path/'isolated.db'))
    database.init_database()


@pytest.mark.parametrize('entry',[95,97.7,98,98.5,99,100,100.001,100.01,104.5,104.6,105,110])
def test_exact_policy_return_or_error_unchanged(context,entry):
    c=candidate();before=copy.deepcopy(c);s=c['single_target_source']
    try:
        expected=single_target_policy.build(entry,s['atr'],s['zones'],s['data_as_of'],Clock.now().isoformat())
    except ValueError as e:
        with pytest.raises(ValueError) as actual:
            stock_scanner._candidate_target_plan(c,'BUY',entry,{'min_risk_reward':2},quote_at='2026-09-28T13:59:00Z')
        assert str(actual.value)==str(e)
    else:
        assert stock_scanner._candidate_target_plan(c,'BUY',entry,{'min_risk_reward':2},quote_at='2026-09-28T13:59:00Z')==expected
    assert c==before
    r=context['target_checks']['pre_ai']
    assert r['quote']['price']==entry and r['quote']['as_of']=='2026-09-28T13:59:00Z'
    assert r['build_sha']=='synthetic-build' and r['policy_version']=='single_target_v2'
    final_ai.requests.post.assert_not_called()


@pytest.mark.parametrize('resistance,detail',[(100.1,'target_buffer_reaches_entry'),(100.154,'target_rounds_to_or_below_entry')])
def test_invalid_levels_explain_buffer_vs_rounding(context,resistance,detail):
    with pytest.raises(ValueError,match='^invalid_rounded_levels$'):
        stock_scanner._candidate_target_plan(candidate([zone(98,98.4),zone(resistance,101)]),'BUY',100,{'min_risk_reward':2})
    r=context['target_checks']['pre_ai']
    assert detail in r['rejection_detail']
    assert r['rejection_reason']=='invalid_rounded_levels'


def test_post_ai_price_change_is_separate_and_original_evidence_immutable(context):
    c=candidate()
    stock_scanner._candidate_target_plan(c,'BUY',100,{'min_risk_reward':2},quote_at='2026-09-28T13:59:00Z')
    with pytest.raises(ValueError,match='2r'):
        stock_scanner._candidate_target_plan(c,'BUY',100.01,{'min_risk_reward':2},quote_at='2026-09-28T14:00:00Z',phase='post_ai')
    c['single_target_source']['zones'][0]['low']=1
    assert context['target_checks']['pre_ai']['outcome']=='PASS'
    assert context['target_checks']['post_ai']['outcome']=='REJECT'
    assert context['target_checks']['pre_ai']['source_inputs']['zones'][0]['low']==98


def test_failed_diagnostic_math_does_not_change_accepted_plan(context,monkeypatch):
    monkeypatch.setattr(target_evidence,'_geometry',Mock(side_effect=RuntimeError('synthetic')))
    assert stock_scanner._candidate_target_plan(candidate(),'BUY',100,{'min_risk_reward':2})['rr']==[2]
    assert not context.get('target_checks')
    assert context['target_evidence_attempted']


def test_payload_limit_reports_gap_not_fake_full_evidence(context,monkeypatch):
    monkeypatch.setattr(target_evidence,'MAX_BYTES',100)
    stock_scanner._candidate_target_plan(candidate(),'BUY',100,{'min_risk_reward':2})
    r=context['target_checks']['pre_ai']
    assert r['evidence_gap']=='payload_exceeds_64k_no_full_replay'
    assert 'source_inputs' not in r and r['source_inputs_sha256']


def test_no_raw_news_secrets_or_ai_payload_changes(context):
    c=candidate()|{'news':[{'title':'private story'}],'token':'DO-NOT-SAVE'}
    stock_scanner._candidate_target_plan(c,'BUY',100,{'min_risk_reward':2})
    value=json.dumps(context['target_checks'])
    assert 'private story' not in value and 'DO-NOT-SAVE' not in value
    assert 'target_checks' not in c


def test_sqlite_repeat_persist_restart_link_and_dashboard_counts(db,context):
    stock_scanner._candidate_target_plan(candidate(),'BUY',100,{'min_risk_reward':2})
    final_ai.persist(context);final_ai.persist(copy.deepcopy(context))
    database.init_database()
    with database.get_db_connection() as c:
        assert c.execute("SELECT count(*) FROM scanner_candidates WHERE stage='target_check'").fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM scanner_candidates WHERE status='rejected'").fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM scanner_signals').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM scanner_orders').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM scanner_telegram_outbox').fetchone()[0]==0
        path=Path(__file__).resolve().parents[3]/'scripts/target_evidence_report.py'
        spec=importlib.util.spec_from_file_location('target_report',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        r=mod.report(c,'2020-01-01T00:00:00Z')
        assert r['observations']==1 and r['records'][0]['signal_links']==[]


def test_sqlite_journal_failure_does_not_rollback_ai_telemetry(db,context):
    stock_scanner._candidate_target_plan(candidate(),'BUY',100,{'min_risk_reward':2})
    with database.get_db_connection() as c:
        c.execute("CREATE TRIGGER fail_evidence BEFORE INSERT ON scanner_candidates BEGIN SELECT RAISE(ABORT,'test'); END")
        c.commit()
    final_ai.persist(context)
    with database.get_db_connection() as c:
        assert c.execute('SELECT count(*) FROM scanner_final_ai_telemetry').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM scanner_candidates').fetchone()[0]==0
