"""Offline album WAL/transport tests. No source retrieval or model calls."""
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

AT = datetime(2026, 11, 8, 10, tzinfo=timezone.utc)
VERSION = 'trump_telegram_album_v1'


@pytest.fixture
def rig(tmp_path, monkeypatch):
    import database as db, trump_truth_posts as posts, trump_truth_media as media, telegram_topics as topics
    monkeypatch.setattr(db, 'DATABASE_URL', '')
    monkeypatch.setattr(db, '_SQLITE_DB_PATH', str(tmp_path/'album.sqlite'))
    db.init_database()
    members = [{'media': {'kind': kind, 'mime_type': mime, 'sha256': hashlib.sha256(data).hexdigest(),
                         'bytes': len(data)}} for kind, mime, data in
               [('photo', 'image/jpeg', b'photo'), ('video', 'video/mp4', b'video')]]
    album = NS(VERSION=VERSION, SENDING='trump_album_sending', enabled=lambda: True,
               checked_manifest=Mock(side_effect=lambda *a, **k: copy.deepcopy(members)))
    monkeypatch.setitem(sys.modules, 'trump_telegram_album', album)
    import trump_telegram_album_delivery as delivery
    envelope = {'item': {'source_version': 'telegram_trump_channel_v1'}, 'presentation': 'hebrew_v1',
                'media_version': VERSION, 'album_ref': 'a'*64}
    monkeypatch.setattr(posts, 'checked_envelope', lambda *a: copy.deepcopy(envelope))
    presentation = Mock(return_value='הודעה בעברית')
    monkeypatch.setattr(posts, 'delivery_message', presentation)
    monkeypatch.setattr(topics, 'thread_id_for_event', lambda *a: 991)
    monkeypatch.setattr(topics, 'destination_fields', lambda *a: {'chat_id': '-1001', 'message_thread_id': 991})
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001')
    monkeypatch.setattr(delivery, '_now', lambda: AT)
    monkeypatch.setattr(media, '_read', Mock(return_value=b'checked bytes'))
    monkeypatch.setattr(media, 'delivery_plan', lambda text, item: {'caption': text if len(text)<1024 else 'מדיה',
                                                                 'text': text if len(text)>=1024 else None})
    with db.get_db_connection() as c:
        c.execute('INSERT INTO scanner_telegram_outbox(dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at) VALUES(?,?,?,?,?,?,?)',
                  ('album:1', 'trump_truth_post', json.dumps(envelope), album.SENDING, 0,
                   (AT+timedelta(minutes=5)).isoformat(), AT.isoformat()))
        row = dict(c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id DESC LIMIT 1').fetchone())
    group = Mock(return_value={'message_ids': [123, 124], 'media_group_id': 'group-1'})
    text = Mock(return_value={'message_id': 125})
    monkeypatch.setattr(delivery, '_send_album', group)
    monkeypatch.setattr(media, '_send', text)
    return NS(d=delivery, db=db, row=row, group=group, text=text, members=members,
              album=album, envelope=envelope, presentation=presentation, media=media)


def run(r): return r.d.dispatch(r.row, {'telegram_enabled': True}, AT)


def test_album_ack_is_durable_and_never_resent(rig):
    r=rig
    assert run(r)=='sent'
    assert r.d.receipt(r.row)['message_ids']==[123,124]
    assert r.d.receipt(r.row)['status']=='complete'
    assert r.d.receipt_key(r.row)==VERSION+':delivery:'+str(r.row['id'])
    assert run(r)=='sent'
    r.group.assert_called_once(); r.text.assert_not_called()


def test_text_retry_never_resends_known_album(rig):
    r=rig; r.presentation.return_value='עברית '*250
    r.text.side_effect=[{'retry':True,'reason':'rate_limited'},{'message_id':125}]
    assert json.loads(run(r))['terminal'] is False
    assert r.d.receipt(r.row)['status']=='retry_text'
    assert run(r)=='sent'
    assert r.group.call_count==1 and r.text.call_count==2


@pytest.mark.parametrize('stage',['album','text'])
def test_unknown_ack_is_terminal_no_fallback_or_replay(rig, stage):
    r=rig; r.presentation.return_value='עברית '*250
    (r.group if stage=='album' else r.text).return_value={'unknown':True}
    assert json.loads(run(r))['terminal'] is True
    assert r.d.receipt(r.row)['status']=='unknown'
    assert json.loads(run(r))['terminal'] is True
    assert r.group.call_count==1 and r.text.call_count==(stage=='text')


def test_crash_after_wal_is_unknown_on_restart(rig):
    r=rig; r.group.side_effect=KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):run(r)
    assert r.d.receipt(r.row)['status']=='album_sending'
    assert json.loads(run(r))['terminal'] is True
    assert r.group.call_count==1


