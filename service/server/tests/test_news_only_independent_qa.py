"""Independent news-only safety checks on actual entry/exit paths, synthetic IO."""
import asyncio
from datetime import datetime, timedelta, timezone
import socket
from unittest.mock import Mock
from types import SimpleNamespace

import pytest
import requests

import database
import entry_emergency
import operation_mode
import scanner_engine as engine
import stock_scanner as scanner
from test_signal_inputs import db, clock
from test_signal_admission_chain import prepare, rows


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Independent news-only tests prohibit external IO')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)
    monkeypatch.delenv('AI_TRADER_OPERATION_MODE', raising=False)


def test_direct_scan_returns_before_initialization_data_and_model(monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setenv('STOCK_SCANNER_ENABLED', 'true')
    forbidden = Mock(side_effect=AssertionError('News-only scan must be a no-op'))
    for obj, name in ((engine, 'initialize_runtime'), (scanner, 'load_universe'),
                      (scanner, 'load_historical_data'), (scanner, 'ai_review'),
                      (scanner, 'read_state'), (database, 'get_db_connection')):
        monkeypatch.setattr(obj, name, forbidden)
    result = scanner.run_scan()
    assert result['status'] == 'news_only'
    assert result['signals_published'] == result['ai_reviewed'] == 0
    forbidden.assert_not_called()


@pytest.mark.parametrize('mode', ['news_only', 'invalid-mode'])
def test_mode_stops_entries_even_without_any_durable_control_row(monkeypatch, mode):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', mode)
    cur = Mock(side_effect=AssertionError('Mode guard must precede database read'))
    result = entry_emergency.check(cur, bar_at='2026-10-06T14:05:00Z')
    assert not result['allowed']
    assert result['reason'] in {'news_only_mode', 'entry_emergency_control_invalid'}
    cur.execute.assert_not_called()


def test_news_only_cannot_resume_entries_or_create_an_implicit_control_row(db, monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    with pytest.raises(ValueError, match='news_only_mode'):
        entry_emergency.set_paused(False, 0)
    assert not rows("SELECT key FROM scanner_settings WHERE key='paper_entry_emergency_v1'")


def test_actual_pending_entry_cannot_fill_after_restart_without_pause_row(db, clock, monkeypatch):
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    original = rows('SELECT plan_json,valid_until,limit_price FROM scanner_orders')
    balances = rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
    assert not rows("SELECT key FROM scanner_settings WHERE key='paper_entry_emergency_v1'")
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    clock.instant = datetime(2026, 10, 6, 14, 10, tzinfo=timezone.utc)
    candle = dict(at='2026-10-06T14:05:00Z', open=100, high=101, low=99.5, close=100)
    engine.initialize_runtime()
    engine._pending_recovery_check('TEST', [candle], clock.instant)
    engine.process_bar('TEST', candle)
    engine.initialize_runtime()
    engine.process_bar('TEST', candle)
    assert not rows('SELECT id FROM scanner_trades')
    assert not rows('SELECT id FROM scanner_fills')
    assert rows('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts') == balances
    assert rows('SELECT plan_json,valid_until,limit_price FROM scanner_orders') == original


def test_internal_trade_creation_guard_cannot_be_bypassed_by_missing_pause(monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    cur = Mock()
    engine._create_trade_rows(cur, {'purpose': 'entry'}, 100, '2026-10-06T14:05:00Z')
    cur.execute.assert_not_called()


@pytest.mark.parametrize('exit_kind', ['tp', 'stop'])
def test_existing_position_tp_sl_survives_news_only_and_restart(db, clock, monkeypatch, exit_kind):
    prepare(monkeypatch, clock)
    assert scanner.run_scan()['signals_published'] == 1
    clock.instant += timedelta(minutes=10)
    engine.process_bar('TEST', dict(at='2026-10-06T14:05:00Z', open=100, high=101, low=99.5, close=100))
    assert rows('SELECT status FROM scanner_trades') == [{'status': 'open'}]
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    engine.initialize_runtime()
    clock.instant += timedelta(minutes=5)
    if exit_kind == 'tp':
        bar = dict(at='2026-10-06T14:10:00Z', open=104.5, high=105, low=104, close=104.5)
    else:
        bar = dict(at='2026-10-06T14:10:00Z', open=99.5, high=100, low=90, close=98)
    engine.process_bar('TEST', bar)
    engine.process_bar('TEST', bar)
    assert rows('SELECT status,remaining_quantity FROM scanner_trades') == [dict(status='closed', remaining_quantity=0)]
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


@pytest.mark.parametrize('which', ['feed', 'ai', 'outbox'])
def test_news_workers_keep_running_with_global_flag_enabled(monkeypatch, which):
    import news_pipeline
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setenv('STOCK_SCANNER_ENABLED', 'true')
    calls = []
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError()

    async def to_thread(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    monkeypatch.setattr(scanner.asyncio, 'sleep', sleep)
    monkeypatch.setattr(scanner.asyncio, 'to_thread', to_thread)
    monkeypatch.setattr(news_pipeline, 'feed_settings', lambda: {'enabled': True, 'analysis_interval': 30})
    monkeypatch.setattr(news_pipeline, 'run_feed_cycle', lambda: calls.append('feed'))
    monkeypatch.setattr(news_pipeline, 'analyze_news_jobs', lambda: calls.append('ai') or {'analyzed': 1})
    monkeypatch.setattr(engine, 'process_telegram_outbox', lambda: calls.append('outbox'))
    callback = {'feed': scanner.stock_news_feed_loop, 'ai': scanner.stock_news_ai_loop,
                'outbox': scanner.stock_telegram_outbox_loop}[which]
    # All awaited operations above are synchronous synthetic coroutines. Step
    # the real worker coroutine directly, without creating Windows' socketpair.
    coroutine = callback()
    try:
        with pytest.raises(asyncio.CancelledError):
            coroutine.send(None)
    finally:
        coroutine.close()
    assert calls == [which]
    assert len(sleeps) == 2


def test_configured_portfolio_status_disable_never_builds_or_sends_card(monkeypatch):
    import telegram_status
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setenv('STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED', 'false')
    send = Mock(side_effect=AssertionError('Disabled portfolio status cannot send'))
    monkeypatch.setattr(telegram_status, '_upsert_pinned_message', send)
    monkeypatch.setattr(telegram_status, 'portfolio_status_message', send)
    assert telegram_status.refresh_telegram_status_cards() == {'portfolio': 'disabled', 'signals_status': 'disabled'}
    send.assert_not_called()


@pytest.mark.parametrize('action', ['buy', 'short', 'BUY', ' SHORT '])
def test_generic_and_follower_entry_helper_blocks_before_database(monkeypatch, action):
    import services
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    connection = Mock(side_effect=AssertionError('No new generic entry DB work'))
    monkeypatch.setattr(services, 'get_db_connection', connection)
    with pytest.raises(ValueError, match='news_only_mode'):
        services._update_position_from_signal(4, 'SYN', 'us-stock', action, 1, 20,
                                             '2026-10-06T14:05:00Z', leader_id=7)
    connection.assert_not_called()


@pytest.mark.parametrize('entry,exit_action', [('buy', 'sell'), ('short', 'cover')])
def test_generic_existing_long_and_short_can_still_close(db, monkeypatch, entry, exit_action):
    import services
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO agents(name,token,cash) VALUES('synthetic-general','synthetic',1000)")
        account = cur.lastrowid
        conn.commit()
    services._update_position_from_signal(account, 'SYN', 'us-stock', entry, 2, 20,
                                         '2026-10-06T14:05:00Z')
    assert len(rows('SELECT id FROM positions')) == 1
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    services._update_position_from_signal(account, 'SYN', 'us-stock', exit_action, 2, 20,
                                         '2026-10-06T14:10:00Z')
    assert not rows('SELECT id FROM positions')


@pytest.mark.parametrize('kind', ['individual', 'team'])
@pytest.mark.parametrize('side', ['buy', 'short'])
def test_challenge_entry_domain_functions_block_before_database(monkeypatch, kind, side):
    import challenges
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    db_call = Mock(side_effect=AssertionError('Challenge entry must stop before DB'))
    monkeypatch.setattr(challenges, 'get_db_connection', db_call)
    with pytest.raises(challenges.ChallengeError, match='news_only_mode'):
        if kind == 'team':
            challenges.create_challenge_team_trade('synthetic', 7, 4, {'side': side})
        else:
            challenges.create_challenge_trade('synthetic', 4, {'side': side})
    db_call.assert_not_called()


@pytest.mark.parametrize('action', ['buy', 'short'])
def test_authenticated_realtime_entry_api_rejects_before_price_experiment_or_writes(monkeypatch, action):
    from fastapi import FastAPI, HTTPException
    import routes_signals
    app = FastAPI()
    routes_signals.register_signal_routes(app, Mock())
    endpoint = next(route.endpoint for route in app.routes if route.path == '/api/signals/realtime')
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setattr(routes_signals, '_get_agent_by_token', lambda token: {'id': 4})
    forbidden = Mock(side_effect=AssertionError('Entry API must reject before any side effects'))
    monkeypatch.setattr(routes_signals, '_agent_experiment_context', forbidden)
    monkeypatch.setattr(routes_signals, 'get_db_connection', forbidden)
    coroutine = endpoint(SimpleNamespace(action=action), authorization='Bearer synthetic')
    try:
        with pytest.raises(HTTPException) as error:
            coroutine.send(None)
    finally:
        coroutine.close()
    assert error.value.status_code == 403 and error.value.detail == 'news_only_mode'
    forbidden.assert_not_called()


def test_authenticated_entry_resume_api_returns_conflict_without_durable_mutation(monkeypatch):
    from fastapi import FastAPI, HTTPException, Response
    import routes_scanner
    app = FastAPI()
    routes_scanner.register_scanner_routes(app)
    endpoint = next(route.endpoint for route in app.routes
                    if route.path == '/api/scanner/settings/entry-emergency' and 'PUT' in route.methods)
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setattr(routes_scanner, '_require_scanner_manager', lambda authorization: {'id': 4})
    db_call = Mock(side_effect=AssertionError('News-only resume cannot write control'))
    monkeypatch.setattr(database, 'get_db_connection', db_call)
    with pytest.raises(HTTPException) as error:
        endpoint(routes_scanner.EntryEmergencyRequest(paused=False, expected_revision=0),
                 Response(), authorization='Bearer synthetic')
    assert error.value.status_code == 409 and error.value.detail == 'news_only_mode'
    db_call.assert_not_called()


@pytest.mark.parametrize('action', ['sell', 'cover'])
def test_invalid_mode_still_preserves_entry_only_guard_semantics_for_exits(monkeypatch, action):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'invalid-mode')
    operation_mode.require_entry_allowed(action)


@pytest.mark.parametrize('which', ['sec', 'translation'])
def test_sec_and_translation_producers_remain_active_in_news_only(monkeypatch, which):
    import sec_intelligence
    import trump_truth_translation
    import trump_truth_media
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setenv('STOCK_SCANNER_ENABLED', 'true')
    calls, sleeps = [], []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError()

    async def to_thread(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    monkeypatch.setattr(scanner.asyncio, 'sleep', sleep)
    monkeypatch.setattr(scanner.asyncio, 'to_thread', to_thread)
    monkeypatch.setattr(scanner.asyncio, 'get_running_loop', lambda: SimpleNamespace(time=lambda: 1.))
    monkeypatch.setattr(engine, 'set_service_status', Mock())
    monkeypatch.setattr(sec_intelligence, 'mode', lambda: 'paper')
    monkeypatch.setattr(sec_intelligence, 'killed', lambda: False)
    monkeypatch.setattr(sec_intelligence, 'discover_cycle', lambda: calls.append('discover') or {'status': 'ok'})
    monkeypatch.setattr(sec_intelligence, 'process_jobs', lambda: calls.append('process') or {'failed': 0, 'processed': 1})
    monkeypatch.setattr(sec_intelligence, 'coverage_status', lambda: calls.append('coverage') or {
        'mapping_or_provider_errors': 0, 'unsupported_filings': 0, 'pending_filings': 0})
    monkeypatch.setattr(engine, 'ingest_market_news', lambda: calls.append('ingest'))
    monkeypatch.setattr(engine, 'translate_pending_news', lambda: calls.append('headlines'))
    monkeypatch.setattr(trump_truth_translation, 'prepare', lambda: calls.append('trump') or {'prepared': 0, 'deferred': 0})
    monkeypatch.setattr(trump_truth_media, 'prepare', lambda: calls.append('media') or {'prepared': 0})
    monkeypatch.setattr(trump_truth_translation, 'enabled', lambda: True)
    monkeypatch.setattr(trump_truth_media, 'enabled', lambda: True)
    coroutine = (scanner.stock_sec_intelligence_loop() if which == 'sec'
                 else scanner.stock_news_translation_loop())
    try:
        with pytest.raises(asyncio.CancelledError):
            coroutine.send(None)
    finally:
        coroutine.close()
    assert calls == (['discover', 'process', 'coverage'] if which == 'sec'
                     else ['ingest', 'headlines', 'trump', 'media'])
