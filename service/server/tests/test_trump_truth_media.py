"""Synthetic pinned relay assets only; no Telegram/model/provider calls."""
import asyncio
import ast
import copy
import hashlib
import json
import inspect
import stat
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

AT = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)


@pytest.fixture
def media(tmp_path, monkeypatch):
    import trump_truth_media as m
    import trump_truth_posts as t
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE', (AT-timedelta(minutes=5)).isoformat())
    monkeypatch.setattr(m, 'CACHE', tmp_path/'assets')
    monkeypatch.setattr(m, '_now', lambda:AT)
    monkeypatch.setattr(m, '_budget_state', {'minute':None,'count':0,'bytes':0})
    import telegram_news_reader as reader
    session=tmp_path/'reader.session';session.touch();session.chmod(0o600)
    monkeypatch.setattr(reader,'SESSION',session)
    # The production boundary uses actual imported Telethon classes. Tests
    # supply a disjoint strict type family, never duck-type arbitrary objects.
    classes = {name: type(name, (), {}) for name in
        ('MessageMediaPhoto', 'Photo', 'MessageMediaDocument', 'Document', 'DocumentAttributeVideo')}
    monkeypatch.setattr(m, '_types', lambda: NS(**classes))
    photo = classes['Photo'](); photo.id = 7; photo.sizes = [NS(size=4)]
    attached = classes['MessageMediaPhoto'](); attached.photo = photo
    text = t.HEADER+'\nThis post contains the following media: image\n'+t.LABEL
    message = NS(id=10, date=AT, message=text, action=None, peer_id=NS(channel_id=t.CHANNEL_ID),
        entities=[NS(offset=len(text[:text.rindex(t.LABEL)].encode('utf-16-le'))//2,
        length=len(t.LABEL), url='https://truthsocial.com/@realDonaldTrump/117500000000000001')],
        media=attached, photo=photo, document=None)
    return m, t, message, classes


def test_actual_photo_is_not_confused_with_marker_only(media):
    m,t,msg,_=media
    item=t.extract(msg,AT)[0]
    assert item['media']['status']=='not_acquired' and item['media']['kind']=='photo'
    msg.media=None;msg.photo=None
    marker=t.extract(msg,AT)[0]
    assert marker['has_media'] and marker['media']['status']=='marker_only'
    assert m.asset_candidate(msg) is None


def test_flag_off_has_no_descriptor_or_reader_download(media, monkeypatch):
    m,t,msg,_=media
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED','false')
    item=t.extract(msg,AT)[0]
    assert 'media' not in item
    client=NS(download_media=AsyncMock())
    assert asyncio.run(m.capture(client,msg,item,AT))==item
    client.download_media.assert_not_called()


def test_webpage_document_and_unapproved_media_never_download(media):
    m,t,msg,classes=media
    msg.media=NS(webpage=NS(photo=msg.photo));msg.photo=None
    assert m.asset_candidate(msg) is None
    d=classes['Document']();d.id=9;d.size=4;d.mime_type='application/pdf';d.attributes=[]
    msg.media=classes['MessageMediaDocument']();msg.media.document=d
    assert m.asset_candidate(msg) is None
    d.mime_type='video/mp4';d.attributes=[classes['DocumentAttributeVideo']()]
    assert m.asset_candidate(msg)['kind']=='video'


def captured(media):
    m,t,msg,_=media
    async def download(message,file):
        file.write(b'\xff\xd8\xff\xd9')
    client=NS(download_media=AsyncMock(side_effect=download))
    item=asyncio.run(m.capture(client,msg,t.extract(msg,AT)[0],AT))
    return item,client


def test_capture_is_hash_bound_private_and_source_bound(media):
    m,t,msg,_=media
    item,client=captured(media)
    d=item['media']
    assert d['status']=='available' and d['sha256']==hashlib.sha256(b'\xff\xd8\xff\xd9').hexdigest()
    assert d['bytes']==4 and t.valid_item(item,AT)
    assert len(list(m.CACHE.iterdir()))==1
    assert 'file_reference' not in json.dumps(item) and 'access_hash' not in json.dumps(item)
    changed=copy.deepcopy(item);changed['relay_message_id']+=1
    assert not t.valid_item(changed,AT)


