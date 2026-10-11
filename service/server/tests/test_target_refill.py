"""Bounded selection refill; real admission/lifecycle, synthetic evidence only."""
import copy
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from test_signal_inputs import db, clock, canonical_fixture
import database
import stock_scanner as scanner
import scanner_engine as engine
from test_signal_news_selection import insert_event
from test_signal_admission_chain import prepare, rows
from test_single_target_v2 import zone


def population(monkeypatch, clock, initial_valid=False, tail_count=1, initial_count=25, tail_news=False):
    base, review, session = prepare(monkeypatch, clock)
    initial = [f'AAA{i:03d}' for i in range(initial_count)]
    tail = ['TEST'] + [f'ZZZ{i:03d}' for i in range(tail_count-1)]
    candidates = {}
    for index, ticker in enumerate(initial+tail):
        row = copy.deepcopy(base)
        row.update(ticker=ticker, company=f'Synthetic {ticker} Corporation',
                   average_dollar_volume=1e9-index*1e6)
        if ticker in initial and not initial_valid:
            row['price_zones'] = [zone(98,98.4),zone(102,103)]
        candidates[ticker] = row
    with database.get_db_connection() as conn:
        for ticker in initial + (tail[1:] if tail_news else []):
            body = json.loads(canonical_fixture()['body_json'])
            body['tickers'] = [ticker]
            body['company_identity'][0].update(ticker=ticker,company=candidates[ticker]['company'])
            body['title'] = f"{candidates[ticker]['company']} announces a new factory opening"
            body['sources'][0].update(tickers=[ticker],title=body['title'],
                source_excerpt=body['title']+' with production scheduled for the next fiscal quarter.')
            insert_event(conn,'story-'+ticker,json.dumps(body))
        conn.commit()
    monkeypatch.setattr(scanner,'load_universe',lambda:{t:dict(company=r['company'],indexes=['synthetic']) for t,r in candidates.items()})
    monkeypatch.setattr(scanner,'load_historical_data',lambda *a:({t:object() for t in candidates},{'status':'synthetic'}))
    monkeypatch.setattr(scanner,'analyze_history',lambda ticker,*a:copy.deepcopy(candidates[ticker]))
    # TEST has the original verified story. No data/provider requests are real.
    candidates['TEST']['company'] = base['company']
    return candidates, review, session


def test_target_failure_refill_reaches_pending_then_real_entry_exit_restart(db,clock,monkeypatch):
    candidates, review, _ = population(monkeypatch,clock)
    result = scanner.run_scan()
    assert result['signals_published'] == 1
    assert review.call_count == 1 and review.call_args.args[0]['ticker'] == 'TEST'
    assert result['target_refill']['target_failures'] == 25
    assert result['target_refill']['checked'] == 1
    assert result['target_refill']['news_lookups'] == 1
    assert result['target_refill']['ai_selected'] == 1
    assert rows('SELECT status FROM scanner_orders') == [{'status':'pending'}]
    assert not rows('SELECT id FROM scanner_fills')
    entry = dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.5,close=100)
    clock.instant = datetime(2026,10,6,14,10,tzinfo=timezone.utc)
    engine.process_bar('TEST',entry)
    exit_bar = dict(at='2026-10-06T14:10:00Z',open=104.5,high=105,low=104,close=104.5)
    clock.instant = datetime(2026,10,6,14,15,tzinfo=timezone.utc)
    engine.process_bar('TEST',exit_bar)
    engine.initialize_runtime()
    engine.process_bar('TEST',entry)
    engine.process_bar('TEST',exit_bar)
    scanner.run_scan()
    assert review.call_count == 1
    assert len(rows('SELECT id FROM scanner_orders')) == 1
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


@pytest.mark.parametrize('block',['hold','confidence','quote','session','no_news'])
def test_non_target_failures_do_not_trigger_refill(db,clock,monkeypatch,block):
    _, review, _ = population(monkeypatch,clock,initial_valid=True)
    if block == 'hold': review.return_value['action'] = 'HOLD'
    if block == 'confidence': review.return_value['confidence'] = .79
    if block == 'quote': monkeypatch.setattr(scanner,'current_intraday_quote',lambda *a:None)
    if block == 'session': monkeypatch.setattr(scanner,'regular_session_open',lambda:False)
    if block == 'no_news': monkeypatch.setattr('signal_news.existing_news',lambda *a,**k:{})
    result = scanner.run_scan()
    assert result['signals_published'] == 0
    assert result['target_refill']['checked'] == 0
    assert all(call.args[0]['ticker'] != 'TEST' for call in review.call_args_list)
    assert review.call_count <= 6
    assert not rows('SELECT id FROM scanner_orders')


