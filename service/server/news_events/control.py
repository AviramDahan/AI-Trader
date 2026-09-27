"""Persistent single-publisher switch. Schema 5 is reversible without DB rewind.

Changing mode requires scanner/Telegram roles stopped by the deployment tool.
Every enqueue/dispatch also checks the switch, so late work cannot leak through.
"""
import os

NEWS_TYPES = {'market_news', 'position_news', 'watchlist_news', 'stock_news'}


def state(connection=None):
    # Existing non-cloud/local fixtures continue to exercise Phase 1.
    if os.getenv('NEWS_EVENTS_RUNTIME', 'false').lower() != 'true':
        return {'mode':'phase1', 'not_before':'', 'epoch':0}
    from database import get_db_connection
    owned=connection is None
    c=connection or get_db_connection()
    try:
        row=c.execute('SELECT * FROM ne_control WHERE id=1').fetchone()
        if not row: raise RuntimeError('news_control_missing')
        return dict(row)
    finally:
        if owned:c.close()


def active():
    return state()['mode']=='canonical'


def publication_allowed(cursor,key,event_type,published_at):
    if event_type not in NEWS_TYPES:return True
    current=state(cursor)
    canonical=key.startswith('canonical:')
    if canonical != (current['mode']=='canonical'):return False
    if current.get('not_before'):
        from .model import timestamp
        if not published_at or timestamp(published_at)<current['not_before']:return False
    return True
