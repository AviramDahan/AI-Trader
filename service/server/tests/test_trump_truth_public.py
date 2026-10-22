"""Synthetic public archive, no providers, inference or Telegram."""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
NOW = datetime(2026, 10, 22, 16, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
    c.executescript('CREATE TABLE scanner_telegram_outbox(id INTEGER PRIMARY KEY,dedupe_key TEXT,event_type TEXT,message TEXT,status TEXT,created_at TEXT,sent_at TEXT); CREATE TABLE scanner_settings(key TEXT PRIMARY KEY,value_json TEXT);')
    yield c
    c.close()


def seed(c, number=1, *, hebrew=True, status='sent', cache=True, **overrides):
    import trump_truth_posts as t
    import trump_truth_translation as h
    post = str(117500000000000000 + number)
    item = dict(source_kind=t.KIND, provider='telegram_channels', relay_channel=t.CHANNEL,
        relay_channel_id=t.CHANNEL_ID, relay_message_id=number, truth_post_id=post,
        truth_url='https://truthsocial.com/@realDonaldTrump/'+post,
        activation=(NOW-timedelta(hours=2)).isoformat(), relay_published_at=(NOW-timedelta(hours=1)).isoformat(),
        observed_at=(NOW-timedelta(minutes=59)).isoformat(), original_published_at=None,
        source_verification='relay_only', text_excerpt='We will not raise tariffs by 5%.', has_media=False, is_repost=False)
    item.update(overrides)
    envelope = {'item':item, 'fence':{'mode':'canonical','epoch':2,'not_before':'','environment_not_before':''}}
    if hebrew: envelope['presentation']='hebrew_v1'
    row = dict(id=number,dedupe_key=t.PREFIX+post,event_type=t.EVENT,message=json.dumps(envelope),status=status,
        created_at=(NOW-timedelta(minutes=58)).isoformat(),sent_at=(NOW-timedelta(minutes=57)).isoformat())
    c.execute('INSERT INTO scanner_telegram_outbox VALUES(:id,:dedupe_key,:event_type,:message,:status,:created_at,:sent_at)',row)
    if cache:
        value=dict(version=h.VERSION,binding=h.binding(row,envelope),attempts=1,status='translated',text_he='לא נעלה את המכסים ב־5%.')
        c.execute('INSERT INTO scanner_settings VALUES(?,?)',(h.cache_key(row),h.wire(value)))
    c.commit()
    return row, envelope


def ready(c):
    c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')


def test_actual_sent_hebrew_public_projection_is_read_only_and_source_bound(conn, monkeypatch):
    seed(conn); seed(conn,2,hebrew=False); seed(conn,3,status='pending')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE','2027-01-01T00:00:00Z')
    ready(conn)
    from trump_truth_public import report
    data=report(conn,now=NOW)
    assert len(data['items'])==1
    item=data['items'][0]
    assert item['text_he']=='לא נעלה את המכסים ב־5%.' and item['translation_status']=='translated'
    assert item['source_verification']=='relay_only' and item['original_published_at'] is None
    assert not {'message','fence','binding','activation','row_id','relay_message_id'} & item.keys()
    assert data['coverage']['history_is_not_live_dispatch'] is True
    with pytest.raises(sqlite3.OperationalError): conn.execute('DELETE FROM scanner_settings')


def test_missing_cache_is_unknown_not_english_translation(conn):
    seed(conn,cache=False); ready(conn)
    from trump_truth_public import report
    item=report(conn,now=NOW)['items'][0]
    assert item['translation_status']=='not_retained' and item['text_he'] is None


@pytest.mark.parametrize('changes',[
    {'relay_channel_id':999}, {'truth_url':'https://evil.invalid/'},
    {'observed_at':(NOW+timedelta(seconds=1)).isoformat()}, {'original_published_at':NOW.isoformat()},
    {'activation':(NOW+timedelta(days=1)).isoformat()}, {'has_media':1},
])
def test_invalid_historical_source_never_public(conn,changes):
    seed(conn,**changes); ready(conn)
    from trump_truth_public import report
    assert report(conn,now=NOW)['items']==[]


def test_cursor_is_public_post_id_and_pages_do_not_repeat(conn):
    for n in range(1,5): seed(conn,n)
    ready(conn)
    from trump_truth_public import report
    first=report(conn,now=NOW,limit=2)
    second=report(conn,now=NOW,limit=2,before=first['next_cursor'])
    assert len(first['items'])==len(second['items'])==2
    assert not {v['id'] for v in first['items']} & {v['id'] for v in second['items']}
    assert first['next_cursor'].isdigit() and len(first['next_cursor'])>=16


def test_refuses_writable_snapshot_and_unbounded_arguments(conn):
    from trump_truth_public import report
    with pytest.raises(RuntimeError,match='read_only'): report(conn,now=NOW)
    ready(conn)
    for limit in (0,21,True):
        with pytest.raises(ValueError): report(conn,now=NOW,limit=limit)
    with pytest.raises(ValueError): report(conn,now=NOW,before='1 OR 1=1')


def test_page_scan_is_bounded_when_old_source_rows_are_excluded(conn):
    for n in range(1,70): seed(conn,n,hebrew=False,cache=False)
    ready(conn)
    from trump_truth_public import report
    data=report(conn,now=NOW)
    assert data['items']==[] and data['coverage']['scanned']==60
    assert data['next_cursor']==str(117500000000000010)
    next_page=report(conn,now=NOW,before=data['next_cursor'])
    assert next_page['coverage']['scanned']==9 and next_page['next_cursor'] is None


def test_archive_window_and_future_sent_are_not_relabelled_as_empty_new_posts(conn):
    seed(conn,1); seed(conn,2); seed(conn,3)
    conn.execute('UPDATE scanner_telegram_outbox SET sent_at=? WHERE id=2',((NOW-timedelta(days=8)).isoformat(),))
    conn.execute('UPDATE scanner_telegram_outbox SET sent_at=? WHERE id=3',((NOW+timedelta(seconds=1)).isoformat(),))
    conn.commit(); ready(conn)
    from trump_truth_public import report
    data=report(conn,now=NOW)
    assert [i['truth_post_id'] for i in data['items']]==['117500000000000001']


def test_unknown_or_duplicate_json_fields_never_leak(conn):
    row,_=seed(conn)
    conn.execute('UPDATE scanner_telegram_outbox SET message=? WHERE id=?',
        ('{"presentation":"hebrew_v1",'+row['message'][1:],row['id']))
    conn.commit(); ready(conn)
    from trump_truth_public import report
    assert report(conn,now=NOW)['items']==[]


def test_public_api_routes_do_not_invoke_workers_or_disclose_exception(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes_scanner import register_scanner_routes
    import trump_truth_public as p
    app=FastAPI(); register_scanner_routes(app)
    calls=[]
    monkeypatch.setattr(p,'payload',lambda **kw:calls.append(kw) or {'version':1,'items':[]})
    client=TestClient(app)
    response=client.get('/api/scanner/trump-posts?limit=2&before=117500000000000001')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert calls==[{'limit':2,'before':'117500000000000001'}]
    for path in ('?limit=21','?before=1','?before=../../private'):
        assert client.get('/api/scanner/trump-posts'+path).status_code==422
    monkeypatch.setattr(p,'asset_payload',lambda token: (_ for _ in ()).throw(ValueError('SYNTHETIC_PRIVATE_SENTINEL')))
    response=client.get('/api/scanner/trump-media/'+'a'*64)
    assert response.status_code==404 and 'SYNTHETIC' not in response.text
    monkeypatch.setattr(p,'asset_payload',lambda token:(b'\xff\xd8\xff\xd9','image/jpeg'))
    response=client.get('/api/scanner/trump-media/'+'a'*64)
    assert response.content==b'\xff\xd8\xff\xd9' and response.headers['x-content-type-options']=='nosniff'