@pytest.mark.parametrize('damage',['expired','lease','message','status','event','dedupe'])
def test_invalid_live_claim_prevents_external_effect(rig,damage):
    r=rig
    field,value={'expired':('next_attempt_at',(AT-timedelta(seconds=1)).isoformat()),
                 'lease':('next_attempt_at',(AT+timedelta(minutes=6)).isoformat()),
                 'message':('message','changed'),'status':('status','pending'),
                 'event':('event_type','news'),'dedupe':('dedupe_key','other')}[damage]
    with r.db.get_db_connection() as c:c.execute('UPDATE scanner_telegram_outbox SET '+field+'=? WHERE id=?',(value,r.row['id']))
    assert json.loads(run(r))['terminal'] is True
    r.group.assert_not_called();r.text.assert_not_called()


@pytest.mark.parametrize('change',['presentation','envelope','destination','disabled','manifest'])
def test_each_side_effect_rechecks_frozen_authority(rig,monkeypatch,change):
    r=rig;r.presentation.return_value='עברית '*250
    def ack(*args):
        if change=='presentation':r.presentation.return_value='השתנה'
        if change=='envelope':r.envelope['fence']='changed'
        if change=='destination':
            import telegram_topics
            monkeypatch.setattr(telegram_topics,'destination_fields',lambda *a:{'chat_id':'-1002','message_thread_id':991})
        if change=='disabled':r.album.enabled=lambda:False
        if change=='manifest':r.members.reverse()
        return {'message_ids':[123,124],'media_group_id':'group-1'}
    r.group.side_effect=ack
    assert json.loads(run(r))['terminal'] is True
    r.text.assert_not_called()


def test_cas_receipt_change_blocks_send(rig,monkeypatch):
    r=rig; original=r.d._save
    def changed(row,value,expected,**kwargs):
        with r.db.get_db_connection() as c:
            c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
                      (r.d.receipt_key(row),'{}',AT.isoformat()))
        return original(row,value,expected,**kwargs)
    monkeypatch.setattr(r.d,'_save',changed)
    assert json.loads(run(r))['terminal'] is True
    r.group.assert_not_called()


def test_album_definite_retry_resumes_same_stage_once(rig):
    r=rig;r.group.side_effect=[{'retry':True,'reason':'connect_timeout'},
                              {'message_ids':[123,124],'media_group_id':'group-1'}]
    assert json.loads(run(r))['terminal'] is False
    assert r.d.receipt(r.row)['status']=='retry_album'
    assert run(r)=='sent'
    assert r.group.call_count==2 and r.text.call_count==0


@pytest.mark.parametrize('stage',['album','text'])
def test_crash_after_ack_saved_never_repeats_acknowledged_side_effect(rig,monkeypatch,stage):
    r=rig;r.presentation.return_value='עברית '*250
    original=r.d._save
    def crash(row,value,expected,**kwargs):
        original(row,value,expected,**kwargs)
        if value['status']==stage+'_sent':raise KeyboardInterrupt()
    monkeypatch.setattr(r.d,'_save',crash)
    with pytest.raises(KeyboardInterrupt):run(r)
    monkeypatch.setattr(r.d,'_save',original)
    assert run(r)=='sent'
    assert r.group.call_count==1 and r.text.call_count==1


def test_crash_after_remote_text_without_ack_never_replays_text_or_group(rig):
    r=rig;r.presentation.return_value='עברית '*250;r.text.side_effect=KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):run(r)
    assert r.d.receipt(r.row)['status']=='text_sending'
    assert json.loads(run(r))['terminal'] is True
    assert r.group.call_count==1 and r.text.call_count==1


