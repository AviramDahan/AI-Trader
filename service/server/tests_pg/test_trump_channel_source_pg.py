"""Real isolated PostgreSQL; synthetic source/model/sender only."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest

# Delivery validates against the real clock; keep synthetic posts within the
# short send window when this PostgreSQL suite runs after the original fixture day.
AT=datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def channel(pg,monkeypatch):
    import trump_truth_posts as t,scanner_engine as e,stock_scanner
    from database import get_db_connection
    values={'TELEGRAM_TRUMP_SOURCE':'telegram_channel_v1','TELEGRAM_TRUMP_CHANNEL_ENABLED':'true',
        'TELEGRAM_TRUMP_TRUTH_ENABLED':'false','TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED':'true',
        'TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED':'true','TELEGRAM_TRUMP_TRUTH_NOT_BEFORE':(AT-timedelta(minutes=1)).isoformat(),
        'TELEGRAM_MARKET_NEWS_THREAD_ID':'991','NEWS_EVENTS_RUNTIME':'false'}
    for k,v in values.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(e,'now_z',lambda:AT.isoformat())
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    m=NS(id=55,date=AT,message='We will not raise tariffs by 5%.',action=None,peer_id=NS(channel_id=1462338131),entities=[])
    item,reason=t.extract(m,AT);assert reason is None
    return t,item,get_db_connection


def approved(system,payload,schema):
    return ({'text_he':'לא נעלה את המכסים ב־5%.'} if 'text_he' in schema['properties'] else
        dict(faithful=True,fluent_hebrew=True,complete=True,unsupported_claims=False))


def row(connect):
    with connect() as c:return dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())


def test_channel_concurrent_ingestion_preparation_and_cached_retry(channel,monkeypatch):
    import trump_truth_translation as h,scanner_engine as e,stock_scanner
    t,item,connect=channel
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:t.ingest([item],AT),range(3)))
    assert sum(v['inserted'] for v in results)==1
    call=Mock(side_effect=approved)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:h.prepare(at=AT,completion=call),range(3)))
    assert sum(v['prepared'] for v in results)==1 and call.call_count==2
    sender=Mock(side_effect=['connect_timeout','sent'])
    monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    assert e.process_telegram_outbox()['failed']==1
    with connect() as c:c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'")
    assert e.process_telegram_outbox()['sent']==1
    assert e.process_telegram_outbox()['sent']==0 and sender.call_count==2
    text=str(sender.call_args)
    assert 'לא נעלה' in text and 'We will not' not in text and 'Truth Social' not in text
    with connect() as c:
        for table in ('scanner_orders','scanner_trades','scanner_signals'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n']==0


def test_channel_exhaustion_or_restored_unavailable_never_sends(channel,monkeypatch):
    import trump_truth_translation as h,scanner_engine as e,stock_scanner
    t,item,connect=channel;t.ingest([item],AT)
    def fail(*a):raise ValueError('synthetic')
    h.prepare(at=AT,completion=fail);h.prepare(at=AT+timedelta(seconds=61),completion=fail)
    assert row(connect)['status']=='cancelled'
    sender=Mock();monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    assert e.process_telegram_outbox()['sent']==0 and sender.call_count==0


def test_channel_restore_missing_cache_and_unknown_ack_no_send(channel,monkeypatch):
    import trump_truth_translation as h,scanner_engine as e,stock_scanner
    t,item,connect=channel;t.ingest([item],AT);h.prepare(at=AT,completion=approved)
    with connect() as c:c.execute('DELETE FROM scanner_settings WHERE key=?',(h.cache_key(row(connect)),))
    sender=Mock();monkeypatch.setattr(stock_scanner,'send_telegram',sender)
    assert e.process_telegram_outbox()['sent']==0 and sender.call_count==0
    assert row(connect)['status']=='cancelled'


def test_new_reader_unknown_to_rollback_stays_blocked_by_legacy_off(channel,monkeypatch):
    t,item,connect=channel;t.ingest([item],AT)
    assert __import__('os').environ['TELEGRAM_TRUMP_TRUTH_ENABLED']=='false'
    monkeypatch.setenv('TELEGRAM_TRUMP_SOURCE','truth_relay_v1')
    assert t.enabled() is False and t.delivery_message(row(connect),AT) is None
