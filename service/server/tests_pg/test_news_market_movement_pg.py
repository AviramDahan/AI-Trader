"""Real isolated PostgreSQL publication queue, synthetic movement/reviewer only."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize('title,mode', [
    ('Nasdaq nears one-month low as chip shares slide on financing concerns', 'accepted'),
    ('Gold rebounds as yields dip and the dollar softens', 'accepted'),
    ('Nasdaq drops as chip shares retreat', 'quality_rejected'),
    ('Gold prices climb as the dollar weakens', 'below_threshold'),
])
def test_market_movement_existing_outbox_survives_restart_without_trading(pg, monkeypatch, title, mode):
    from database import get_db_connection
    from news_events.analysis import CanonicalAnalyzer
    from news_events.engine import Pipeline
    from news_events.model import Source, event_type
    from news_events.runtime import queue_outbox
    from news_events.store import Store

    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'true')
    with get_db_connection() as c:
        assert c.execute('SELECT current_schema() AS name').fetchone()['name'].startswith('test_')
        c.execute("UPDATE ne_control SET mode='canonical',not_before=?,epoch=73 WHERE id=1",
            ((now-timedelta(days=1)).isoformat(),))
    store = Store(get_db_connection, production=True)
    pipeline = Pipeline(store, {}, lambda:(set(), set()), not_before=now-timedelta(days=1))
    kind = event_type(title, '')
    assert kind == 'market'
    item = Source('synthetic_movement', 'fixture-only',
        'https://example.invalid/news/movement-10001', 'Synthetic publisher',
        now.isoformat(), now.isoformat(), title, '', event_type=kind, rights='approved')
    eid = pipeline.ingest(item, now)
    assert store.event(eid)['status'] == 'pending'
    draft = dict(related=True, title_he='נרשמה תנועה בשוק לפי דיווח סינתטי',
        summary_he='לפי הכותרת הסינתטית נרשמה תנועה בשוק על רקע המסחר.',
        interpretation_he='זהו תיאור מדווח ולא המלצת מסחר.',
        sentiment='neutral', materiality='low', relevance=.299 if mode=='below_threshold' else .4)
    review = dict(faithful=True, fluent_hebrew=True,
        unsupported_claims=mode=='quality_rejected', duplicate_of=0,
        material_new_fact=False, explanation='בדיקה סינתטית בלבד', scope_related=True)
    calls = [(draft, {}), (review, {})]
    if mode=='quality_rejected': calls += [(draft, {}), (review, {})]
    completion = Mock(side_effect=calls)
    expected = 'failed' if mode=='quality_rejected' else 'done'
    assert pipeline.analyze(eid, CanonicalAnalyzer(completion), now) == expected
    expected_outbox = int(mode=='accepted')
    assert queue_outbox(pipeline, eid, now) == expected_outbox
    assert completion.call_count == (4 if mode=='quality_rejected' else 2)
    with store.transaction() as c:
        assert c.execute('SELECT count(*) AS n FROM ne_analysis').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) AS n FROM ne_delivery').fetchone()['n'] == expected_outbox
        assert c.execute('SELECT count(*) AS n FROM ne_outbox').fetchone()['n'] == expected_outbox
        assert c.execute('SELECT count(*) AS n FROM scanner_telegram_outbox').fetchone()['n'] == expected_outbox
        if expected_outbox:
            row = c.execute('SELECT event_type,status,attempts FROM scanner_telegram_outbox').fetchone()
            assert dict(row) == dict(event_type='market_news', status='pending', attempts=0)
        for table in ('scanner_fills', 'scanner_orders', 'scanner_trades'):
            assert c.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] == 0

    restarted = Pipeline(Store(get_db_connection, production=True), {}, pipeline.membership,
        not_before=pipeline.not_before)
    assert restarted.ingest(item, now+timedelta(seconds=1)) == eid
    assert restarted.analyze(eid, CanonicalAnalyzer(completion), now+timedelta(seconds=1)) == (
        'quality_failed' if mode=='quality_rejected' else 'done')
    assert queue_outbox(restarted, eid, now+timedelta(seconds=1)) == 0
    assert completion.call_count == len(calls)
    with store.transaction() as c:
        assert c.execute('SELECT count(*) AS n FROM ne_analysis').fetchone()['n'] == 1
        assert c.execute('SELECT count(*) AS n FROM scanner_telegram_outbox').fetchone()['n'] == expected_outbox
