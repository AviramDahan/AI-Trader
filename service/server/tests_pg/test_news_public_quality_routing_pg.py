"""Disposable PG exact-version/public dispatch. No real model or Telegram."""
from unittest.mock import Mock
import pytest
from test_earnings_news_routing_pg import sender


@pytest.mark.parametrize('title,expected',[
    ('Broker Adjusts Example PT to $105 From $100','analyst'),
    ('Example wins $200 million supply contract','positive'),
    ('3 stocks to buy before the next rally','cancelled'),
])
def test_legacy_twenty_hex_version_routes_or_cancels_once(pg,sender,monkeypatch,title,expected):
    from datetime import datetime,timezone
    import database,scanner_engine,stock_scanner
    from news_pipeline import _event_version
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME','false')
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','true')
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_THREAD_ID','880')
    monkeypatch.setenv('TELEGRAM_POSITIVE_STOCK_NEWS_THREAD_ID','881')
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    at=datetime.now(timezone.utc).isoformat()
    version=_event_version({'title':title})
    assert len(version)==20
    with database.get_db_connection() as c:
        c.execute("UPDATE ne_control SET mode='phase1',not_before='' WHERE id=1")
        c.execute('''INSERT INTO scanner_news(fingerprint,scope,title,publisher,url,published_at,fetched_at,
            content_hash,analysis_status,quality_version,verified_tickers_json,sentiment,materiality,relevance)
            VALUES(?,'company',?,'fixture','https://fixture.invalid/news',?,?,?,'analyzed',2,'["TEST"]','positive','high',.9)''',
            ('fixture',title,at,at,version))
        nid=c.execute('SELECT id FROM scanner_news').fetchone()['id']
        key=f'stock-news:{nid}:{version}:TEST'
        assert scanner_engine.enqueue_telegram(c.cursor(),key,'stock_news','עדכון חברה חדש',published_at=at)
    result=scanner_engine.process_telegram_outbox()
    assert result['sent']==int(expected!='cancelled')
    assert scanner_engine.process_telegram_outbox()['sent']==0
    if expected=='cancelled':assert not sender.post.called
    else:assert sender.post.call_args.kwargs['data']['message_thread_id']==(880 if expected=='analyst' else 881)
    with database.get_db_connection() as c:
        row=dict(c.execute('SELECT * FROM scanner_telegram_outbox WHERE dedupe_key=?',(key,)).fetchone())
        assert row['status']==('cancelled' if expected=='cancelled' else 'sent')
        assert row['event_type']=='stock_news' and row['dedupe_key']==key
        assert c.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM scanner_orders').fetchone()['n']==0
