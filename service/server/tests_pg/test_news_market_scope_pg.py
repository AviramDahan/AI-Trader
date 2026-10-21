"""Real isolated PostgreSQL, synthetic reviewer; never sends or infers live."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("corrected", [True, False])
def test_market_scope_review_persists_without_repeat_or_trading(pg, monkeypatch, corrected):
    from database import get_db_connection
    from news_events.analysis import CanonicalAnalyzer
    from news_events.engine import Pipeline
    from news_events.model import Source
    from news_events.runtime import queue_outbox
    from news_events.store import Store

    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    monkeypatch.setenv("NEWS_EVENTS_RUNTIME", "true")
    with get_db_connection() as c:
        # The opt-in pg fixture creates a fresh test_* schema, never Production.
        assert c.execute("SELECT current_schema() AS name").fetchone()["name"].startswith("test_")
        c.execute(
            "UPDATE ne_control SET mode='canonical',not_before=?,epoch=42 WHERE id=1",
            ((now - timedelta(days=1)).isoformat(),),
        )
    store = Store(get_db_connection, production=True)
    pipeline = Pipeline(store, {}, lambda: (set(), set()), not_before=now - timedelta(days=1))
    source = Source(
        "synthetic_primary", "market-fixture", "https://example.invalid/news/policy",
        "Synthetic primary", now.isoformat(), now.isoformat(),
        "Central bank announces a policy decision",
        "The central bank announces its latest policy decision and explains the available economic evidence.",
        event_type="market", rights="approved",
    )
    eid = pipeline.ingest(source, now)
    initial = dict(
        related=False, title_he="הבנק המרכזי פרסם החלטת מדיניות",
        summary_he="הבנק פרסם את החלטתו והסביר את הרקע הכלכלי.",
        interpretation_he="זהו מידע כלכלי ולא המלצת מסחר.",
        sentiment="neutral", materiality="medium", relevance=.4,
    )
    review = dict(
        faithful=True, fluent_hebrew=True, unsupported_claims=False,
        duplicate_of=0, material_new_fact=False, explanation="מידע כלכלי רלוונטי לשוק",
        scope_related=True,
    )
    completion = Mock(side_effect=[
        (initial, {}), (review, {}), ({**initial, "related": corrected}, {}), (review, {}),
    ])
    outcome = pipeline.analyze(eid, CanonicalAnalyzer(completion), now)
    assert outcome == ("done" if corrected else "failed")
    assert [call.args[0] for call in completion.call_args_list] == [
        "source_analysis", "quality_review", "editorial_repair", "repair_review",
    ]
    assert completion.call_count == 4 and initial["related"] is False
    assert queue_outbox(pipeline, eid, now) == int(corrected)
    record = pipeline.store.event(eid)
    if corrected:
        assert record["status"] == "analyzed"
    else:
        assert record["status"] == "quality_failed"
        assert record["reason"] == "news_quality_rejected:scope_related_consistent"

    restarted = Pipeline(
        Store(get_db_connection, production=True), {}, pipeline.membership,
        not_before=pipeline.not_before,
    )
    # Same source/version and a process restart do not claim another model job.
    assert restarted.ingest(source, now + timedelta(seconds=1)) == eid
    repeated = restarted.analyze(eid, CanonicalAnalyzer(completion), now + timedelta(seconds=1))
    assert repeated == ("done" if corrected else "quality_failed")
    assert queue_outbox(restarted, eid, now + timedelta(seconds=1)) == 0
    assert completion.call_count == 4
    with store.transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM ne_events").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM ne_analysis").fetchone()["n"] == 1
        assert c.execute("SELECT count(*) AS n FROM ne_delivery").fetchone()["n"] == int(corrected)
        assert c.execute("SELECT count(*) AS n FROM ne_outbox").fetchone()["n"] == int(corrected)
        assert c.execute("SELECT count(*) AS n FROM scanner_telegram_outbox").fetchone()["n"] == int(corrected)
        if corrected:
            row = c.execute("SELECT event_type,status,attempts FROM scanner_telegram_outbox").fetchone()
            assert dict(row) == {"event_type": "market_news", "status": "pending", "attempts": 0}
        assert c.execute("SELECT count(*) AS n FROM scanner_fills").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM scanner_trades").fetchone()["n"] == 0
