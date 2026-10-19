"""Actual shared-lock/CAS PAPER entry stop in disposable test_* PG schemas."""
from datetime import timedelta
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import database
import entry_emergency as emergency
import scanner_engine as engine
import stock_scanner as scanner
from test_signal_inputs import clock
from test_signal_admission_chain import prepare, rows
from test_entry_emergency import (
    candle,
    test_shared_pause_blocks_new_baseline_order_before_any_signal_write as exercise_new_order,
    test_shared_pause_blocks_existing_baseline_limit_fill as exercise_pending_fill,
    test_resume_rejects_straddling_and_old_bars_then_allows_new_full_bar_once as exercise_resume,
    test_pause_does_not_hide_missing_unpaused_pre_stop_bar_or_release_hold as exercise_gap,
    test_only_explicit_paused_missing_bars_are_known_no_execution as exercise_covered_gap,
    test_close_long_order_can_be_created_and_filled_during_pause as exercise_close,
    test_short_pending_entry_is_blocked_then_original_contract_can_fill as exercise_short,
)


@pytest.fixture
def emergency_pg(pg):
    from news_events.store import Store
    Store(database.get_db_connection, sandbox=True).install()
    return pg


@pytest.mark.parametrize('exercise', [exercise_new_order, exercise_pending_fill, exercise_resume,
                                     exercise_gap, exercise_covered_gap, exercise_close, exercise_short])
def test_pg_emergency_entry_lifecycle(emergency_pg, clock, monkeypatch, exercise):
    exercise(None, clock, monkeypatch)


def test_pg_two_operator_cas_writers_cannot_both_advance_same_revision(emergency_pg, clock, monkeypatch):
    prepare(monkeypatch, clock)
    started = threading.Barrier(3)
    outcomes = []
    def change():
        started.wait(timeout=10)
        try:
            outcomes.append(('success', emergency.set_paused(True, 0, now=clock.instant)['revision']))
        except ValueError as exc:
            outcomes.append(('blocked', str(exc)))
    workers = [threading.Thread(target=change) for _ in range(2)]
    for worker in workers: worker.start()
    started.wait(timeout=10)
    for worker in workers: worker.join(timeout=15)
    assert not any(worker.is_alive() for worker in workers)
    assert sorted(outcomes) == [('blocked', 'entry_emergency_revision_conflict'), ('success', 1)]
    with database.get_db_connection() as conn:
        state = emergency.snapshot(conn.cursor(), now=clock.instant)
    assert state['revision'] == 1 and state['paused'] and len(state['intervals']) == 1


@pytest.mark.parametrize('operation', ['new_order', 'pending_fill'])
def test_pg_acknowledged_pause_wins_against_already_started_entry_waiting_for_same_lock(
        emergency_pg, clock, monkeypatch, operation):
    candidate, review, _ = prepare(monkeypatch, clock)
    engine.initialize_runtime()
    signal = scanner._paper_order(candidate, review.return_value, [],
        (100, clock.instant.isoformat()), {}, scanner.settings(), None)
    if operation == 'pending_fill':
        assert scanner.run_scan()['signals_published'] == 1
        clock.instant += timedelta(minutes=10)
    acquired, writer_waiting, release = threading.Event(), threading.Event(), threading.Event()
    original_snapshot = emergency.snapshot
    original_begin = engine.begin_write_transaction
    outcomes = []
    def controlled_snapshot(cur, *, now=None):
        if threading.current_thread().name == 'pause-control':
            acquired.set()
            assert release.wait(timeout=10), 'test did not release pause writer'
        return original_snapshot(cur, now=now)
    def tracked_begin(cur):
        if threading.current_thread().name == 'entry-writer':
            writer_waiting.set()
        return original_begin(cur)
    monkeypatch.setattr(emergency, 'snapshot', controlled_snapshot)
    monkeypatch.setattr(engine, 'begin_write_transaction', tracked_begin)
    def pause():
        try:
            state = emergency.set_paused(True, 0, now=clock.instant)
            outcomes.append(('pause', state['revision']))
        except Exception as exc:
            outcomes.append(('pause_error', type(exc).__name__))
    def writer():
        try:
            if operation == 'new_order':
                engine.record_signal(signal, candidate, review.return_value, {}, 'waiting-before-pause-ack')
            else:
                engine.process_bar('TEST', candle())
            outcomes.append(('writer', 'returned'))
        except ValueError as exc:
            outcomes.append(('writer', str(exc)))
    pausing = threading.Thread(target=pause, name='pause-control')
    waiting = threading.Thread(target=writer, name='entry-writer')
    try:
        pausing.start()
        assert acquired.wait(timeout=10), 'pause did not acquire global writer lock'
        waiting.start()
        assert writer_waiting.wait(timeout=10), 'entry did not attempt global writer lock'
        assert waiting.is_alive()
    finally:
        release.set()
        pausing.join(timeout=15)
        if waiting.ident is not None: waiting.join(timeout=15)
    assert not pausing.is_alive() and not waiting.is_alive()
    assert ('pause', 1) in outcomes
    assert not rows('SELECT id FROM scanner_trades') and not rows('SELECT id FROM scanner_fills')
    if operation == 'new_order':
        assert ('writer', 'entry_emergency_paused') in outcomes
        assert not rows('SELECT id FROM scanner_signals') and not rows('SELECT id FROM scanner_orders')
    else:
        assert ('writer', 'returned') in outcomes
        assert rows('SELECT status FROM scanner_orders') == [{'status': 'pending'}]
