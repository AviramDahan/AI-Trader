"""Isolated providers, temporary database, no production signals or Telegram."""
import asyncio
import copy
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import final_ai
import scanner_engine
import scanner_targets
import stock_scanner as scanner

DECISION = dict(action="BUY", confidence=.91, news_sentiment=.4,
                news_relevance=.9, time_horizon="1-4 weeks", reason="Aligned evidence.")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", "")
    monkeypatch.setattr(database, "_SQLITE_DB_PATH", str(tmp_path / "test.db"))
    database.init_database()
    return tmp_path / "test.db"


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv("STOCK_SCANNER_FINAL_AI_PROVIDER", "ollama")
    monkeypatch.delenv("STOCK_SCANNER_FINAL_AI_MODEL", raising=False)
    monkeypatch.setattr(final_ai.time, "sleep", Mock())
    monkeypatch.setattr(final_ai, "persist", Mock())
    post = Mock()
    monkeypatch.setattr(final_ai.requests, "post", post)
    return post


def response(value=DECISION, cloud=False):
    content = value if isinstance(value, str) else json.dumps(value)
    body = ({"choices":[{"message":{"content":content}}],
             "usage":{"prompt_tokens":101,"completion_tokens":32,"cost":.001}}
            if cloud else {"message":{"content":content},"prompt_eval_count":101,"eval_count":32})
    return Mock(json=Mock(return_value=body))


def review():
    return final_ai.review([{"role":"user","content":"fixture"}],
                           lambda v: scanner.validate_ai_decision(v, "BUY"))


def test_strict_ollama_schema_and_valid_hold_no_retry(transport):
    transport.return_value = response({**DECISION,"action":"HOLD","confidence":.1})
    assert review()["action"] == "HOLD"
    assert transport.call_count == 1
    assert transport.call_args.kwargs["json"]["format"] == final_ai.SCHEMA


@pytest.mark.parametrize("bad", ["not json", {**DECISION,"extra":1}, {**DECISION,"confidence":True},
                                 {**DECISION,"confidence":float('nan')}, {**DECISION,"reason":""}])
def test_schema_repair_once(transport, bad):
    transport.side_effect = [response(bad), response()]
    assert review()["action"] == "BUY"
    assert transport.call_count == 2


def test_repair_exhausted_fail_closed(transport):
    transport.return_value = response("bad")
    with pytest.raises(json.JSONDecodeError):
        review()
    assert transport.call_count == 2


def test_timeout_then_schema_failure_shares_one_retry_budget(transport):
    transport.side_effect = [requests.Timeout(), response("bad"), response()]
    with pytest.raises(json.JSONDecodeError):
        review()
    assert transport.call_count == 2


def test_semantic_direction_not_repaired(transport):
    transport.return_value = response({**DECISION,"action":"SELL"})
    with pytest.raises(ValueError, match="direction"):
        review()
    assert transport.call_count == 1


def test_missing_cloud_key_never_calls_provider(transport,monkeypatch):
    monkeypatch.setenv("STOCK_SCANNER_FINAL_AI_PROVIDER","openrouter")
    monkeypatch.setenv("STOCK_SCANNER_FINAL_AI_MODEL","test/model")
    monkeypatch.delenv("OPENROUTER_API_KEY",raising=False)
    with pytest.raises(ValueError,match="credentials"):
        review()
    transport.assert_not_called()


def test_retry_usage_is_summed_without_double_counting_candidate(transport):
    transport.side_effect=[response("bad"),response()]
    trace=final_ai.new_trace("scan","ABC",5)
    token=final_ai.TRACE.set(trace)
    try:
        review()
    finally:
        final_ai.TRACE.reset(token)
    assert len(trace["attempts"])==2
    assert final_ai._total(trace["attempts"],"input_tokens")==202
    assert final_ai._total(trace["attempts"],"output_tokens")==64
    assert final_ai._total(trace["attempts"],"estimated_cost") is None


@pytest.mark.parametrize("status,expected", [(401,1),(400,1),(429,2),(503,2)])
def test_http_retry_policy(transport,status,expected):
    transport.side_effect = requests.HTTPError(response=Mock(status_code=status))
    with pytest.raises(requests.HTTPError):
        review()
    assert transport.call_count == expected