def test_refill_revalidates_quote_after_ai_and_never_moves_targets(db,clock,monkeypatch):
    _, review, _ = population(monkeypatch,clock)
    def quote(ticker):
        return (103 if review.called else 100,clock.instant.isoformat())
    monkeypatch.setattr(scanner,'current_intraday_quote',quote)
    result = scanner.run_scan()
    assert review.call_count == 1
    assert result['signals_published'] == 0
    assert not rows('SELECT id FROM scanner_orders')
    assert any(r['reason'] in {'structural_stop_too_distant','nearest_resistance_below_2r'}
               for r in result['rejected'])


def test_refill_budget_gate_still_blocks_durable_order(db,clock,monkeypatch):
    population(monkeypatch,clock)
    monkeypatch.setattr('ai_budget.check',Mock(side_effect=RuntimeError('synthetic budget block')))
    result = scanner.run_scan()
    assert result['signals_published'] == 0
    assert not rows('SELECT id FROM scanner_orders')


def test_refill_preserves_allocation_block_as_signal_not_active_position(db,clock,monkeypatch):
    population(monkeypatch,clock)
    engine.initialize_runtime()
    with database.get_db_connection() as conn:
        conn.execute('UPDATE scanner_accounts SET cash=0')  # Disposable test account only.
        conn.commit()
    result = scanner.run_scan()
    assert result['signals_published'] == 1
    assert rows('SELECT status FROM scanner_signals') == [{'status':'RISK_BLOCKED'}]
    assert not rows('SELECT id FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')


def test_refill_checks_are_bounded_and_cursor_survives_scan_restart(db,clock,monkeypatch):
    candidates,review,_ = population(monkeypatch,clock,tail_count=140)
    for ticker in list(candidates)[25:]:
        candidates[ticker]['price_zones'] = [zone(98,98.4),zone(102,103)]
    monkeypatch.setattr(scanner.time,'monotonic',lambda:0)
    first = scanner.run_scan()
    assert first['target_refill']['checked'] == 64
    assert first['target_refill']['stop_reason'] == 'check_limit'
    cursor = first['target_refill_cursor']
    assert first['target_refill']['news_lookups'] == 0
    second = scanner.run_scan()
    assert second['target_refill']['checked'] == 64
    assert second['target_refill']['start_after'] == cursor
    assert second['target_refill_cursor'] != cursor
    review.assert_not_called()


def test_refill_runtime_budget_stops_before_another_request(db,clock,monkeypatch):
    candidates,review,_ = population(monkeypatch,clock,tail_count=5)
    for ticker in list(candidates)[25:]:
        candidates[ticker]['price_zones'] = [zone(98,98.4),zone(102,103)]
    elapsed = [0]
    monkeypatch.setattr(scanner.time,'monotonic',lambda:elapsed[0])
    def quote(ticker):
        if ticker == 'TEST': elapsed[0] += 121
        return (100,clock.instant.isoformat())
    monkeypatch.setattr(scanner,'current_intraday_quote',quote)
    result = scanner.run_scan()
    assert result['target_refill']['checked'] == 1
    assert result['target_refill']['stop_reason'] == 'time_budget'
    assert result['target_refill']['news_lookups'] == 0
    review.assert_not_called()


def test_initial_and_refill_share_six_ai_slots_no_extra_hold_replacements(db,clock,monkeypatch):
    candidates,review,_ = population(monkeypatch,clock,tail_count=20,tail_news=True)
    candidates['AAA000']['price_zones'] = copy.deepcopy(candidates['TEST']['price_zones'])
    review.return_value['action'] = 'HOLD'
    monkeypatch.setattr(scanner.time,'monotonic',lambda:0)
    result = scanner.run_scan()
    assert review.call_count == result['ai_selected_count'] == 6
    assert result['target_refill']['ai_selected'] == 5
    assert result['target_refill']['checked'] == 5  # No phantom seventh selection/cursor advance.
    assert result['target_refill']['news_lookups'] == 5
    assert result['target_refill']['stop_reason'] == 'ai_limit'
    assert len({call.args[0]['ticker'] for call in review.call_args_list}) == 6
    assert not rows('SELECT id FROM scanner_orders')
    stored = rows("SELECT metrics_json FROM scanner_candidates WHERE stage='admission_selection'")
    assert json.loads(stored[0]['metrics_json']) == result['target_refill']


