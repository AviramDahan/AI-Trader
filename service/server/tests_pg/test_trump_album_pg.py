"""Real isolated PostgreSQL album claims/WAL; synthetic assets and mocked sends."""
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone

import pytest

AT=datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def ready_album(pg,tmp_path,monkeypatch):
    import database,scanner_engine,stock_scanner
    import trump_truth_media as m,trump_telegram_album as a
    from trump_telegram_channel import KIND,POLICY,CHANNEL,CHANNEL_ID,URL_PREFIX
    values={'TELEGRAM_TRUMP_SOURCE':'telegram_channel_v1','TELEGRAM_TRUMP_CHANNEL_ENABLED':'true',
        'TELEGRAM_TRUMP_TRUTH_ENABLED':'false','TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED':'true',
        'TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED':'true','TELEGRAM_TRUMP_TRUTH_NOT_BEFORE':(AT-timedelta(hours=1)).isoformat(),
        'TELEGRAM_MARKET_NEWS_THREAD_ID':'991','TELEGRAM_BOT_TOKEN':'synthetic-only','TELEGRAM_CHAT_ID':'-1001',
        'NEWS_EVENTS_RUNTIME':'false'}
    for k,v in values.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(m,'CACHE',tmp_path/'assets')
    monkeypatch.setattr(scanner_engine,'now_z',lambda:AT.isoformat())
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    members=[]
    for number in (100,101,102):
        item=dict(source_kind=KIND,provider='telegram_channels',relay_channel=CHANNEL,
            relay_channel_id=CHANNEL_ID,relay_message_id=number,truth_post_id='tg:1462338131:'+str(number),
            truth_url=URL_PREFIX+str(number),relay_published_at=(AT-timedelta(minutes=2)).isoformat(),
            observed_at=AT.isoformat(),original_published_at=None,source_verification='channel_only',
            activation=values['TELEGRAM_TRUMP_TRUTH_NOT_BEFORE'],text_excerpt='',has_media=True,is_repost=False,
            publication_policy=POLICY,telegram_grouped_id=123456)
        data=b'\xff\xd8\xff'+bytes([number]);sha=hashlib.sha256(data).hexdigest();m._store(data,sha)
        item['media']=dict(version=m.VERSION,binding=m._binding(item),status='available',kind='photo',
            mime_type='image/jpeg',asset_identity=hashlib.sha256(str(number).encode()).hexdigest(),
            sha256=sha,bytes=len(data),captured_at=AT.isoformat(),reason=None)
        members.append(item)
    ref=a.fingerprint(members)
    with database.get_db_connection() as c:
        a._put(c,a._key(123456),dict(version=a.VERSION,fingerprint=ref,first_seen=(AT-timedelta(minutes=2)).isoformat(),
            phase='ready',members=members,lease=None,lease_until=None),AT)
    return database,a,dict(members[0],album_ref=ref)


def _queued(ready_album):
    db,a,item=ready_album
    import trump_truth_posts as t
    assert t.ingest([item],AT)['inserted']==1
    with db.get_db_connection() as c:
        return dict(c.execute('SELECT * FROM scanner_telegram_outbox WHERE status=?',(a.PENDING,)).fetchone())


def test_pg_atomic_member_reservations_and_real_queue_lifecycle(ready_album,monkeypatch):
    db,a,item=ready_album
    row=_queued(ready_album)
    import trump_truth_posts as t,trump_truth_translation as h,scanner_engine as e
    import trump_telegram_album_delivery as d
    assert t.ingest([item],AT)['duplicates']==1
    def no_ai(*args,**kwargs):pytest.fail('captionless album must not call inference')
    assert h.prepare(at=AT,completion=no_ai)=={'prepared':1,'deferred':0}
    with db.get_db_connection() as c:
        assert c.execute('SELECT count(*) AS n FROM scanner_telegram_outbox WHERE status=?',(a.CLAIMED,)).fetchone()['n']==3
    monkeypatch.setattr(d,'_now',lambda:AT)
    calls=[]
    def send(fields,members):
        calls.append([i['relay_message_id'] for i in members])
        return {'message_ids':[501,502,503],'media_group_id':'synthetic-group'}
    monkeypatch.setattr(d,'_send_album',send)
    assert e.process_telegram_outbox()=={'sent':1,'failed':0}
    assert e.process_telegram_outbox()=={'sent':0,'failed':0}
    assert calls==[[100,101,102]]
    with db.get_db_connection() as c:
        final=dict(c.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?',(row['id'],)).fetchone())
        assert final['status']=='sent' and final['attempts']==1
        assert d.receipt(final,c)['status']=='complete'
        assert c.execute('SELECT count(*) AS n FROM scanner_telegram_outbox WHERE status=?',(a.CLAIMED,)).fetchone()['n']==3


def test_pg_same_claim_writeahead_is_cas_serialized(ready_album):
    db,a,_=ready_album;row=_queued(ready_album)
    import trump_telegram_album_delivery as d,trump_truth_media as m
    row.update(status=a.SENDING,next_attempt_at=(AT+timedelta(minutes=5)).isoformat())
    with db.get_db_connection() as c:
        c.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=? WHERE id=?',
            (row['status'],row['next_attempt_at'],row['id']))
    sha='a'*64
    value=dict(version=a.VERSION,binding=m._receipt_binding(row),destination=sha,album_ref=sha,manifest_sha256=sha,
        member_count=3,text_sha256=sha,caption_sha256=sha,text_required=False,message_ids=[],media_group_id=None,
        text_message_id=None,status='album_sending')
    gate=threading.Barrier(2)
    def save():
        gate.wait(timeout=5)
        try:d._save(row,value,None,at=AT);return 'saved'
        except ValueError:return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:save(),range(2)))
    assert sorted(results)==['rejected','saved']


def test_pg_old_member_blocks_entire_new_album_without_partial_claims(ready_album):
    db,a,item=ready_album
    import scanner_engine as e,trump_truth_posts as t
    with db.get_db_connection() as c:
        assert e.enqueue_telegram(c.cursor(),t.PREFIX+'tg:1462338131:101',t.EVENT,'prior accepted body')
        c.execute("UPDATE scanner_telegram_outbox SET status='failed'")
    assert t.ingest([item],AT)['inserted']==0
    with db.get_db_connection() as c:
        rows=c.execute('SELECT * FROM scanner_telegram_outbox').fetchall()
        assert len(rows)==1 and rows[0]['status']=='failed' and rows[0]['message']=='prior accepted body'