def test_openrouter_schema_and_usage(transport,monkeypatch):
    monkeypatch.setenv("STOCK_SCANNER_FINAL_AI_PROVIDER","openrouter")
    monkeypatch.setenv("STOCK_SCANNER_FINAL_AI_MODEL","test/model")
    monkeypatch.setenv("OPENROUTER_API_KEY","test-only")
    transport.return_value=response(cloud=True)
    trace=final_ai.new_trace("scan","ABC",6)
    token=final_ai.TRACE.set(trace)
    try:
        review()
    finally:
        final_ai.TRACE.reset(token)
    body=transport.call_args.kwargs["json"]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"]["require_parameters"] is True
    assert trace["attempts"][0]["input_tokens"] == 101
    assert trace["attempts"][0]["output_tokens"] == 32
    assert trace["attempts"][0]["estimated_cost"] == .001
    assert "test-only" not in json.dumps(trace)


def test_telemetry_durable_unknown_usage_and_no_db_lock_during_http(db,monkeypatch):
    monkeypatch.setenv("STOCK_SCANNER_FINAL_AI_PROVIDER","ollama")
    monkeypatch.delenv("STOCK_SCANNER_FINAL_AI_MODEL",raising=False)
    trace=final_ai.new_trace("scan","ABC",4)
    final_ai.persist(trace)
    def post(*args,**kwargs):
        conn=database.get_db_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        finally:
            conn.close()
        return Mock(json=Mock(return_value={"message":{"content":json.dumps(DECISION)}}))
    monkeypatch.setattr(final_ai.requests,"post",post)
    token=final_ai.TRACE.set(trace)
    try:
        review()
    finally:
        final_ai.TRACE.reset(token)
    trace.update(result="rejected",reject_reason="duplicate_cooldown")
    final_ai.persist(trace)
    final_ai.persist(trace)  # same candidate record is idempotently updated
    conn=database.get_db_connection()
    rows=conn.execute("SELECT * FROM scanner_final_ai_telemetry").fetchall()
    conn.close()
    assert len(rows)==1
    assert rows[0]["rank"]==4 and rows[0]["reject_reason"]=="duplicate_cooldown"
    assert rows[0]["input_tokens"] is None and rows[0]["estimated_cost"] is None
    database.init_database()  # additive migration/startup is repeatable
    conn=database.get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM scanner_final_ai_telemetry").fetchone()[0]==1
    conn.close()


@pytest.fixture
def pipeline(monkeypatch,tmp_path):
    # Existing V1/STAGED preflight regression; V2 is covered separately.
    monkeypatch.setattr(scanner_engine, 'lifecycle_settings', lambda: {'active_strategy':'staged'})
    monkeypatch.setenv("STOCK_SCANNER_TOKEN","test-only")
    monkeypatch.setenv("STOCK_SCANNER_AI_CANDIDATE_LIMIT","6")
    monkeypatch.setattr(scanner,'regular_session_open',lambda:True)
    monkeypatch.setattr(scanner,'research_reference_quote',Mock(side_effect=AssertionError('Provider calls forbidden')))
    monkeypatch.setattr(__import__('signal_projection'),'retry_pending',Mock())
    monkeypatch.setattr(scanner,"STATE_FILE",tmp_path/"state.json")
    candidates=[dict(ticker=f"T{i}",company=f"Company{i}",technical_direction="BUY",technical_score=7,
                     average_dollar_volume=1e9-i,atr=2,atr_pct=2,return_20d_pct=4,
                     price_zones=[{"low":p,"high":p} for p in (97,108,116,124)],
                     news=[],combined_rank_score=.99-i*.01) for i in range(1,8)]
    monkeypatch.setattr(scanner,"load_universe",lambda:{c["ticker"]:{"company":c["company"],"indexes":["S&P 500"]} for c in candidates})
    monkeypatch.setattr(scanner,"load_historical_data",lambda *a:({c["ticker"]:None for c in candidates},{}))
    monkeypatch.setattr(scanner,"_market_context",lambda *a:{})
    monkeypatch.setattr(scanner,"analyze_history",lambda ticker,*a:copy.deepcopy(next(c for c in candidates if c["ticker"]==ticker)))
    monkeypatch.setattr(scanner,"enrich_and_rank_candidates",lambda *a:(copy.deepcopy(candidates),[]))
    for name in ("initialize_runtime","record_candidates","record_scan_news","set_service_status"):
        monkeypatch.setattr(scanner_engine,name,Mock())
    monkeypatch.setattr(scanner_engine,"record_signal",Mock(return_value={"id":1,"status":"PENDING_ENTRY"}))
    monkeypatch.setattr(scanner,"_localize_telegram_signal",lambda v:v)
    session=Mock(headers={})
    session.request.return_value=Mock(json=Mock(return_value={"signal_id":1}))
    monkeypatch.setattr(scanner.requests,"Session",lambda:session)
    events=[]
    monkeypatch.setattr(final_ai,"persist",lambda trace:events.append(copy.deepcopy(trace)))
    quote=Mock(return_value=(100,"2026-09-25T15:00:00Z"))
    monkeypatch.setattr(scanner,"current_intraday_quote",quote)
    def decide(*a):
        final_ai.TRACE.get()["ai_started"]=True
        return {**DECISION,"action":"HOLD"}
    ai=Mock(side_effect=decide)
    monkeypatch.setattr(scanner,"ai_review",ai)
    return candidates,quote,ai,events,session


