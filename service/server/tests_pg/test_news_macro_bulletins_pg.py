from datetime import datetime, timedelta, timezone

import news_pipeline
from database import get_db_connection


def test_macro_release_is_deduplicated_across_relay_titles_on_postgres(pg, monkeypatch):
    monkeypatch.setenv("STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED", "true")
    monkeypatch.setenv("NEWS_EVENTS_RUNTIME", "false")
    now = datetime.now(timezone.utc)
    for index, title in enumerate((
        "JAPANESE PPI MOM ACTUAL 0.7% (FORECAST 0.3%, PREVIOUS -0.3%) $MACRO|FJ",
        "Japan PPI (M/M) Oct: 0.7% (est 0.3%; prev -0.3%)",
    )):
        at = now + timedelta(seconds=index)
        item = {"title": title, "source_excerpt": title, "provider": "telegram_channels",
                "publisher": "Synthetic Wire", "url": f"https://example.test/release/{index}",
                "published_at": news_pipeline._z(at), "source_kind": "telegram_post",
                "headline_only": False, "tickers": []}
        assert news_pipeline.ingest_items([item], at)["inserted"] == 1
        with get_db_connection() as conn:
            row = dict(conn.execute("SELECT * FROM scanner_news WHERE title=?", (title,)).fetchone())
            assert news_pipeline._queue_general_bulletin(
                conn.cursor(), row, {"title_he": "מדד ביפן"}, at, news_pipeline._z(at),
                translation_only=True) is (index == 0)
            conn.commit()
    with get_db_connection() as conn:
        messages = conn.execute("SELECT message FROM scanner_telegram_outbox WHERE event_type='market_news'").fetchall()
    assert len(messages) == 1 and "מדד מחירי היצרן" in messages[0]["message"]