@pytest.mark.parametrize('damage',['oversize','download_error','wrong_magic','future','wrong_source'])
def test_failed_or_unbound_capture_never_fabricates_asset(media,damage):
    m,t,msg,_=media
    item=t.extract(msg,AT)[0]
    if damage=='future':item['observed_at']=(AT+timedelta(seconds=1)).isoformat()
    if damage=='wrong_source':item['relay_channel_id']=999
    async def download(message,file):
        if damage=='download_error':raise RuntimeError('private provider text')
        file.write(b'x'*(m.PHOTO_MAX+1) if damage=='oversize' else b'not-an-image')
    client=NS(download_media=AsyncMock(side_effect=download))
    result=asyncio.run(m.capture(client,msg,item,AT))
    assert result.get('media',{}).get('status')!='available'
    assert not m.CACHE.exists() or not list(m.CACHE.iterdir())
    assert 'private provider' not in json.dumps(result)


def test_source_edit_or_corrupt_cache_refuses_public_asset(media,monkeypatch):
    m,t,msg,_=media
    item,_=captured(media);envelope={'item':item,'media_version':m.VERSION};row={'id':1,'message':'frozen','status':'sent','event_type':'trump_truth_post','dedupe_key':'synthetic-only'}
    monkeypatch.setattr(t,'checked_archive',lambda *a:envelope)
    monkeypatch.setattr(m,'_receipt',lambda *a:{'status':'complete','asset_sha256':item['media']['sha256'],'media_message_id':123,'binding':m._receipt_binding(row)})
    public=m.public_media(row,envelope,AT)
    assert public['status']=='available' and public['asset_token']!=item['media']['sha256']
    assert m.read_public_asset(public['asset_token'],row,envelope,AT)[0]==b'\xff\xd8\xff\xd9'
    assert not any(k in json.dumps(public) for k in ('access_hash','file_reference','assets/'))
    (m.CACHE/item['media']['sha256']).write_bytes(b'changed')
    assert m.public_media(row,envelope,AT)['status']=='unavailable'
    with pytest.raises(ValueError):m.read_public_asset(public['asset_token'],row,envelope,AT)


def test_caption_fits_without_cutting_and_long_translation_has_two_tracked_stages(media):
    m,_,_,_=media
    short=m.delivery_plan('עברית מלאה',{'truth_url':'https://truthsocial.com/@realDonaldTrump/117500000000000001'})
    assert short['text'] is None and 'עברית מלאה' in short['caption']
    long='עברית מלאה '*200
    planned=m.delivery_plan(long,{'truth_url':'https://truthsocial.com/@realDonaldTrump/117500000000000001'})
    from telegram_presentation import utf16_length
    assert planned['text']==long and utf16_length(planned['caption'])<=1024
    assert '…' not in planned['text']


@pytest.fixture
def db(media,tmp_path,monkeypatch):
    import database
    import scanner_engine
    import stock_scanner
    monkeypatch.setattr(database,'DATABASE_URL','')
    monkeypatch.setattr(database,'_SQLITE_DB_PATH',str(tmp_path/'media.sqlite'))
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_MARKET_NEWS_THREAD_ID','991')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','synthetic-only')
    monkeypatch.setenv('TELEGRAM_CHAT_ID','-1001')
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME','false')
    monkeypatch.delenv('TELEGRAM_NEWS_NOT_BEFORE',raising=False)
    database.init_database()
    monkeypatch.setattr(scanner_engine,'now_z',lambda:AT.isoformat())
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    return database