def test_early_quote_skips_bounded_pool_without_ai(pipeline):
    _,quote,ai,events,session=pipeline
    quote.return_value=None
    scanner.run_scan()
    assert ai.call_count==0 and session.request.call_count==0
    assert [e["rank"] for e in events]==[1,2,3,4,5,6,7]
    assert all(e["ai_call_saved"] and e["result"]=="early_skip" for e in events)
    assert all(e['target_checks']['pre_ai']['outcome']=='NOT_EVALUATED' for e in events)
    assert all(e['target_checks']['pre_ai']['quote']['price'] is None for e in events)


def test_early_cooldown(pipeline):
    _,quote,ai,events,_=pipeline
    scanner.save_state({"cooldowns":{"T1:BUY":time.time()}})
    scanner.run_scan()
    assert ai.call_count==6
    assert events[0]["reject_reason"]=="pre_duplicate_cooldown"


def test_early_targets_skip_without_ai(pipeline):
    candidates,_,ai,events,_=pipeline
    for c in candidates:c["price_zones"]=[]
    scanner.run_scan()
    assert ai.call_count==0
    assert all(e["reject_reason"]=="pre_insufficient_confirmed_price_zones" for e in events)
    assert all(e['target_checks']['pre_ai']['outcome']=='REJECT' for e in events)


def test_quote_provider_error_is_early_skip(pipeline):
    _,quote,ai,events,_=pipeline
    quote.side_effect=requests.Timeout()
    scanner.run_scan()
    ai.assert_not_called()
    assert len(events)==7 and all(e["ai_call_saved"] for e in events)


def test_success_preserves_max_three_and_paper_publication(pipeline):
    _,quote,ai,events,session=pipeline
    def decide(*a):
        final_ai.TRACE.get()["ai_started"]=True
        return copy.deepcopy(DECISION)
    ai.side_effect=decide
    result=scanner.run_scan()
    assert ai.call_count==3 and quote.call_count==6
    assert result["signals_published"]==3
    assert result["ai_candidates_count"]==3
    assert result["ai_selected_count"]==3
    assert all(c.args[1].endswith("/signals/strategy") for c in session.request.call_args_list)
    assert [e["rank"] for e in events if e["result"]=="signal"]==[1,2,3]
    assert all(set(e['target_checks'])=={'pre_ai','post_ai'} for e in events if e['result']=='signal')


@pytest.mark.parametrize("change", ["stale","targets","cooldown"])
def test_post_ai_rechecks_prevent_signal(pipeline,monkeypatch,change):
    _,quote,ai,events,session=pipeline
    def decide(*a):
        final_ai.TRACE.get()["ai_started"]=True
        if change=="stale":quote.return_value=None
        if change=="targets":quote.return_value=(97,"2026-09-25T15:00:01Z")
        return copy.deepcopy(DECISION)
    ai.side_effect=decide
    if change=="cooldown":
        monkeypatch.setattr(scanner,"duplicate_in_cooldown",Mock(side_effect=[False,True]*6))
    scanner.run_scan()
    assert session.request.call_count==0
    assert events[1]["result"]=="rejected" and not events[1]["ai_call_saved"]


def test_hold_not_retried_or_published_and_keeps_six(pipeline):
    _,_,ai,events,session=pipeline
    scanner.run_scan()
    assert ai.call_count==6 and session.request.call_count==0
    assert len([e for e in events if e["result"]=="rejected"])==6


def test_deterministic_failures_refill_but_hold_consumes_slot(pipeline):
    candidates,quote,ai,events,_=pipeline
    candidates[0]['price_zones']=[]
    result=scanner.run_scan()
    assert ai.call_count==6 and result['ai_selected_count']==6
    assert events[0]['reject_reason']=='pre_insufficient_confirmed_price_zones'
    assert [e['rank'] for e in events if e['ai_started']]==[2,3,4,5,6,7]