def test_refill_news_failure_consumes_credit_not_another_quota(db,clock,monkeypatch):
    _,review,_ = population(monkeypatch,clock,tail_count=40)
    review.return_value['action'] = 'HOLD'
    monkeypatch.setattr(scanner.time,'monotonic',lambda:0)
    result = scanner.run_scan()
    assert result['target_refill']['credits_created'] == 25
    assert result['target_refill']['checked'] == result['target_refill']['news_lookups'] == 25
    assert result['target_refill']['credits_remaining'] == 0
    assert result['target_refill']['stop_reason'] == 'no_target_credits'
    assert review.call_count == 1
    assert not rows('SELECT id FROM scanner_orders')


def test_market_closing_before_refill_starts_no_tail_requests(db,clock,monkeypatch):
    _,review,_ = population(monkeypatch,clock)
    opened = [True]
    quotes = []
    monkeypatch.setattr(scanner,'regular_session_open',lambda:opened[0])
    def quote(ticker):
        quotes.append(ticker)
        if ticker == 'AAA024': opened[0] = False
        return (100,clock.instant.isoformat())
    monkeypatch.setattr(scanner,'current_intraday_quote',quote)
    result = scanner.run_scan()
    assert 'TEST' not in quotes
    assert result['target_refill']['stop_reason'] == 'market_closed'
    assert result['target_refill']['checked'] == 0
    review.assert_not_called()


def test_refill_timeout_is_fail_closed_not_an_order(db,clock,monkeypatch):
    population(monkeypatch,clock)
    def quote(ticker):
        if ticker == 'TEST': raise scanner.requests.Timeout('synthetic timeout')
        return (100,clock.instant.isoformat())
    monkeypatch.setattr(scanner,'current_intraday_quote',quote)
    result = scanner.run_scan()
    assert result['signals_published'] == 0
    assert not rows('SELECT id FROM scanner_orders')
    assert any(r['reason']=='timeout_fail_closed' for r in result['rejected'])


def test_selector_deduplicates_tail_and_rotates_without_altering_rank(monkeypatch):
    monkeypatch.setattr(scanner,'regular_session_open',lambda:True)
    initial = [dict(ticker='INITIAL')]
    tail = [dict(ticker=t) for t in ('A','B','A','INITIAL','C')]
    selector = scanner._TargetRefill(initial,tail,'B')
    selector.target_failed(False)
    checked = []
    for candidate,refill in selector:
        checked.append((candidate['ticker'],refill))
        if refill: selector.target_failed(True)
    assert checked == [('INITIAL',False),('C',True),('A',True),('B',True)]
    assert selector.credits == 1  # Failures do not compound credits.


def test_refill_deadline_during_news_does_not_start_ai(db,clock,monkeypatch):
    population(monkeypatch,clock)
    elapsed = [0]
    monkeypatch.setattr(scanner.time,'monotonic',lambda:elapsed[0])
    original = scanner.enrich_and_rank_candidates
    def enrich(candidates,*args):
        result = original(candidates,*args)
        if len(candidates) == 1 and candidates[0]['ticker'] == 'TEST': elapsed[0] = 121
        return result
    monkeypatch.setattr(scanner,'enrich_and_rank_candidates',enrich)
    review = scanner.ai_review
    result = scanner.run_scan()
    assert result['target_refill']['stop_reason'] == 'time_budget'
    assert result['target_refill']['news_lookups'] == 1
    assert not rows('SELECT id FROM scanner_orders')
    review.assert_not_called()


def test_late_rank_candidate_is_reached_across_bounded_cycles(db,clock,monkeypatch):
    candidates,review,_ = population(monkeypatch,clock,tail_count=220)
    # Put the valid synthetic ticker at rank 195, not an exceptional ticker rule.
    candidates['TEST']['average_dollar_volume'] = 1e9-194.5e6
    for ticker in list(candidates)[26:]:
        candidates[ticker]['price_zones'] = [zone(98,98.4),zone(102,103)]
    monkeypatch.setattr(scanner.time,'monotonic',lambda:0)
    assert scanner.run_scan()['signals_published'] == 0
    assert scanner.run_scan()['signals_published'] == 0
    third = scanner.run_scan()
    assert third['signals_published'] == 1 and review.call_count == 1
    assert review.call_args.args[0]['ticker'] == 'TEST'
    assert third['target_refill']['checked'] <= 64
    inventories = rows("""SELECT COUNT(*) n FROM
        (SELECT scan_id,ticker FROM scanner_candidates GROUP BY scan_id,ticker) stocks""")
    technical = rows("""SELECT COUNT(*) n FROM
        (SELECT scan_id,ticker FROM scanner_candidates WHERE stage='technical' GROUP BY scan_id,ticker) stocks""")
    assert inventories == technical
