"""Existing schema only; disposable PG fixtures, never production."""
import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import database
import final_ai
import scanner_engine
import target_evidence


def trace(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','ollama')
    t=final_ai.new_trace('synthetic-evidence','TEST',1)
    t['target_checks']={'pre_ai':dict(evidence_version=1,observation_id=t['id']+':pre_ai',
        scan_id=t['scan_id'],ticker='TEST',review_id=t['id'],company='Synthetic',phase='pre_ai',
        observed_at='2026-09-28T14:00:00Z',outcome='REJECT',rejection_reason='no_forward_zone',
        quote=dict(price=100,as_of='2026-09-28T13:59:00Z',source='yahoo_1m_close'))}
    return t


def test_pg_concurrent_idempotency_restart_no_trading_side_effects(pg,monkeypatch):
    t=trace(monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(final_ai.persist,[copy.deepcopy(t) for _ in range(3)]))
    final_ai.persist(copy.deepcopy(t))  # reconstructed caller / new connection
    with database.get_db_connection() as c:
        assert c.execute("SELECT count(*) n FROM scanner_candidates WHERE stage='target_check'").fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM scanner_final_ai_telemetry').fetchone()['n']==1
        assert c.execute("SELECT count(*) n FROM scanner_candidates WHERE status='rejected'").fetchone()['n']==0
        for table in ('scanner_signals','scanner_orders','scanner_fills','scanner_telegram_outbox'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0
        payload=json.loads(c.execute('SELECT metrics_json FROM scanner_candidates').fetchone()['metrics_json'])
        assert payload['quote']['as_of']=='2026-09-28T13:59:00Z'


def test_pg_partial_evidence_failure_uses_savepoint_only(pg,monkeypatch):
    t=trace(monkeypatch)
    t['target_checks']['post_ai']=dict(t['target_checks']['pre_ai'],observation_id=t['id']+':post_ai',
                                      phase='post_ai',observed_at=None)
    # NOT NULL failure after the first insert: no partial journal and telemetry survives.
    final_ai.persist(t)
    with database.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM scanner_final_ai_telemetry').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM scanner_candidates').fetchone()['n']==0
    t['target_checks']['post_ai']['observed_at']='2026-09-28T14:01:00Z'
    final_ai.persist(t)
    with database.get_db_connection() as c:
        assert c.execute('SELECT count(*) n FROM scanner_candidates').fetchone()['n']==2


def test_pg_existing_candidate_counts_and_schema_unchanged(pg,monkeypatch):
    scanner_engine.record_candidates('original',[dict(ticker='ORIGINAL',company='Synthetic')],
                                     [dict(ticker='ORIGINAL',reason='pre_no_forward_zone')])
    final_ai.persist(trace(monkeypatch))
    with database.get_db_connection() as c:
        assert c.execute("SELECT count(*) n FROM scanner_candidates WHERE stage='technical'").fetchone()['n']==1
        assert c.execute("SELECT count(*) n FROM scanner_candidates WHERE status='rejected'").fetchone()['n']==1
        assert c.execute('SELECT max(version) n FROM schema_migrations').fetchone()['n']==7


def test_pg_signal_order_links_and_trading_backup_unchanged(pg,monkeypatch):
    from test_recovery_holds import initialize_empty
    import recovery_state
    from single_target_policy import build
    # Opt in only inside this isolated test; the production creation gate stays intact.
    monkeypatch.setenv('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED','true')
    initialize_empty()
    zs=[dict(low=x,high=x,touches=1,pivots=[dict(price=x,date='2026-09-21',
        kind='swing_high',confirmed_at='2026-09-23T20:05:00Z')]) for x in (98,105)]
    p=build(100,1,zs,'2026-09-25','2026-09-28T14:00:00Z')
    s=dict(ticker='TEST',company='Synthetic',action='BUY',entry=100,stop_loss=p['stop'],
           target_plan=p,confidence=.9,time_horizon='days',reason='synthetic',relevant_news=[])
    with patch.object(scanner_engine,'now_z',return_value='2026-09-28T14:00:00Z'):
        signal=scanner_engine.record_signal(s,{}, {}, {}, 'synthetic-evidence')
    # Ordinary pending orders are deliberately outside active recovery snapshots.
    # A synthetic blocked V2 order exercises the existing format-3 hold contract.
    with database.get_db_connection() as c:
        c.execute("UPDATE scanner_orders SET status='recovery_uncertain' WHERE signal_id=?",(signal['id'],))
        c.execute("UPDATE scanner_signals SET status='RECOVERY_UNCERTAIN' WHERE id=?",(signal['id'],))
    before=recovery_state.export_postgres(pg)
    final_ai.persist(trace(monkeypatch))
    after=recovery_state.export_postgres(pg)
    assert before['tables']==after['tables']
    assert before['recovery_format']==after['recovery_format']==3
    path=Path(__file__).resolve().parents[3]/'scripts/target_evidence_report.py'
    spec=importlib.util.spec_from_file_location('evidence_report_pg',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION READ ONLY')
        r=mod.report(c,'2026-09-28T00:00:00Z')
        links=r['records'][0]['signal_links']
        assert links[0]['signal_id']==signal['id']
        assert links[0]['saved_policy_version']=='single_target_v2'
        assert len(links[0]['orders'])==1
        assert links[0]['orders'][0]['status']=='recovery_uncertain'
