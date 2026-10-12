"""Synthetic price contracts and bounded mocked transport; no live AI or Telegram."""
import copy
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import stock_scanner as scanner
import final_ai
from test_review_evidence import candidate, held
from test_signal_inputs import clock, db
from test_final_ai_preflight import transport, response


def input_candidate():
    c=candidate()
    c['validated_target_plan']=dict(entry=110,stop=105,targets=[120],rr=[2],
        policy_version='single_breakout_v1',target_kind='projected_2r_not_confirmed_resistance')
    return c


def decision(**changes):
    value=dict(held(),entry_price_relation='equal',entry_price_concern='none')
    value.update(changes)
    return value


def test_projection_has_one_authoritative_price_contract(monkeypatch,clock):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    capture=Mock(return_value=held());monkeypatch.setattr(scanner.final_ai,'review',capture)
    c=input_candidate();before=copy.deepcopy(c)
    scanner.ai_review(c,[],{})
    payload=json.loads(capture.call_args.args[0][1]['content'])
    facts=payload['review_evidence_context']['entry_price_facts']
    assert facts['status']=='VERIFIED' and facts['relation']=='equal'
    assert facts['quote_price']==facts['planned_entry']==110
    assert not {'entry','quote_at','daily_reference_close','daily_reference_as_of','validated_target_plan'}.intersection(payload['candidate'])
    assert payload['review_evidence_context']['completed_daily']['reference_close']==105
    assert c==before


def test_false_above_entry_hold_is_repaired_without_changing_action(transport,clock):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    bad=decision(reason='The quote is already above the planned entry.')
    good=decision(reason='News is mixed; HOLD remains appropriate.')
    transport.side_effect=[response(bad),response(good)]
    result=scanner.ai_review(input_candidate(),[],{})
    assert result['action']=='HOLD' and result['entry_rationale']['status']=='REPAIRED'
    assert transport.call_count==2
    feedback=transport.call_args.kwargs['json']['messages'][-1]['content']
    assert 'HOLD' in feedback and 'locked_decision' in feedback


@pytest.mark.parametrize('changed',[
    {'action':'BUY'},{'confidence':.99},{'news_relevance':.99},
    {'news_sentiment':.9},{'time_horizon':'1-3 months'}])
def test_rationale_repair_cannot_promote_or_change_original_decision(transport,clock,changed):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    bad=decision(reason='The quote is above the planned entry.')
    replacement=dict(decision(reason='Corrected rationale.'),**changed)
    transport.side_effect=[response(bad),response(replacement)]
    with pytest.raises(ValueError,match='rationale_repair_changed_decision'):
        scanner.ai_review(input_candidate(),[],{})
    assert transport.call_count==2


@pytest.mark.parametrize('bad',[
    decision(entry_price_relation='above'),
    decision(entry_price_concern='quote_above_planned_entry'),
    decision(reason='The current price is below the planned entry.')])
def test_contradictory_structured_or_known_prose_claim_fails_closed(transport,clock,bad):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    transport.return_value=response(bad)
    with pytest.raises(final_ai.SchemaFailure):scanner.ai_review(input_candidate(),[],{})
    assert transport.call_count==2


@pytest.mark.parametrize('reason',[
    'Recent headlines are mixed.',
    'There is no evidence that the quote is above the planned entry.',
    'If the quote is above the planned entry later, reassess.',
    'The quote is not above the planned entry.',
    'The target is above the planned entry.',
    'Comparable intraday volume is unknown.'])
def test_legitimate_hold_or_nonassertion_is_not_repaired(transport,clock,reason):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    transport.return_value=response(decision(reason=reason))
    result=scanner.ai_review(input_candidate(),[],{})
    assert result['action']=='HOLD' and transport.call_count==1
    assert result['entry_rationale']['status']=='VERIFIED'


@pytest.mark.parametrize('first',[ 'timeout','json'])
def test_retry_and_rationale_repair_share_existing_two_attempts(transport,clock,first):
    import requests
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    transport.side_effect=[requests.Timeout() if first=='timeout' else response('bad json'),
        response(decision(reason='The quote is above the planned entry.')),response(decision())]
    with pytest.raises(final_ai.SchemaFailure):scanner.ai_review(input_candidate(),[],{})
    assert transport.call_count==2


def test_unknown_comparison_does_not_invent_price_relation(transport,clock):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    c=input_candidate();c.pop('validated_target_plan')
    transport.return_value=response(dict(held(),entry_price_relation='unknown',entry_price_concern='none'))
    result=scanner.ai_review(c,[],{})
    assert result['entry_rationale']['status']=='UNVERIFIABLE' and transport.call_count==1


@pytest.mark.parametrize('planned,relation,concern,reason',[
    (109,'above','quote_above_planned_entry','The quote is above the planned entry.'),
    (111,'below','quote_below_planned_entry','The quote is below the planned entry.')])
