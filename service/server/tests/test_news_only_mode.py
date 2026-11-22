"""News-only operational controls: synthetic state, no providers or messages."""
import asyncio
from datetime import timedelta
from unittest.mock import Mock

import pytest

import entry_emergency
import scanner_engine as engine
import stock_scanner as scanner
from test_signal_inputs import db, clock
from test_signal_admission_chain import prepare, rows
from test_entry_emergency import candle


def test_news_only_direct_scan_does_not_initialize_fetch_or_call_ai(monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    initialize = Mock(side_effect=AssertionError('No trading initialization'))
    fetch = Mock(side_effect=AssertionError('No trading market download'))
    review = Mock(side_effect=AssertionError('No trading inference'))
    monkeypatch.setattr(engine, 'initialize_runtime', initialize)
    monkeypatch.setattr(scanner, 'load_universe', fetch)
    monkeypatch.setattr(scanner, 'ai_review', review)
    assert scanner.run_scan() == dict(status='news_only', signals_published=0, ai_reviewed=0)
    initialize.assert_not_called(); fetch.assert_not_called(); review.assert_not_called()


def test_news_mode_blocks_resume_before_any_control_write(monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    with pytest.raises(ValueError, match='news_only_mode'):
        entry_emergency.set_paused(False, 0)


def test_public_trading_status_is_disabled_while_news_global_stays_enabled(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_ENABLED', 'true')
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setattr(scanner, 'read_state', lambda: {'mode': 'paper', 'status': 'scanning'})
    status = scanner.public_status()
    assert status['operation_mode'] == status['mode'] == 'news_only'
    assert not status['enabled'] and status['status'] == 'disabled'


def test_mode_blocks_entry_even_without_saved_pause(monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    cur = Mock(side_effect=AssertionError('No DB needed to deny a news-only entry'))
    assert entry_emergency.check(cur) == dict(allowed=False, reason='news_only_mode')
    cur.execute.assert_not_called()


def test_pending_entry_stays_unfilled_across_restart_in_news_mode(db, clock, monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'paper')
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', candle())
    engine.initialize_runtime()
    engine.process_bar('TEST', candle())
    assert not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')


def test_existing_position_tp_still_executes_in_news_mode(db, clock, monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'paper')
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', candle())
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    clock.instant += timedelta(minutes=5)
    engine.process_bar('TEST', dict(at='2026-10-06T14:10:00Z', open=104.5, high=105, low=104, close=104.5))
    assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [dict(status='closed', remaining_quantity=0)]
    assert len(rows('SELECT id FROM scanner_fills')) == 2


def test_news_mode_scanner_task_stays_alive_without_running_scan(monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_ENABLED', 'true')
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    run = Mock(side_effect=AssertionError('Trading discovery disabled'))
    status = Mock(); save = Mock()
    monkeypatch.setattr(scanner, 'run_scan', run)
    monkeypatch.setattr(scanner, 'read_state', lambda: {})
    monkeypatch.setattr(scanner, 'save_state', save)
    monkeypatch.setattr(engine, 'set_service_status', status)
    async def sleep(seconds):
        if seconds != 20:
            raise asyncio.CancelledError()
    monkeypatch.setattr(scanner.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scanner.stock_scanner_loop())
    run.assert_not_called()
    assert save.call_args.args[0]['mode'] == 'news_only'
    assert status.call_args.args[:2] == ('scan', 'disabled')


@pytest.mark.parametrize('mode', ['typo', '', 'live', 'NEWS'])
def test_invalid_mode_fails_closed_for_entry_and_scan(monkeypatch, mode):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', mode)
    with pytest.raises(ValueError, match='invalid_operation_mode'):
        scanner.run_scan()
    assert not entry_emergency.check(Mock())['allowed']