def test_real_stage_clock_expiry_after_album_prevents_text(rig,monkeypatch):
    r=rig;r.presentation.return_value='עברית '*250;clock=[AT]
    monkeypatch.setattr(r.d,'_now',lambda:clock[0])
    def ack(*a):
        clock[0]=AT+timedelta(minutes=6)
        return {'message_ids':[123,124],'media_group_id':'group-1'}
    r.group.side_effect=ack
    assert json.loads(r.d.dispatch(r.row,{'telegram_enabled':True}))['terminal'] is True
    r.text.assert_not_called()
    assert r.d.receipt(r.row)['status']=='album_sending'


@pytest.mark.parametrize('field,value',[
    ('message_ids',[True,124]),('message_ids',[123,123]),('message_ids',[123]),
    ('media_group_id',''),('member_count',True),('text_message_id',False),
    ('text_message_id',125),('destination','b'*64),('manifest_sha256','b'*64),
    ('album_ref','b'*64),('text_sha256','b'*64),('caption_sha256','b'*64),
    ('status','made_up')])
def test_invalid_or_rebound_complete_receipt_never_replays(rig,field,value):
    r=rig;assert run(r)=='sent';receipt=r.d.receipt(r.row);receipt[field]=value
    with r.db.get_db_connection() as c:c.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',
                                               (json.dumps(receipt),r.d.receipt_key(r.row)))
    assert json.loads(run(r))['terminal'] is True
    assert r.group.call_count==1


def test_disabled_and_invalid_manifest_never_send_or_prepare_ai(rig):
    r=rig
    assert json.loads(r.d.dispatch(r.row,{'telegram_enabled':False},AT))['terminal'] is True
    r.album.checked_manifest.side_effect=ValueError('private data must not escape')
    output=run(r)
    assert json.loads(output)['terminal'] is True and 'private data' not in output
    r.group.assert_not_called();r.text.assert_not_called()


def test_two_callers_with_same_claim_cannot_both_send(rig,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    r=rig;barrier=Barrier(2);original=r.d.receipt
    def synchronized_receipt(row,conn=None):
        value=original(row,conn)
        barrier.wait(timeout=10)
        return value
    monkeypatch.setattr(r.d,'receipt',synchronized_receipt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:run(r),range(2)))
    assert results.count('sent')==1
    assert all(v=='sent' or json.loads(v)['terminal'] is True for v in results)
    assert r.group.call_count==1


def test_postgres_stage_locks_live_claim_before_receipt_cas(rig,monkeypatch):
    from contextlib import contextmanager
    r=rig;assert run(r)=='sent'
    value=r.d.receipt(r.row)
    real=r.db.get_db_connection;queries=[]
    class Connection:
        def __init__(self,c):self.c=c
        def cursor(self):return self.c.cursor()
        def execute(self,sql,args=()):
            queries.append(sql)
            return self.c.execute(sql.removesuffix(' FOR UPDATE'),args)
    # Open SQLite BEFORE selecting the emulated SQL dialect; never invoke a
    # PostgreSQL factory or any real socket for this SQL-shape-only test.
    with real() as raw:
        @contextmanager
        def fake_postgres():yield Connection(raw)
        monkeypatch.setattr(r.db,'get_db_connection',fake_postgres)
        monkeypatch.setattr(r.db,'using_postgres',lambda:True)
        monkeypatch.setattr(r.db,'begin_write_transaction',lambda cur:cur.execute('BEGIN IMMEDIATE'))
        r.d._save(r.row,value,value,at=AT)
    assert queries[0].endswith(' FOR UPDATE')
    assert 'scanner_telegram_outbox' in queries[0] and 'scanner_settings' in queries[1]


