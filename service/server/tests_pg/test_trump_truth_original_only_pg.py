"""Original-only cutover on real isolated schema7; never remote IO/inference."""
import json
from unittest.mock import Mock

import pytest

from test_trump_truth_posts_pg import AT, relay


@pytest.mark.parametrize('status', ['trump_pending', 'trump_retry'])
def test_unclassified_old_entry_is_cancelled_before_send_and_stays_cancelled(relay, monkeypatch, status):
    import scanner_engine as engine
    import stock_scanner
    t, item, connect = relay
    assert item['publication_policy'] == t.ORIGINAL_POLICY
    assert t.ingest([item], AT)['inserted'] == 1
    with connect() as c:
        settings_before = [dict(r) for r in c.execute('SELECT * FROM scanner_settings ORDER BY key').fetchall()]
        row = dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        envelope = json.loads(row['message'])
        envelope['item'].pop('publication_policy')
        old_message = json.dumps(envelope)
        c.execute('UPDATE scanner_telegram_outbox SET message=?,status=? WHERE id=?',
                  (old_message, status, row['id']))
    sender = Mock(side_effect=AssertionError('unclassified old post must not send'))
    monkeypatch.setattr(stock_scanner, 'settings', lambda: {'telegram_enabled': True})
    monkeypatch.setattr(stock_scanner, 'send_telegram', sender)
    assert engine.process_telegram_outbox()['sent'] == 0
    assert engine.process_telegram_outbox()['sent'] == 0
    sender.assert_not_called()
    with connect() as c:
        retained = c.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone()
        assert retained['status'] == 'cancelled'
        assert retained['message'] == old_message  # Preserve the retained source/audit.
        assert [dict(r) for r in c.execute('SELECT * FROM scanner_settings ORDER BY key').fetchall()] == settings_before
        for table in ('scanner_orders', 'scanner_trades', 'scanner_signals', 'scanner_fills'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n'] == 0


def test_old_translation_preparation_cancels_without_inference_or_cache_rewrite(relay, monkeypatch):
    import trump_truth_translation as h
    t, item, connect = relay
    t.ingest([item], AT)
    with connect() as c:
        row = dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        envelope = json.loads(row['message'])
        envelope['item'].pop('publication_policy')
        old_message = json.dumps(envelope)
        c.execute('UPDATE scanner_telegram_outbox SET message=?,status=? WHERE id=?',
                  (old_message, h.PENDING, row['id']))
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
                  (h.cache_key(row), '{"retained":"synthetic-legacy-cache"}', AT.isoformat()))
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED', 'true')
    completion = Mock(side_effect=AssertionError('no inference for an unclassified old post'))
    assert h.prepare(at=AT, completion=completion)['prepared'] == 0
    completion.assert_not_called()
    with connect() as c:
        retained = c.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?', (row['id'],)).fetchone()
        assert retained['status'] == 'cancelled' and retained['message'] == old_message
        assert c.execute('SELECT value_json FROM scanner_settings WHERE key=?',
                         (h.cache_key(row),)).fetchone()['value_json'] == '{"retained":"synthetic-legacy-cache"}'
