from datetime import datetime, timedelta, timezone

import database
import news_pipeline
from scanner_engine import set_news_watchlist


def test_watchlist_same_fact_survives_separate_source_and_does_not_block_new_fact(pg, monkeypatch):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED', 'true')
    monkeypatch.delenv('NEWS_EVENTS_RUNTIME', raising=False)
    monkeypatch.delenv('NEWS_EVIDENCE_ENABLED', raising=False)
    set_news_watchlist('NVDA', 'NVIDIA Corporation')
    at = datetime(2026, 11, 24, 14, tzinfo=timezone.utc)

    def analyzer(rows):
        return [dict(id=row['id'], related=True, title_he='עדכון חברה', summary_he='החברה פרסמה עדכון.',
                     materiality='high', sentiment='positive', relevance=.98, thesis_effect='unchanged')
                for row in rows]

    titles = [
        'NVIDIA board reinstates Jensen Huang as CEO',
        'Nvidia shares jump as Jensen Huang returns as CEO',
        'NVIDIA has formed a national security and export control committee',
    ]
    for i, title in enumerate(titles):
        now = at + timedelta(minutes=i)
        news_pipeline.ingest_items([dict(title=title, url=f'https://example.test/edit/{i}',
          provider='yahoo_priority', publisher='Fixture Wire', tickers=['NVDA'], published_at=now.isoformat())], now)
        news_pipeline.analyze_news_jobs(analyzer=analyzer, at=now)
    with database.get_db_connection() as conn:
        queued = conn.execute("SELECT dedupe_key FROM scanner_telegram_outbox WHERE event_type='watchlist_news'").fetchall()
        assert len(queued) == 2
