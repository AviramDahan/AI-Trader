"""Revalidate personal-news subscriptions immediately before Telegram delivery.

No ticker-specific code, AI calls, message-text parsing or trading writes.
Uses persisted news references in application-generated outbox dedupe keys.
"""
from database import get_db_connection


def personal_delivery_message(event):
    """Return a message for the still-relevant original recipients, or cancel.

    A closed position can remain relevant via an enabled watchlist (and vice
    versa). A pending notice is never promoted to the broad-news tier here:
    that tier has its own stricter filters. Sent messages/history are untouched.
    """
    from news_pipeline import _news_alert_message, _watchlist_alert_message
    parts = event['dedupe_key'].split(':')
    conn = get_db_connection()
    try:
        if parts[0] in {'news', 'watchlist-news'} and len(parts) >= 4 and parts[1].isdigit():
            news = conn.execute('SELECT * FROM scanner_news WHERE id=?', (int(parts[1]),)).fetchone()
            original = set(parts[-1].split(','))
        elif parts[0] == 'position-news' and len(parts) == 2:
            news = conn.execute('SELECT * FROM scanner_news WHERE fingerprint=?', (parts[1],)).fetchone()
            original = {news['ticker']} if news else set()
        else:
            return None
        if not news or not original:
            return None
        placeholders = ','.join('?' for _ in original)
        params = tuple(sorted(original))
        held = {r['ticker']: r['company'] for r in conn.execute(f"""
            SELECT ticker,company FROM scanner_trades WHERE status='open'
            AND remaining_quantity>0 AND is_shadow=0 AND ticker IN ({placeholders})""", params)}
        watched = {r['ticker']: r['company'] for r in conn.execute(f"""
            SELECT ticker,company FROM scanner_news_watchlist
            WHERE enabled=1 AND ticker IN ({placeholders})""", params)}
        active = {**watched, **held}
        if not active:
            return None
        row = dict(news)
        from news_evidence import decorate
        decorate(conn.cursor(), row)
        row.update(ticker=', '.join(sorted(active)),
                   company=', '.join(sorted({c for c in active.values() if c})),
                   impact=row.get('impact') or row.get('sentiment') or 'unclear',
                   materiality=row.get('materiality') or 'low')
        if not held:
            return _watchlist_alert_message(row)
        message = _news_alert_message(row)
        if set(watched) - set(held):
            message = message.replace('חדשות מהותיות לפוזיציה פתוחה', 'חדשות מהותיות לתיק ולרשימת המעקב', 1)
        return message
    finally:
        conn.close()
