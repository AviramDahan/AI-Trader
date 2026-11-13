"""Shared bilingual queue integration: isolated synthetic rows, no remote IO."""
import pytest
from unittest.mock import Mock

from test_trump_truth_media_outbox import db, insert, current, AT


@pytest.mark.parametrize('state', ['trump_bilingual_ready', 'trump_bilingual_retry'])
def test_bilingual_claim_returns_exact_durable_deadline_and_is_exclusive(db, state):
    import scanner_engine as e
    r = insert(db, state)
    rows = e._claim_telegram_outbox()
    assert len(rows) == 1 and rows[0]['id'] == r['id']
    assert rows[0]['status'] == 'trump_bilingual_sending'
    assert rows[0]['next_attempt_at'] == current(db, r)['next_attempt_at']
    assert rows[0]['next_attempt_at'] != r['next_attempt_at']
    assert e._claim_telegram_outbox() == []


@pytest.mark.parametrize('state', ['trump_bilingual_pending', 'trump_bilingual_preparing'])
def test_unprepared_bilingual_cannot_reach_generic_sender(db, state):
    import scanner_engine as e
    r = insert(db, state)
    assert e._claim_telegram_outbox() == []
    assert current(db, r)['status'] == state


def test_expired_bilingual_send_is_terminal_after_restart(db):
    import scanner_engine as e
    r = insert(db, 'trump_bilingual_sending', due='2000-01-01T00:00:00Z')
    assert e._claim_telegram_outbox() == []
    assert current(db, r)['status'] == 'failed'
    assert current(db, r)['last_error'] == 'trump_truth_delivery_unknown_manual_review'


@pytest.mark.parametrize(('result', 'expected'), [
    ('sent', 'sent'), ('missing_credentials', 'disabled'),
    ('{"terminal":true,"reason":"unknown"}', 'failed'),
    ('{"terminal":false,"retry_after":60}', 'trump_bilingual_retry'),
])
def test_bilingual_dispatch_owns_immutable_json_and_never_generic_fallback(db, monkeypatch, result, expected):
    import scanner_engine as e, stock_scanner, trump_truth_posts as t, trump_truth_bilingual as b
    r = insert(db, 'trump_bilingual_ready')
    dispatcher = Mock(return_value=result)
    monkeypatch.setattr(b, 'dispatch', dispatcher)
    monkeypatch.setattr(t, 'delivery_message', lambda *a, **k: pytest.fail('generic pre-render of bilingual JSON'))
    monkeypatch.setattr(stock_scanner, 'send_telegram', lambda *a, **k: pytest.fail('generic bilingual fallback'))
    e.process_telegram_outbox()
    assert dispatcher.call_count == 1
    assert dispatcher.call_args.args[0]['message'] == r['message']
    assert dispatcher.call_args.args[0]['status'] == 'trump_bilingual_sending'
    assert current(db, r)['message'] == r['message']
    assert current(db, r)['status'] == expected
    e.process_telegram_outbox()
    assert dispatcher.call_count == 1


def test_foreign_event_cannot_claim_bilingual_state(db):
    import scanner_engine as e
    r = insert(db, 'trump_bilingual_ready', event='news')
    assert e._claim_telegram_outbox() == []
    assert current(db, r)['status'] == 'trump_bilingual_ready'