def claimed(db,media,long=False):
    m,t,msg,_=media
    if long:
        body='Policy continues. '*70
        text=t.HEADER+'\n'+body+'\n'+t.LABEL;msg.message=text
        msg.entities[0].offset=len(text[:text.rindex(t.LABEL)].encode('utf-16-le'))//2
    item,_=captured(media)
    assert t.ingest([item],AT)['inserted']==1
    import trump_truth_translation as h
    def translated(system,payload,schema):
        return {'text_he':'המדיניות ממשיכה. '*90} if 'text_he' in schema['properties'] else {
            'faithful':True,'fluent_hebrew':True,'complete':True,'unsupported_claims':False}
    assert h.prepare(at=AT,completion=translated)['prepared']==1
    with db.get_db_connection() as c:
        row=dict(c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id DESC LIMIT 1').fetchone())
        assert row['status']==m.READY
        lease=(AT+timedelta(minutes=5)).isoformat()
        c.execute('UPDATE scanner_telegram_outbox SET status=?,next_attempt_at=? WHERE id=?',(m.SENDING,lease,row['id']))
    row.update(status=m.SENDING,next_attempt_at=lease)
    return row


def test_single_caption_ack_is_durable_and_never_resent(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media)
    send=Mock(return_value={'message_id':123})
    monkeypatch.setattr(m,'_send',send)
    assert m.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    r=m._receipt(row)
    assert r['status']=='complete' and r['media_message_id']==123 and r['text_message_id'] is None
    assert m.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    assert send.call_count==1
    with db.get_db_connection() as c:
        public=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(m.VERSION+':asset:'+m._public_token(r['binding'],r['asset_sha256']),)).fetchone()
        assert json.loads(public['value_json'])['row_id']==row['id']


def test_long_hebrew_uses_two_durable_acks_no_clipping(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media,long=True)
    send=Mock(side_effect=[{'message_id':123},{'message_id':124}]);monkeypatch.setattr(m,'_send',send)
    assert m.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    assert [call.args[0] for call in send.call_args_list]==['sendPhoto','sendMessage']
    assert send.call_args_list[1].args[1]['text'].count('המדיניות ממשיכה.')==90
    r=m._receipt(row);assert (r['media_message_id'],r['text_message_id'])==(123,124)


