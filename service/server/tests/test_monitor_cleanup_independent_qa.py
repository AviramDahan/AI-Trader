"""Independent exception-boundary checks; no database, provider or AI calls."""
from unittest.mock import Mock

import pytest


BAR = dict(at='2026-11-03T15:00:00Z', open=100, high=101, low=99, close=100)


@pytest.fixture
def bar_boundary(monkeypatch):
    import requests
    import scanner_engine as engine
    monkeypatch.setattr(requests.sessions.Session, 'request',
                        lambda *_a, **_k: pytest.fail('No external HTTP in cleanup QA'))
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    acquisition = Mock(return_value=connection)
    monkeypatch.setattr(engine, 'get_db_connection', acquisition)
    monkeypatch.setattr(engine, 'begin_write_transaction', Mock())
    monkeypatch.setattr(engine, 'now_z', lambda: '2026-11-03T15:10:00Z')
    monkeypatch.setattr(engine, 'store_quote', Mock())
    return engine, connection, cursor, acquisition


@pytest.mark.parametrize('stage', ['cursor', 'begin', 'query', 'quote_write', 'commit'])
def test_retained_failure_closes_exactly_once_without_retry_or_error_replacement(bar_boundary, stage):
    engine, connection, cursor, acquisition = bar_boundary
    failure = RuntimeError('independent synthetic boundary failure')
    retained = [connection, failure]
    if stage == 'cursor':
        connection.cursor.side_effect = failure
    elif stage == 'begin':
        engine.begin_write_transaction.side_effect = failure
    elif stage == 'query':
        cursor.execute.side_effect = failure
    elif stage == 'quote_write':
        engine.store_quote.side_effect = failure
    else:
        connection.commit.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        engine.process_bar('TEST', dict(BAR))
    assert caught.value is retained[1]
    acquisition.assert_called_once()
    retained[0].close.assert_called_once()
    assert connection.commit.call_count == int(stage == 'commit')


def test_replay_rollback_failure_still_closes_and_propagates(bar_boundary):
    engine, connection, cursor, _ = bar_boundary
    cursor.fetchone.return_value = {'last_bar_at': BAR['at']}
    failure = RuntimeError('independent synthetic rollback failure')
    connection.rollback.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        engine.process_bar('TEST', dict(BAR))
    assert caught.value is failure
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    connection.commit.assert_not_called()
    engine.store_quote.assert_not_called()


def test_incomplete_v2_bar_rolls_back_without_quote_or_cursor_commit(bar_boundary, monkeypatch):
    import single_target_policy
    engine, connection, cursor, _ = bar_boundary
    monkeypatch.setattr(engine, 'now_z', lambda: '2026-11-03T15:03:00Z')
    monkeypatch.setattr(single_target_policy, 'is_single', lambda _plan: True)
    cursor.fetchall.side_effect = [[{'plan_json': '{}'}], []]
    engine.process_bar('TEST', dict(BAR))
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    connection.commit.assert_not_called()
    engine.store_quote.assert_not_called()


def test_exit_processing_failure_closes_before_exception_escapes(bar_boundary, monkeypatch):
    engine, connection, cursor, _ = bar_boundary
    cursor.fetchall.side_effect = [[], [{'signal_id': 1, 'last_bar_at': '2026-11-03T14:55:00Z'}]]
    failure = RuntimeError('independent synthetic protective-exit failure')
    exits = Mock(side_effect=failure)
    monkeypatch.setattr(engine, '_process_trade_bar', exits)
    with pytest.raises(RuntimeError) as caught:
        engine.process_bar('TEST', dict(BAR))
    assert caught.value is failure
    exits.assert_called_once()
    connection.close.assert_called_once()
    connection.commit.assert_not_called()
    engine.store_quote.assert_not_called()


def test_success_keeps_explicit_commit_before_single_close(bar_boundary):
    engine, connection, _, _ = bar_boundary
    engine.process_bar('TEST', dict(BAR))
    connection.commit.assert_called_once()
    connection.close.assert_called_once()
    connection.rollback.assert_not_called()
    engine.store_quote.assert_called_once()
    assert connection.mock_calls.index(('commit', (), {})) < connection.mock_calls.index(('close', (), {}))


def test_invalid_bar_never_acquires_a_transaction(bar_boundary):
    engine, connection, _, acquisition = bar_boundary
    with pytest.raises(ValueError, match='Invalid OHLC'):
        engine.process_bar('TEST', dict(BAR, high=98))
    acquisition.assert_not_called()
    connection.close.assert_not_called()