def test_album_safe_transport_and_ack_identity(monkeypatch):
    import requests, trump_truth_media as m, trump_telegram_album_delivery as d
    members=[{'media':{'kind':'photo','mime_type':'image/jpeg','sha256':'a'*64,'bytes':4}},
             {'media':{'kind':'video','mime_type':'video/mp4','sha256':'b'*64,'bytes':5}}]
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','synthetic-only')
    monkeypatch.setattr(m,'_read',Mock(return_value=b'bytes'))
    result=[{'message_id':n,'chat':{'id':-1001},'message_thread_id':991,'media_group_id':'group-1',kind:({} if kind=='video' else [{}])}
            for n,kind in [(123,'photo'),(124,'video')]]
    session=Mock();session.post.return_value=NS(status_code=200,json=lambda:{'ok':True,'result':result})
    monkeypatch.setattr(requests,'Session',lambda:session)
    assert d._send_album({'chat_id':'-1001','message_thread_id':991,
        'caption':'עברית\nחשיבות לא נקבעה · הסבר\nדווח: 13.11.2026 20:00 UTC'},members)=={
        'message_ids':[123,124],'media_group_id':'group-1'}
    kw=session.post.call_args.kwargs
    assert session.trust_env is False and kw['allow_redirects'] is False and kw['timeout']==30
    media=json.loads(kw['data']['media'])
    assert [x['media'] for x in media]==['attach://asset0','attach://asset1']
    assert media[0]['caption']=='עברית' and 'caption' not in media[1]
    assert set(kw['files'])=={'asset0','asset1'}
    session.close.assert_called_once()


@pytest.mark.parametrize('damage',['length','duplicate','boolean','chat','thread','group','kind','empty_group','malformed'])
def test_ambiguous_group_ack_never_accepted(monkeypatch,damage):
    import requests, trump_truth_media as m, trump_telegram_album_delivery as d
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','synthetic-only');monkeypatch.setattr(m,'_read',lambda *a:b'bytes')
    members=[{'media':{'kind':'photo','mime_type':'image/jpeg','sha256':'a'*64,'bytes':4}} for _ in range(2)]
    result=[{'message_id':n,'chat':{'id':-1001},'message_thread_id':991,'media_group_id':'group-1','photo':[{}]} for n in (123,124)]
    if damage=='length':result.pop()
    if damage=='duplicate':result[1]['message_id']=123
    if damage=='boolean':result[0]['message_id']=True
    if damage=='chat':result[0]['chat']['id']=-1002
    if damage=='thread':result[0]['message_thread_id']=True
    if damage=='group':result[0]['media_group_id']='group-2'
    if damage=='kind':result[0].pop('photo');result[0]['video']={}
    if damage=='empty_group':result[0]['media_group_id']=''
    if damage=='malformed':result={}
    s=Mock();s.post.return_value=NS(status_code=200,json=lambda:{'ok':True,'result':result})
    monkeypatch.setattr(requests,'Session',lambda:s)
    assert d._send_album({'chat_id':'-1001','message_thread_id':991,'caption':'עברית'},members)=={'unknown':True}


@pytest.mark.parametrize('outcome',['rate','connect','read','server','redirect','bad_json'])
def test_transport_retries_only_definite_rejection_or_connect_timeout(monkeypatch,outcome):
    import requests, trump_truth_media as m, trump_telegram_album_delivery as d
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','synthetic-only');monkeypatch.setattr(m,'_read',lambda *a:b'bytes')
    s=Mock();body={'ok':False,'error_code':429}
    s.post.return_value=NS(status_code={'rate':429,'server':500,'redirect':302}.get(outcome,200),json=lambda:body)
    if outcome in ('connect','read'):s.post.side_effect=requests.ConnectTimeout() if outcome=='connect' else requests.ReadTimeout()
    if outcome=='bad_json':s.post.return_value.json=Mock(side_effect=ValueError('private body'))
    monkeypatch.setattr(requests,'Session',lambda:s)
    members=[{'media':{'kind':'photo','mime_type':'image/jpeg','sha256':'a'*64,'bytes':4}} for _ in range(2)]
    got=d._send_album({'chat_id':'-1001','message_thread_id':991,'caption':'עברית'},members)
    assert got==({'retry':True,'reason':'rate_limited'} if outcome=='rate' else {'retry':True,'reason':'connect_timeout'} if outcome=='connect' else {'unknown':True})
    assert s.post.call_count==1