def test_true_comparison_is_not_rejected(transport,clock,planned,relation,concern,reason):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    c=input_candidate();c['validated_target_plan']['entry']=planned
    transport.return_value=response(decision(entry_price_relation=relation,entry_price_concern=concern,reason=reason))
    result=scanner.ai_review(c,[],{})
    assert result['entry_rationale']['price_relation']==relation and transport.call_count==1


@pytest.mark.parametrize('bad',['zero','nan','bool','future','stale','missing_time','context_conflict'])
def test_invalid_comparison_is_unknown_not_a_fabricated_relation(bad):
    from review_rationale import price_facts
    from review_evidence import context
    c=input_candidate();now=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    ctx=context(c,now,'2026-10-09')
    if bad=='zero':c['validated_target_plan']['entry']=0
    if bad=='nan':c['validated_target_plan']['entry']=float('nan')
    if bad=='bool':c['validated_target_plan']['entry']=True
    if bad=='future':ctx['entry_quote']['as_of']='2026-10-12T14:10:01Z'
    if bad=='stale':ctx['entry_quote']['as_of']='2026-10-12T13:57:59Z'
    if bad=='missing_time':ctx['entry_quote']['as_of']=None
    if bad=='context_conflict':ctx['entry_quote']['price']=109
    assert price_facts(c,ctx)['relation']=='unknown'


def test_missing_new_fields_still_locks_original_valid_hold(transport,clock):
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    transport.side_effect=[response(held()),response(decision(action='BUY'))]
    with pytest.raises(ValueError,match='rationale_repair_changed_decision'):
        scanner.ai_review(input_candidate(),[],{})
    assert transport.call_count==2


def test_cloud_schema_and_two_attempt_usage_remain_bounded(transport,clock,monkeypatch,db):
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','openrouter')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_MODEL','synthetic/model')
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-only')
    clock.instant=datetime(2026,10,12,14,10,tzinfo=timezone.utc)
    monkeypatch.setattr('ai_budget.check',Mock())
    monkeypatch.setattr('ai_budget.acquire_request_slot',Mock())
    from review_rationale import SCHEMA
    bad=decision(reason='The quote is above the planned entry.')
    transport.side_effect=[response(bad,cloud=True),response(decision(),cloud=True)]
    trace=final_ai.new_trace('synthetic-scan','TEST',1);token=final_ai.TRACE.set(trace)
    try:result=scanner.ai_review(input_candidate(),[],{})
    finally:final_ai.TRACE.reset(token)
    assert result['action']=='HOLD' and transport.call_count==2
    sent=transport.call_args.kwargs['json']
    assert sent['response_format']['json_schema']['schema']==SCHEMA
    assert sent['max_tokens']==450 and sent['model']=='synthetic/model'
    assert len(trace['attempts'])==2 and final_ai._total(trace['attempts'],'input_tokens')==202
    assert trace['attempts'][0]['entry_rationale_failure']['expected_relation']=='equal'
    assert 'synthetic-only' not in json.dumps(trace)


@pytest.mark.parametrize('repair_action',['HOLD','BUY'])
def test_actual_scanner_invalid_hold_never_creates_order(db,clock,monkeypatch,repair_action):
    from test_signal_admission_chain import prepare,rows
    from test_single_target_v2 import zone
    from test_review_evidence import scanner_review
    import database
    c,_,_=prepare(monkeypatch,clock)
    c['price_zones']=[zone(98,98.4),zone(104.65,105)]
    monkeypatch.setattr(scanner,'ai_review',scanner_review)
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','ollama')
    monkeypatch.delenv('STOCK_SCANNER_FINAL_AI_MODEL',raising=False)
    monkeypatch.setattr(final_ai.time,'sleep',Mock())
    bad=decision(reason='The quote is above the planned entry.')
    good=dict(decision(reason='Mixed evidence remains a HOLD.'),action=repair_action)
    def post(*args,**kwargs):
        # Actual application persist closes its DB connection before repair IO.
        with database.get_db_connection() as conn:
            assert conn.execute("SELECT count(*) n FROM scanner_candidates WHERE stage='target_check'").fetchone()['n']==1
        return response(bad if post.calls==0 else good)
    post.calls=0
    def counted(*a,**k):
        r=post(*a,**k);post.calls+=1;return r
    monkeypatch.setattr(final_ai.requests,'post',counted)
    result=scanner.run_scan()
    assert post.calls==2 and result['signals_published']==0
    assert not rows('SELECT id FROM scanner_orders') and not rows('SELECT id FROM scanner_fills')
    assert len(rows('SELECT id FROM scanner_final_ai_telemetry'))==1
    trace=json.loads(rows('SELECT attempts_json FROM scanner_final_ai_telemetry')[0]['attempts_json'])
    assert len(trace)==2 and trace[0]['entry_rationale_failure']['expected_relation']=='equal'
    if repair_action=='HOLD':
        saved=json.loads(rows("SELECT metrics_json FROM scanner_candidates WHERE stage='ai_decision'")[0]['metrics_json'])
        assert saved['action']=='HOLD' and saved['entry_rationale']['status']=='REPAIRED'
    else:assert not rows("SELECT id FROM scanner_candidates WHERE stage='ai_decision'")
