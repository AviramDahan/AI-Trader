"""Synthetic public archive, no providers, inference or Telegram."""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
NOW = datetime(2026, 10, 22, 16, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
    c.executescript('CREATE TABLE scanner_telegram_outbox(id INTEGER PRIMARY KEY,dedupe_key TEXT,event_type TEXT,message TEXT,status TEXT,created_at TEXT,sent_at TEXT); CREATE TABLE scanner_settings(key TEXT PRIMARY KEY,value_json TEXT);')
    yield c
    c.close()


def seed(c, number=1, *, hebrew=True, status='sent', cache=True, presentation='hebrew_v1', **overrides):
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
    if hebrew: envelope['presentation']=presentation
    row = dict(id=number,dedupe_key=t.PREFIX+post,event_type=t.EVENT,message=json.dumps(envelope),status=status,
        created_at=(NOW-timedelta(minutes=58)).isoformat(),sent_at=(NOW-timedelta(minutes=57)).isoformat())
    c.execute('INSERT INTO scanner_telegram_outbox VALUES(:id,:dedupe_key,:event_type,:message,:status,:created_at,:sent_at)',row)
    if cache:
        value=dict(version=presentation,binding=h.binding(row,envelope),attempts=1,status='translated',text_he='לא נעלה את המכסים ב־5%.')
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


def test_new_bilingual_publication_requires_its_own_complete_receipt(conn,monkeypatch):
    row,envelope=seed(conn,presentation='bilingual_v1',cache=False)
    proof=Mock(return_value=True)
    monkeypatch.setitem(sys.modules,'trump_truth_bilingual',SimpleNamespace(published_receipt=proof))
    ready(conn)
    from trump_truth_public import report
    items=report(conn,now=NOW)['items']
    assert len(items)==1 and items[0]['source_excerpt']==envelope['item']['text_excerpt']
    assert items[0]['translation_status']=='not_retained' and items[0]['text_he'] is None
    assert proof.call_args.kwargs['conn'] is conn and proof.call_args.kwargs['at']==NOW
    assert proof.call_args.args[0]['id']==row['id']


@pytest.mark.parametrize('receipt',[False,None,1,{'status':'complete'}])
def test_old_sent_or_old_complete_cannot_stand_in_for_bilingual_acks(conn,monkeypatch,receipt):
    seed(conn,presentation='bilingual_v1')
    monkeypatch.setitem(sys.modules,'trump_truth_bilingual',SimpleNamespace(published_receipt=Mock(return_value=receipt)))
    ready(conn)
    from trump_truth_public import report
    assert report(conn,now=NOW)['items']==[]


def complete_bilingual(c,row,envelope):
    """Synthetic positive ACK fixture derived from the REAL pure versioned plan."""
    import trump_truth_bilingual as b
    import trump_truth_media as m
    import trump_truth_translation as h
    cache=json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(h.cache_key(row),)).fetchone()[0])
    parts=b.plan(envelope['item'],cache,False)
    value={'version':b.RECEIPT_VERSION,'binding':m._receipt_binding(row),'destination':'a'*64,'asset_sha256':None,
        'plan':b._metadata(parts),'acks':{p['stage']:100+i for i,p in enumerate(parts)},'status':'complete','active_stage':None}
    c.execute('INSERT INTO scanner_settings VALUES(?,?)',(b.receipt_key(row),json.dumps(value)))
    c.commit();return cache,value,parts


def test_actual_bilingual_multi_part_receipt_does_not_apply_legacy_single_wire_fallback(conn):
    import trump_truth_translation as h
    source='We said: '+'1 '*790
    row,envelope=seed(conn,presentation='bilingual_v1',text_excerpt=source.strip())
    value=json.loads(conn.execute('SELECT value_json FROM scanner_settings WHERE key=?',(h.cache_key(row),)).fetchone()[0])
    value['text_he']='אמרנו: '+'1 '*790+'עברית '*100
    conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(json.dumps(value),h.cache_key(row)));conn.commit()
    _,_,parts=complete_bilingual(conn,row,envelope)
    assert len(parts)==2
    ready(conn)
    from trump_truth_public import report
    item=report(conn,now=NOW)['items'][0]
    assert item['text_he']==value['text_he'] and item['source_excerpt']==source.strip()
    assert item['translation_status']=='translated'


@pytest.mark.parametrize('damage',['missing_cache','missing_ack','other_valid_unsent_cache'])
def test_actual_bilingual_receipt_missing_data_never_reconstructs_or_certifies_other_text(conn,damage):
    import trump_truth_bilingual as b
    import trump_truth_translation as h
    row,envelope=seed(conn,presentation='bilingual_v1')
    cache,receipt,_=complete_bilingual(conn,row,envelope)
    if damage=='missing_cache':conn.execute('DELETE FROM scanner_settings WHERE key=?',(h.cache_key(row),))
    if damage=='missing_ack':
        receipt['acks']={}
        conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(json.dumps(receipt),b.receipt_key(row)))
    if damage=='other_valid_unsent_cache':
        cache['text_he']='לא נשנה את המכסים ב־5%.'
        h.checked_cache(row,envelope,cache)
        conn.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(json.dumps(cache),h.cache_key(row)))
    conn.commit();ready(conn)
    from trump_truth_public import report
    items=report(conn,now=NOW)['items']
    if damage=='missing_cache':
        assert len(items)==1 and items[0]['translation_status']=='not_retained' and items[0]['text_he'] is None
        assert items[0]['source_excerpt']==envelope['item']['text_excerpt']
    else:assert items==[]


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
