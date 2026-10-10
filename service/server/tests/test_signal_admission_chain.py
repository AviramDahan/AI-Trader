"""Real scanner/admission/bar executor on a disposable DB; all providers mocked."""
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from test_signal_inputs import db, clock
from test_signal_news_selection import seed_crowded_snapshot
from test_single_target_v2 import zone
import database
import scanner_engine as engine
import stock_scanner as scanner


def prepare(monkeypatch, clock):
    clock.instant = datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
    monkeypatch.setattr(engine, 'now_z', lambda: clock.instant.isoformat())
    monkeypatch.setenv('STOCK_SCANNER_TOKEN', 'synthetic-only')
    monkeypatch.setenv('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED', 'true')
    monkeypatch.setenv('STOCK_SCANNER_EXIT_STRATEGY', 'single')
    monkeypatch.setenv('SEC_INTELLIGENCE_MODE', 'off')
    monkeypatch.setenv('STOCK_SCANNER_TELEGRAM_ENABLED', 'false')
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER', 'ollama')
    # A dedicated test database/clock, not a cloud worker or a live quote.
    monkeypatch.delenv('AI_TRADER_CLOUD', raising=False)
    with database.get_db_connection() as conn:
        conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic-only',100000)")
        seed_crowded_snapshot(conn)
    candidate = dict(ticker='TEST', company='Synthetic Corporation', technical_direction='BUY',
        technical_score=7, average_dollar_volume=1e9, atr=1, atr_pct=1, entry=100,
        price_as_of='2026-10-05', price_zones=[zone(98,98.4), zone(104.65,105)])
    state = {}
    monkeypatch.setattr(scanner, 'read_state', lambda: dict(state))
    monkeypatch.setattr(scanner, 'save_state', lambda value: state.update(value))
    monkeypatch.setattr(scanner, 'load_universe', lambda: {'TEST':dict(company=candidate['company'], indexes=['synthetic'])})
    monkeypatch.setattr(scanner, 'load_historical_data', lambda *a: ({'TEST':object()}, {'status':'synthetic'}))
    monkeypatch.setattr(scanner, '_market_context', lambda *a: {})
    monkeypatch.setattr(scanner, 'analyze_history', lambda *a: dict(candidate))
    monkeypatch.setattr(scanner, '_read_news_cache', lambda: {})
    monkeypatch.setattr(scanner, '_write_news_cache', Mock())
    monkeypatch.setattr(scanner, 'fetch_recent_news', Mock(return_value=[]))
    monkeypatch.setattr(scanner, 'research_reference_quote', Mock(return_value=None))
    monkeypatch.setattr(scanner, 'regular_session_open', lambda: True)
    monkeypatch.setattr(scanner, 'current_intraday_quote', lambda *a: (100, clock.instant.isoformat()))
    monkeypatch.setattr(scanner, '_localize_telegram_signal', lambda signal: dict(signal, telegram_reason_he='בדיקה מבודדת', telegram_news_he=[]))
    monkeypatch.setattr('ai_budget.check', Mock())
    monkeypatch.setattr('telegram_status.refresh_telegram_status_cards', Mock())
    response = Mock()
    response.json.return_value = {'signal_id':1234}
    session = Mock(headers={})
    session.request.return_value = response
    monkeypatch.setattr(scanner.requests, 'Session', lambda: session)
    review = Mock(return_value=dict(action='BUY', confidence=.91, news_sentiment=.3,
        news_relevance=.9, time_horizon='1-4 weeks', reason='Synthetic verified evidence'))
    monkeypatch.setattr(scanner, 'ai_review', review)
    return candidate, review, session


def rows(query):
    with database.get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query)]


def test_recovered_evidence_reaches_real_pending_entry_fill_exit_and_restart(db, clock, monkeypatch):
    candidate, review, session = prepare(monkeypatch, clock)
    result = scanner.run_scan()
    assert result['signals_published'] == 1
    assert review.call_count == 1
    assert review.call_args.args[1][0]['canonical_event_id'] == 'company-story'
    assert rows('SELECT status FROM scanner_orders') == [{'status':'pending'}]
    assert not rows('SELECT id FROM scanner_trades')  # Signal is not a position.
    assert not rows('SELECT id FROM scanner_fills')
    clock.instant = datetime(2026,10,6,14,10,tzinfo=timezone.utc)
    entry = dict(at='2026-10-06T14:05:00Z',open=100,high=101,low=99.5,close=100)
    engine.process_bar('TEST',entry)
    assert len(rows('SELECT id FROM scanner_trades')) == 1
    assert rows('SELECT status FROM scanner_orders') == [{'status':'filled'}]
    clock.instant = datetime(2026,10,6,14,15,tzinfo=timezone.utc)
    exit_bar = dict(at='2026-10-06T14:10:00Z',open=104.5,high=105,low=104,close=104.5)
    engine.process_bar('TEST',exit_bar)
    engine.initialize_runtime()
    engine.process_bar('TEST',entry)
    engine.process_bar('TEST',exit_bar)
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    assert rows('SELECT remaining_quantity,status FROM scanner_trades') == [{'remaining_quantity':0,'status':'closed'}]
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    scanner.run_scan()  # Saved cooldown prevents another analysis/order.
    assert review.call_count == 1
    assert len(rows('SELECT id FROM scanner_orders')) == 1
    assert all(call.args[0] == 'POST' and call.args[1].endswith('/signals/strategy')
               for call in session.request.call_args_list)


@pytest.mark.parametrize('block', ['hold','confidence','quote','session','targets'])
def test_recovered_evidence_cannot_bypass_remaining_admission_gates(db, clock, monkeypatch, block):
    candidate, review, _ = prepare(monkeypatch, clock)
    if block == 'hold': review.return_value['action'] = 'HOLD'
    if block == 'confidence': review.return_value['confidence'] = .79
    if block == 'quote': monkeypatch.setattr(scanner,'current_intraday_quote',lambda *a:None)
    if block == 'session': monkeypatch.setattr(scanner,'regular_session_open',lambda:False)
    if block == 'targets': candidate['price_zones'] = [zone(98,98.4),zone(102,103)]
    result = scanner.run_scan()
    assert result['signals_published'] == 0 and result['rejected']
    assert not rows('SELECT id FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')
    if block in {'quote','session','targets'}:
        review.assert_not_called()
