from datetime import datetime, timedelta, timezone

import pytest

import database
import news_pipeline
from scanner_engine import set_news_watchlist


@pytest.mark.parametrize(('ticker', 'company', 'titles', 'kept'), [
    ('NVDA', 'NVIDIA Corporation', [
        'NVIDIA board reinstates Jensen Huang as CEO',
        'Nvidia shares jump as Jensen Huang returns as CEO',
        'NVIDIA has formed a national security and export control committee',
    ], (0, 2)),
    ('MU', 'Micron Technology Inc.', [
        'Micron raises FY2027 revenue outlook to $30 billion',
        'Micron lifts FY2027 sales guidance to $30bn',
        'Micron raises FY2027 revenue forecast to $35 billion',
        'Micron cuts FY2027 capex outlook to $10 billion',
    ], (0, 2, 3)),
    ('GOOGL', 'Alphabet Inc.', [
        'Google agrees to buy Wiz for $32 billion',
        'Google signs deal to acquire Wiz for $32bn',
        'Alphabet completes its acquisition of Wiz for $32 billion',
    ], (0, 2)),
    ('NVDA', 'NVIDIA Corporation', [
        'U.S. Commerce Department imposes export restrictions on Nvidia H200 chips to China',
        'BIS imposes export curbs on Nvidia H200 chips to China',
        'BIS expands export restrictions on Nvidia H200 chips to China',
    ], (0, 2)),
])
def test_watchlist_same_fact_survives_separate_source_and_does_not_block_new_fact(
        pg, monkeypatch, ticker, company, titles, kept):
    monkeypatch.setenv('AI_TRADER_OPERATION_MODE', 'news_only')
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED', 'true')
    monkeypatch.delenv('NEWS_EVENTS_RUNTIME', raising=False)
    monkeypatch.delenv('NEWS_EVIDENCE_ENABLED', raising=False)
    set_news_watchlist(ticker, company)
    at = datetime(2026, 11, 24, 14, tzinfo=timezone.utc)

    def analyzer(rows):
        return [dict(id=row['id'], related=True, title_he='עדכון חברה', summary_he='החברה פרסמה עדכון.',
                     materiality='high', sentiment='positive', relevance=.98, thesis_effect='unchanged')
                for row in rows]

    for i, title in enumerate(titles):
        now = at + timedelta(minutes=i)
        news_pipeline.ingest_items([dict(title=title, url=f'https://example.test/edit/{i}',
          provider='yahoo_priority', publisher='Fixture Wire', tickers=[ticker], published_at=now.isoformat())], now)
        news_pipeline.analyze_news_jobs(analyzer=analyzer, at=now)
    with database.get_db_connection() as conn:
        queued = conn.execute("""
            SELECT n.title FROM scanner_telegram_outbox o JOIN scanner_news n
            ON o.dedupe_key LIKE ('watchlist-news:' || n.id || ':%')
            WHERE o.event_type='watchlist_news' ORDER BY o.id
            """).fetchall()
        assert [row['title'] for row in queued] == [titles[index] for index in kept]