@pytest.mark.parametrize('unknown_stage',['media','text'])
def test_unknown_ack_terminal_and_no_untracked_fallback(db,media,monkeypatch,unknown_stage):
    m,_,_,_=media;row=claimed(db,media,long=True)
    send=Mock(side_effect=[{'unknown':True}] if unknown_stage=='media' else [{'message_id':123},{'unknown':True}])
    monkeypatch.setattr(m,'_send',send)
    assert json.loads(m.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is True
    assert send.call_count==(1 if unknown_stage=='media' else 2)
    assert m._receipt(row)['status']=='unknown'
    assert json.loads(m.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is True
    assert send.call_count==(1 if unknown_stage=='media' else 2)


def test_known_media_ack_text_rate_limit_resumes_only_text(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media,long=True)
    send=Mock(side_effect=[{'message_id':123},{'retry':True,'reason':'rate_limited'},{'message_id':124}])
    monkeypatch.setattr(m,'_send',send)
    assert json.loads(m.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is False
    assert m._receipt(row)['status']=='retry_text'
    assert m.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    assert [call.args[0] for call in send.call_args_list]==['sendPhoto','sendMessage','sendMessage']


def test_crash_after_writeahead_does_not_retry_uncertain_media(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media)
    # Failure after the external boundary, before a durable ACK, leaves its WAL.
    def crash(*a):raise KeyboardInterrupt()
    monkeypatch.setattr(m,'_send',crash)
    with pytest.raises(KeyboardInterrupt):m.dispatch(row,{'telegram_enabled':True},AT)
    assert m._receipt(row)['status']=='media_sending'
    never=Mock();monkeypatch.setattr(m,'_send',never)
    assert json.loads(m.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is True
    never.assert_not_called()


def test_old_selector_ignores_new_media_queue_and_disabled_media_never_sends(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media)
    with db.get_db_connection() as c:
        assert not c.execute("SELECT id FROM scanner_telegram_outbox WHERE status IN ('pending','retry','trump_pending','trump_retry','trump_hebrew_ready','trump_hebrew_retry')").fetchall()
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED','false')
    never=Mock();monkeypatch.setattr(m,'_send',never)
    assert json.loads(m.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is True
    never.assert_not_called()


def test_postdownload_observation_is_not_compared_to_prefetch_cycle_time(db,media,monkeypatch):
    m,t,msg,_=media
    finished=AT+timedelta(seconds=2)
    monkeypatch.setattr(m,'_now',lambda:finished)
    item,_=captured(media)
    assert item['media']['captured_at']==finished.isoformat()
    import news_pipeline
    monkeypatch.setattr(news_pipeline,'_now',lambda at=None:at or finished)
    assert news_pipeline.ingest_items([item],AT)['inserted']==1


def test_postdownload_future_capture_is_still_rejected(db,media,monkeypatch):
    m,t,msg,_=media
    monkeypatch.setattr(m,'_now',lambda:AT+timedelta(seconds=2))
    item,_=captured(media)
    import news_pipeline
    monkeypatch.setattr(news_pipeline,'_now',lambda at=None:at or AT+timedelta(seconds=1))
    assert news_pipeline.ingest_items([item],AT)['inserted']==0


def test_forged_clean_source_body_cannot_reuse_genuine_media(media):
    m,t,msg,_=media
    item=t.extract(msg,AT)[0]
    item['text_excerpt']='A forged clean caption never present in the relay.'
    item['media']['binding']=m._binding(item)
    async def download(message,file):file.write(b'\xff\xd8\xff\xd9')
    client=NS(download_media=AsyncMock(side_effect=download))
    result=asyncio.run(m.capture(client,msg,item,AT))
    assert result['media']['status']!='available'
    client.download_media.assert_not_called()


@pytest.mark.parametrize('field,value',[('media_message_id',True),('text_message_id',False),('status','made_up')])
def test_malformed_durable_ack_cannot_claim_complete(db,media,monkeypatch,field,value):
    m,_,_,_=media;row=claimed(db,media)
    send=Mock(return_value={'message_id':123});monkeypatch.setattr(m,'_send',send)
    assert m.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    damaged=m._receipt(row);damaged[field]=value
    with db.get_db_connection() as c:c.execute('UPDATE scanner_settings SET value_json=? WHERE key=?',(json.dumps(damaged),m.receipt_key(row)))
    assert json.loads(m.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is True
    assert send.call_count==1


def test_complete_published_asset_survives_flag_and_boundary_changes(db,media,monkeypatch):
    m,t,_,_=media;row=claimed(db,media)
    monkeypatch.setattr(m,'_send',Mock(return_value={'message_id':123}))
    assert m.dispatch(row,{'telegram_enabled':True},AT)=='sent'
    with db.get_db_connection() as c:
        c.execute('UPDATE scanner_telegram_outbox SET status=?,sent_at=? WHERE id=?',('sent',AT.isoformat(),row['id']))
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED','false')
    monkeypatch.setenv('TELEGRAM_TRUMP_TRUTH_NOT_BEFORE',(AT+timedelta(minutes=1)).isoformat())
    token=m._public_token(m._receipt_binding(row),json.loads(row['message'])['item']['media']['sha256'])
    with db.get_db_connection() as c:
        c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        data,mime=m.public_asset(token,c,AT+timedelta(minutes=2))
    assert data==b'\xff\xd8\xff\xd9' and mime=='image/jpeg'


def test_genuine_mp4_document_has_bounded_hash_checked_asset(media):
    m,t,msg,types=media
    data=b'\x00\x00\x00\x14ftypisom'
    document=types['Document']();document.id=9;document.size=len(data)
    document.mime_type='video/mp4';document.attributes=[types['DocumentAttributeVideo']()]
    msg.media=types['MessageMediaDocument']();msg.media.document=document;msg.document=document;msg.photo=None
    async def download(message,file):file.write(data)
    result=asyncio.run(m.capture(NS(download_media=AsyncMock(side_effect=download)),msg,t.extract(msg,AT)[0],AT))
    assert result['media']['status']=='available' and result['media']['kind']=='video'
    assert m._read(result['media']['sha256'],len(data))==data


def test_per_minute_budget_stops_third_download(media):
    m,t,msg,_=media
    async def download(message,file):file.write(b'\xff\xd8\xff\xd9')
    client=NS(download_media=AsyncMock(side_effect=download))
    statuses=[]
    for number in (10,11,12):
        msg.id=number
        statuses.append(asyncio.run(m.capture(client,msg,t.extract(msg,AT)[0],AT))['media']['status'])
    assert statuses==['available','available','unavailable'] and client.download_media.call_count==2


def test_untrusted_session_path_blocks_download(media,monkeypatch,tmp_path):
    m,t,msg,_=media
    import telegram_news_reader as reader
    bad=tmp_path/'directory-not-session';bad.mkdir()
    monkeypatch.setattr(reader,'SESSION',bad)
    client=NS(download_media=AsyncMock())
    assert asyncio.run(m.capture(client,msg,t.extract(msg,AT)[0],AT))['media']['status']=='unavailable'
    client.download_media.assert_not_called()


@pytest.mark.parametrize('damage',[None,'boolean_id','wrong_chat','wrong_thread','boolean_thread','missing_thread','redirect','rate_limit'])
def test_media_bot_ack_identity_and_safe_transport(db,media,monkeypatch,damage):
    m,_,_,_=media
    import requests
    result={'message_id':123,'chat':{'id':-1001},'message_thread_id':991}
    status=200;body={'ok':True,'result':result}
    if damage=='boolean_id':result['message_id']=True
    if damage=='wrong_chat':result['chat']['id']=-1002
    if damage=='wrong_thread':result['message_thread_id']=777
    if damage=='boolean_thread':result['message_thread_id']=True
    if damage=='missing_thread':result.pop('message_thread_id')
    if damage=='redirect':status=302
    if damage=='rate_limit':status=429;body={'ok':False}
    response=NS(status_code=status,json=lambda:body)
    session=Mock();session.post.return_value=response
    monkeypatch.setattr(requests,'Session',lambda:session)
    value=m._send('sendPhoto',{'chat_id':'-1001','message_thread_id':991,'caption':'בדיקה'},('relay.jpg',b'\xff\xd8\xff\xd9','image/jpeg'))
    assert value==({'message_id':123} if damage is None else {'retry':True,'reason':'rate_limited'} if damage=='rate_limit' else {'unknown':True})
    assert session.trust_env is False and session.post.call_args.kwargs['allow_redirects'] is False
    assert session.post.call_args.kwargs['timeout']==30
    session.close.assert_called_once()


def test_same_asset_later_unsent_post_cannot_hide_existing_published_asset(db,media,monkeypatch):
    m,_,msg,_=media
    monkeypatch.setattr(m,'_send',Mock(side_effect=[{'message_id':123},{'message_id':124}]))
    first=claimed(db,media)
    assert m.dispatch(first,{'telegram_enabled':True},AT)=='sent'
    with db.get_db_connection() as c:
        c.execute('UPDATE scanner_telegram_outbox SET status=?,sent_at=? WHERE id=?',('sent',AT.isoformat(),first['id']))
        first=dict(c.execute('SELECT * FROM scanner_telegram_outbox WHERE id=?',(first['id'],)).fetchone())
        envelope=json.loads(first['message'])
        token=m.public_media(first,envelope,AT,conn=c)['asset_token']
    assert token
    msg.id=11;msg.entities[0].url='https://truthsocial.com/@realDonaldTrump/117500000000000002'
    second=claimed(db,media)
    assert m.dispatch(second,{'telegram_enabled':True},AT)=='sent'
    # The second media ACK is durable, but the enclosing outbox commit crashes.
    with db.get_db_connection() as c:
        assert c.execute('SELECT status FROM scanner_telegram_outbox WHERE id=?',(second['id'],)).fetchone()['status']==m.SENDING
        assert m.public_asset(token,c,AT)==(b'\xff\xd8\xff\xd9','image/jpeg')


def posix_guards(module):
    # Exercise literal production guard functions on Windows without changing
    # global os.name/Path semantics or creating a real privileged/session file.
    source=inspect.getsource(module._secure)+'\n'+inspect.getsource(module._session_parent)
    env={'os':NS(name='posix',geteuid=lambda:10001),'stat':stat}
    exec(compile(ast.parse(source),'<actual POSIX metadata guards>','exec'),env)
    return env


@pytest.mark.parametrize('mode',[0o700,0o750,0o755])
def test_protected_existing_session_parent_allows_readonly_listing(media,mode):
    m,_,_,_=media;n=posix_guards(m)
    info=NS(st_mode=stat.S_IFDIR|mode,st_uid=10001)
    assert n['_session_parent'](NS(lstat=lambda:info)) is info


@pytest.mark.parametrize('kind,mode,owner',[
    (stat.S_IFDIR,0o775,10001),(stat.S_IFDIR,0o777,10001),(stat.S_IFDIR,0o702,10001),
    (stat.S_IFDIR,0o755,0),(stat.S_IFLNK,0o700,10001),(stat.S_IFREG,0o600,10001)])
def test_untrusted_session_parent_stays_blocked(media,kind,mode,owner):
    m,_,_,_=media;n=posix_guards(m)
    with pytest.raises(ValueError):n['_session_parent'](NS(lstat=lambda:NS(st_mode=kind|mode,st_uid=owner)))


@pytest.mark.parametrize('kind,mode,owner',[
    (stat.S_IFREG,0o640,10001),(stat.S_IFREG,0o600,0),(stat.S_IFLNK,0o600,10001)])
def test_session_file_guard_remains_exact_0600_owned_regular(media,kind,mode,owner):
    m,_,_,_=media;n=posix_guards(m)
    with pytest.raises(ValueError):n['_secure'](NS(lstat=lambda:NS(st_mode=kind|mode,st_uid=owner)))


@pytest.mark.parametrize('mode',[0o750,0o755])
def test_asset_cache_directory_remains_exact_0700(media,mode):
    m,_,_,_=media;n=posix_guards(m)
    with pytest.raises(ValueError):n['_secure'](NS(lstat=lambda:NS(st_mode=stat.S_IFDIR|mode,st_uid=10001)),True)


def test_expired_claim_cannot_begin_an_external_stage(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media)
    expired=(AT-timedelta(seconds=1)).isoformat()
    with db.get_db_connection() as c:c.execute('UPDATE scanner_telegram_outbox SET next_attempt_at=? WHERE id=?',(expired,row['id']))
    row['next_attempt_at']=expired
    send=Mock(return_value={'message_id':123});monkeypatch.setattr(m,'_send',send)
    result=m.dispatch(row,{'telegram_enabled':True},AT)
    assert result!='sent' and json.loads(result)['terminal'] is True
    send.assert_not_called()


def test_changed_live_claim_deadline_cannot_be_borrowed(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media)
    changed=(AT+timedelta(minutes=6)).isoformat()
    with db.get_db_connection() as c:c.execute('UPDATE scanner_telegram_outbox SET next_attempt_at=? WHERE id=?',(changed,row['id']))
    send=Mock(return_value={'message_id':123});monkeypatch.setattr(m,'_send',send)
    assert json.loads(m.dispatch(row,{'telegram_enabled':True},AT))['terminal'] is True
    send.assert_not_called()


def test_real_stage_clock_expiry_prevents_second_external_call(db,media,monkeypatch):
    m,_,_,_=media;row=claimed(db,media,long=True)
    clock=[AT];monkeypatch.setattr(m,'_now',lambda:clock[0])
    def first_ack(*a):
        clock[0]=AT+timedelta(minutes=5,seconds=1)
        return {'message_id':123}
    send=Mock(side_effect=first_ack);monkeypatch.setattr(m,'_send',send)
    assert json.loads(m.dispatch(row,{'telegram_enabled':True}))['terminal'] is True
    assert send.call_count==1