def test_closed_session_reference_is_research_only(pipeline,monkeypatch):
    _,quote,ai,events,session=pipeline
    monkeypatch.setattr(scanner,'regular_session_open',lambda:False)
    reference=Mock(return_value=dict(price=101,as_of='2026-09-25T12:59:00Z',
        source='yahoo_prepost_1m',fresh=True,age_seconds=60,eligible_for_entry=False))
    monkeypatch.setattr(scanner,'research_reference_quote',reference)
    result=scanner.run_scan()
    assert reference.call_count==6 and result['ai_selected_count']==0
    quote.assert_not_called();ai.assert_not_called();session.request.assert_not_called()
    scanner_engine.record_signal.assert_not_called()
    assert all(e['reject_reason']=='pre_waiting_regular_session' for e in events)
    assert all(e['target_checks']['pre_ai']['quote']['eligible_for_entry'] is False for e in events)


def test_ai_input_uses_actual_quote_and_validated_plan(pipeline):
    candidates,_,ai,events,_=pipeline
    for c in candidates:c.update(entry=95,price_as_of='2026-09-24')
    scanner.run_scan()
    value=ai.call_args.args[0]
    assert value['entry']==100 and value['daily_reference_close']==95
    assert value['quote_at']=='2026-09-25T15:00:00Z'
    assert value['validated_target_plan']['entry']==100
    assert candidates[0]['entry']==95  # No alteration of recorded technical evidence.
    decision=next(e['decision'] for e in events if e.get('decision'))
    assert decision['quote']['price']==100
    assert decision['filter_failures']==['ai_hold']


def test_durable_failure_cannot_publish_projection(pipeline,monkeypatch):
    _,_,ai,_,session=pipeline
    ai.side_effect=lambda *a:copy.deepcopy(DECISION)
    monkeypatch.setattr(scanner_engine,'record_signal',Mock(side_effect=RuntimeError('isolated failure')))
    result=scanner.run_scan()
    assert result['signals_published']==0
    session.request.assert_not_called()


def test_projection_failure_does_not_create_second_order(pipeline):
    _,_,ai,_,session=pipeline
    ai.side_effect=lambda *a:copy.deepcopy(DECISION)
    session.request.side_effect=requests.Timeout('isolated publication failure')
    result=scanner.run_scan()
    assert result['signals_published']==3 and scanner_engine.record_signal.call_count==3
    assert session.request.call_count==3
    saved=scanner_engine.record_signal.call_args.args[1]
    assert saved['_strategy_projection']['market']=='us-stock'
    assert session.request.call_args.kwargs['json']['scanner_signal_id']==1


def test_monitor_and_state_access_not_blocked_by_scanner_lock(monkeypatch):
    monkeypatch.setattr(scanner_engine,"monitor_prices",lambda:{"ok":True})
    with scanner.SCAN_LOCK:
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(scanner.monitor_tracked_signals).result(timeout=1)=={"ok":True}


def test_monitor_runs_while_ai_http_is_blocked(transport,monkeypatch):
    started=threading.Event();release=threading.Event()
    def blocked(*a,**kw):
        started.set()
        assert release.wait(3)
        return response()
    transport.side_effect=blocked
    monkeypatch.setattr(scanner_engine,"monitor_prices",lambda:{"ok":True})
    with ThreadPoolExecutor(max_workers=2) as executor:
        future=executor.submit(review)
        try:
            assert started.wait(1)
            assert executor.submit(scanner.monitor_tracked_signals).result(timeout=1)=={"ok":True}
        finally:
            release.set()
        assert future.result(timeout=1)["action"]=="BUY"


def test_monitor_loop_has_capacity_when_default_executor_is_saturated(monkeypatch):
    monkeypatch.setenv("STOCK_SCANNER_ENABLED","true")
    ran=threading.Event()
    release=threading.Event()
    monkeypatch.setattr(scanner,"monitor_tracked_signals",lambda:ran.set())
    async def sleep(seconds):
        if seconds!=45:
            raise asyncio.CancelledError()
    monkeypatch.setattr(scanner.asyncio,"sleep",sleep)
    async def scenario():
        loop=asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        blocker=loop.run_in_executor(None,release.wait,3)
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(scanner.stock_signal_monitor_loop(),timeout=1)
            assert ran.is_set()
        finally:
            release.set()
            await blocker
    asyncio.run(scenario())
