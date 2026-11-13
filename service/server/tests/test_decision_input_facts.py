import copy
import hashlib
import json
import sqlite3
from unittest.mock import Mock

import pytest

import decision_input_facts as facts
import target_evidence


def payload():
    return dict(candidate=dict(ticker='TEST', price=101., token='never export', nested={'secret': True}),
        market_context={'SPY': dict(close=500., above_ema20=True, ema20_above_ema50=False,
            return_20d_pct=-1., as_of='2026-10-19', secret='never export')},
        recent_news=[dict(title='Synthetic headline', publisher='Fixture', published_at='2026-10-20T13:00:00Z', relevance=.9)],
        review_evidence_context=dict(version='review_time_context_v1',
            completed_daily={'as_of':'2026-10-19','metrics':{'volume_ratio':.6},'current_session_volume_available':False},
            entry_quote={'price':101.,'as_of':'2026-10-20T14:00:00Z'}, intraday={'bars':[]}))


def capture(value):
    wire = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return facts.capture(value, wire, observed_at='2026-10-20T14:00:01Z'), wire


def test_actual_wire_and_sanitized_projection_have_distinct_verified_scopes():
    p=payload(); saved,wire=capture(p)
    assert saved['initial_user_content_utf8_sha256']==hashlib.sha256(wire.encode()).hexdigest()
    assert saved['sanitized_projection_sha256']==facts.digest(saved['facts'])
    assert saved['initial_user_content_utf8_sha256']!=saved['sanitized_projection_sha256']
    assert saved['source_content_reconstructible'] is False
    assert saved['facts']['completed_daily']['metrics']['volume_ratio']==.6
    assert 'never export' not in json.dumps(saved)
    assert saved['facts']['market_context']['SPY']['above_ema20'] is True
    p['candidate']['price']=1
    assert saved['facts']['candidate']['price']==101


def test_unmeasured_values_are_absent_not_zero_and_truncation_explicit():
    p=payload();p['candidate']['score']=True;p['market_context']['SPY']['above_ema20']=1
    p['recent_news'][0]['title']='X'*500
    saved,_=capture(p)
    assert 'score' not in saved['facts']['candidate']
    assert 'above_ema20' not in saved['facts']['market_context']['SPY']
    assert saved['facts']['recent_news'][0]['title_truncated'] is True
    assert len(saved['facts']['recent_news'][0]['title'])==256
    with pytest.raises(ValueError): facts.capture(p, '{}')


def test_separate_journal_is_observed_idempotent_and_does_not_rewrite_checks():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    conn.execute('CREATE TABLE scanner_candidates(scan_id,ticker,company,stage,status,reason,metrics_json,created_at)')
    saved,_=capture(payload());trace=dict(id='synthetic',scan_id='scan',ticker='TEST',input_facts=saved)
    for _ in range(2): target_evidence.persist_input_facts(conn, trace)
    rows=conn.execute('SELECT * FROM scanner_candidates').fetchall()
    assert len(rows)==1 and rows[0]['stage']=='review_input' and rows[0]['status']=='observed'
    assert json.loads(rows[0]['metrics_json'])['observation_id']=='synthetic:input_facts'


def test_evidence_storage_failure_does_not_fail_the_outer_transaction():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    saved,_=capture(payload())
    target_evidence.persist_input_facts(conn, dict(id='test',scan_id='scan',ticker='TEST',input_facts=saved))
    assert conn.execute('SELECT 1').fetchone()[0]==1


def test_actual_ai_review_records_actual_projection_before_transport(db, clock, monkeypatch):
    import database
    import final_ai
    import stock_scanner as scanner
    from test_review_evidence import candidate, held
    trace=final_ai.new_trace('input-facts-isolated','TEST',1)
    token=final_ai.TRACE.set(trace)
    observed=[]
    def transport(messages,validator):
        with database.get_db_connection() as conn:
            rows=conn.execute("SELECT metrics_json FROM scanner_candidates WHERE stage='review_input'").fetchall()
        assert len(rows)==1
        saved=json.loads(rows[0]['metrics_json'])
        assert saved['initial_user_content_utf8_sha256']==hashlib.sha256(messages[1]['content'].encode()).hexdigest()
        observed.append(saved)
        return held()
    monkeypatch.setattr(final_ai,'review',transport)
    try:
        assert scanner.ai_review(candidate(),[],{'SPY':{'close':500.}})['action']=='HOLD'
    finally:
        final_ai.TRACE.reset(token)
    assert len(observed)==1


def test_optional_capture_failure_does_not_prevent_the_existing_review(clock,monkeypatch):
    import final_ai
    import stock_scanner as scanner
    from test_review_evidence import candidate,held
    trace=final_ai.new_trace('input-facts-failed','TEST',1)
    token=final_ai.TRACE.set(trace)
    monkeypatch.setattr(facts,'capture',Mock(side_effect=ValueError('invalid optional evidence')))
    transport=Mock(return_value=held());monkeypatch.setattr(final_ai,'review',transport)
    try:
        assert scanner.ai_review(candidate(),[],{})['action']=='HOLD'
    finally:final_ai.TRACE.reset(token)
    assert transport.call_count==1 and 'input_facts' not in trace


# Existing dedicated temporary SQLite/clock fixtures; no real DB initializer.
from test_signal_inputs import db,clock
