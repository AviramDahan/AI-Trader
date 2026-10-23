"""Actual PG general-news outbox boundary; synthetic sources, no sends or AI."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from test_news_events_runtime import live
from news_events.engine import Analysis, Pipeline
from news_events.store import Store
from news_events import runtime
from signal_news import existing_news


def admit(live):
    p, src, result, at, members = live
    result = {**result, 'title_he': 'חברת רובוטיקה מדווחת על סגירת מפעל',
              'summary_he': 'החברה דיווחה על סגירת מפעל לאחר אובדן חוזה אספקה.',
              'interpretation_he': 'הדיווח עשוי להשפיע על הייצור ועל כוח האדם.'}
    members[0].add('AAPL')
    src = replace(src, title='Example Robotics announces regional factory closure',
                  source_excerpt='Example Robotics announced closure of its regional factory after losing a supply contract and provided details about affected production and staff.',
                  event_type='business_update', tickers=('AAPL',))
    eid = p.ingest(src, at)
    assert p.store.event(eid)['status'] == 'pending'
    assert p.analyze(eid, lambda _: Analysis(result), at) == 'done'
    return p, eid, at, members


def test_pg_general_outbox_projection_restart_and_scanner_isolation(live, monkeypatch):
    p, eid, at, members = admit(live)
    nid = runtime.project(p, eid, at)
    assert runtime.queue_outbox(p, eid, at) == 1
    assert runtime.queue_outbox(p, eid, at) == 0
    with p.store.transaction() as c:
        projected = c.execute('SELECT * FROM scanner_news WHERE id=?', (nid,)).fetchone()
        assert projected['ticker'] is None and json.loads(projected['verified_tickers_json']) == []
        assert projected['scope'] == 'market' and projected['news_category'] == 'company'
        outbox = dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
        assert outbox['event_type'] == 'market_news'
        for table in ('scanner_news_jobs', 'scanner_trade_news', 'scanner_signals', 'scanner_orders', 'scanner_trades', 'scanner_fills'):
            assert c.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] == 0
    assert runtime.delivery_message(outbox)
    assert 'מניות:' not in runtime.delivery_message(outbox)
    assert existing_news([{'ticker': 'AAPL', 'company': 'Apple Inc.'}], 6, at) == {'AAPL': []}
    restarted = Pipeline(Store(p.store.connect, production=True), p.universe,
                         lambda: members, not_before=p.not_before)
    monkeypatch.setattr(runtime, 'pipeline', lambda: restarted)
    assert runtime.queue_outbox(restarted, eid, at) == 0
    assert runtime.delivery_message(outbox)


@pytest.mark.parametrize('change', ['rights', 'excerpt', 'kind', 'conflict', 'version', 'retracted', 'epoch', 'expiry', 'destination'])
def test_pg_pending_general_delivery_revalidates_every_boundary(live, monkeypatch, change):
    p, eid, at, _ = admit(live)
    assert runtime.queue_outbox(p, eid, at) == 1
    with p.store.transaction() as c:
        outbox = dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
    assert runtime.delivery_message(outbox)
    if change == 'expiry':
        monkeypatch.setattr(runtime, 'now', lambda: at + timedelta(hours=7))
    elif change == 'destination':
        monkeypatch.setenv('TELEGRAM_MARKET_NEWS_THREAD_ID', '424242')
    elif change == 'retracted':
        p.store.withdraw('licensed', 'one', at)
    else:
        with p.store.transaction(True) as c:
            if change == 'epoch':
                c.execute('UPDATE ne_control SET epoch=epoch+1 WHERE id=1')
            elif change == 'version':
                c.execute("UPDATE ne_events SET evidence_version='corrected' WHERE event_id=?", (eid,))
            else:
                body = p.store.event(eid)['body']
                if change == 'rights': body['sources'][0]['rights'] = 'review_required'
                if change == 'excerpt': body['sources'][0]['source_excerpt'] = ''
                if change == 'kind': body['event_type'] = 'unknown'
                if change == 'conflict': body['conflicts'] = ['contradictory facts']
                c.execute('UPDATE ne_events SET body_json=? WHERE event_id=?', (json.dumps(body), eid))
    assert runtime.delivery_message(outbox) is None


def test_pg_current_projection_clears_obsolete_stock_attribution(live):
    p, eid, at, _ = admit(live)
    nid = runtime.project(p, eid, at)
    # Model an obsolete retained view, not an invented financial transaction.
    with p.store.transaction(True) as c:
        c.execute("UPDATE scanner_news SET ticker='AAPL',verified_tickers_json='[\"AAPL\"]',scope='open_position',news_category='macro' WHERE id=?", (nid,))
    assert runtime.project(p, eid, at) == nid
    with p.store.transaction() as c:
        row = c.execute('SELECT ticker,verified_tickers_json,scope,news_category FROM scanner_news WHERE id=?', (nid,)).fetchone()
        assert row['ticker'] is None and json.loads(row['verified_tickers_json']) == []
        assert row['scope'] == 'market' and row['news_category'] == 'company'


def test_pg_later_verified_identity_cannot_duplicate_same_exact_public_story(live, monkeypatch):
    p, eid, at, _ = admit(live)
    monkeypatch.setenv('TELEGRAM_MARKET_NEWS_THREAD_ID', '42')
    monkeypatch.setenv('TELEGRAM_STOCK_NEWS_THREAD_ID', '42')
    assert runtime.queue_outbox(p, eid, at) == 1
    with p.store.transaction(True) as c:
        c.execute("UPDATE scanner_telegram_outbox SET status='sent'")
    original = p.store.event(eid)['body']['sources'][0]
    from news_events.model import Source
    p.universe['EXRB'] = {'company': 'Example Robotics'}
    observed = replace(Source(**original), provider_id='another_licensed', source_id='second')
    second = p.ingest(observed, at)
    assert second != eid  # Publication dedupe does not silently merge audits.
    assert p.store.event(second)['body']['tickers'] == ['EXRB']
    assert p.analyze(second, lambda _: Analysis(live[2]), at) == 'done'
    assert runtime.queue_outbox(p, second, at) == 0
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n'] == 1
        assert c.execute('SELECT status FROM ne_delivery WHERE event_id=?', (second,)).fetchone()['status'] == 'duplicate'
    # A different actual destination is not the same publication.
    monkeypatch.setenv('TELEGRAM_STOCK_NEWS_THREAD_ID', '43')
    # Existing duplicate row is deliberately not requeued when configuration
    # changes. A genuinely new event remains governed by ordinary routing.
    assert runtime.queue_outbox(p, second, at) == 0
