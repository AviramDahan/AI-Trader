import json
import pytest
import database
from entry_repair_audit import collect,compare
from test_single_target_v2 import zone


def test_paired_structure_never_reports_fills_or_bypasses_resistance():
    check=dict(source_inputs=dict(atr=1,zones=[zone(98,98.4)],data_as_of='2026-09-25'),
               quote=dict(price=100),decided_at='2026-10-06T14:00:00Z')
    assert compare(check,99)=='BASELINE_FAIL_NEW_PASS'
    assert compare(check,None)=='NOT_VERIFIED_MISSING_COMPLETED_HIGH'
    assert compare(check,100)=='BOTH_FAIL'
    check['source_inputs']['zones'].append(zone(102,103))
    assert compare(check,99)=='BOTH_FAIL'


def test_audit_requires_readonly_and_never_mutates(pg):
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        before=c.execute('SELECT count(*) n FROM scanner_orders').fetchone()['n']
        report=collect(c,'2026-10-01T00:00:00Z')
        assert report['new_policy_signals']==[] and report['linked_chains']==[]
        assert c.execute('SELECT count(*) n FROM scanner_orders').fetchone()['n']==before
        assert c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
    with database.get_db_connection() as c:
        with pytest.raises(AssertionError):collect(c,'2026-10-01T00:00:00Z')


def test_audit_links_frozen_source_with_actual_retained_entry(pg):
    from test_recovery_holds import initialize_empty
    from test_single_breakout_pg import seed_contract
    import scanner_engine as engine
    initialize_empty()
    sid=seed_contract('AUDIT')
    engine.process_bar('AUDIT',dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.8,close=100))
    check=dict(source_inputs=dict(atr=1,zones=[zone(98,98.4)],data_as_of='2026-09-25'),
               quote=dict(price=100),decided_at='2026-10-06T14:00:00Z',phase='pre_ai',action='BUY',
               evaluated=True,ticker='AUDIT',source_inputs_sha256='synthetic-hash',rejection_reason='no_forward_zone')
    with database.get_db_connection() as c:
        for stage,metrics in [('technical',dict(recent_high_20d=99)),('target_check',check)]:
            c.execute('INSERT INTO scanner_candidates(scan_id,ticker,stage,status,metrics_json,created_at) VALUES(?,?,?,?,?,?)',
                      ('synthetic-scan','AUDIT',stage,'observed',json.dumps(metrics),'2026-10-06T14:00:00Z'))
        c.commit()
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        report=collect(c,'2026-10-01T00:00:00Z')
        assert report['paired_structural_checks']=={'BASELINE_FAIL_NEW_PASS':1}
        assert report['unique_ticker_source_structures']==1
        chain=report['linked_chains'][0]
        assert chain['signal_id']==sid and chain['entries']==1 and chain['exits']==0
        assert report['new_policy_completed_chains']==0


def observation(conn, scan, stage, metrics, ticker='AUDIT'):
    conn.execute('''INSERT INTO scanner_candidates(scan_id,ticker,stage,status,metrics_json,created_at)
        VALUES(?,?,?,'observed',?,'2026-10-06T14:00:00Z')''',
        (scan, ticker, stage, metrics if isinstance(metrics,str) else json.dumps(metrics)))


def paired_check():
    return dict(source_inputs=dict(atr=1,zones=[zone(98,98.4)],data_as_of='2026-09-25'),
        quote=dict(price=100),decided_at='2026-10-06T14:00:00Z',phase='pre_ai',action='BUY',
        evaluated=True,ticker='AUDIT',source_inputs_sha256='synthetic-source')


def test_large_unevaluated_population_cannot_clip_valid_checks_or_repeat_scans(pg):
    with database.get_db_connection() as c:
        c.execute('''INSERT INTO scanner_candidates(scan_id,ticker,stage,status,metrics_json,created_at)
            SELECT 'background-'||g::text,'OTHER','technical','candidate','{}','2026-10-06T14:00:00Z'
            FROM generate_series(1,30000) g''')
        c.execute('''INSERT INTO scanner_candidates(scan_id,ticker,stage,status,metrics_json,created_at)
            SELECT 'closed-'||g::text,'OTHER','target_check','observed',?, '2026-10-06T14:00:00Z'
            FROM generate_series(1,2500) g''', (json.dumps(dict(phase='pre_ai',action='BUY',evaluated=False)),))
        observation(c,'real','technical',dict(recent_high_20d=99))
        observation(c,'real','technical',dict(recent_high_20d=101)) # Earliest id remains the source.
        observation(c,'real','target_check',paired_check())
        c.commit()
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c.execute("SET LOCAL statement_timeout='3s'")
        before=c.execute('SELECT count(*) n FROM scanner_candidates').fetchone()['n']
        result=collect(c,'2026-10-01T00:00:00Z')
        assert result['paired_structural_checks']=={'BASELINE_FAIL_NEW_PASS':1}
        assert result['unique_ticker_source_structures']==1 and not result['evidence_truncated']
        assert c.execute('SELECT count(*) n FROM scanner_candidates').fetchone()['n']==before


def test_malformed_json_and_missing_technical_high_are_explicit_unknown(pg):
    with database.get_db_connection() as c:
        observation(c,'broken','target_check','{invalid')
        observation(c,'scalar','target_check','[]')
        observation(c,'missing','target_check',paired_check())
        observation(c,'bad-technical','technical','[1]')
        observation(c,'bad-technical','target_check',paired_check())
        c.commit()
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        result=collect(c,'2026-10-01T00:00:00Z')
        assert result['paired_structural_checks']=={
            'NOT_VERIFIED_INVALID_OR_INCOMPLETE_EVIDENCE':3,
            'NOT_VERIFIED_MISSING_COMPLETED_HIGH':1}
        assert result['new_policy_completed_chains']==0
