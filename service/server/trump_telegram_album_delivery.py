"""One bounded Telegram album, with write-ahead stages and no uncertain replay.

Only captured private assets and an already accepted Hebrew presentation are
used. Source acquisition, translation and generic text fallback are forbidden.
"""
import hashlib
import os
from contextlib import nullcontext
from datetime import datetime, timezone

import trump_truth_media as m

VERSION = 'trump_telegram_album_v1'
SENDING = 'trump_album_sending'


def _now(): return datetime.now(timezone.utc)


def _hash(value): return hashlib.sha256(value.encode()).hexdigest()


def receipt_key(row):
    if type(row.get('id')) is not int or row['id']<=0: raise ValueError('album_row_invalid')
    return VERSION+':delivery:'+str(row['id'])


def _checked(row, value):
    fields={'version','binding','destination','album_ref','manifest_sha256','member_count',
            'text_sha256','caption_sha256','text_required','message_ids','media_group_id','text_message_id','status'}
    if (type(value) is not dict or set(value)!=fields or value['version']!=VERSION
            or value['binding']!=m._receipt_binding(row)): raise ValueError('album_receipt_invalid')
    for key in ('binding','destination','album_ref','manifest_sha256','text_sha256','caption_sha256'):
        if type(value[key]) is not str or not m._HASH.fullmatch(value[key]): raise ValueError('album_receipt_invalid')
    count=value['member_count'];ids=value['message_ids'];group=value['media_group_id'];text=value['text_message_id']
    if type(count) is not int or not 2<=count<=10 or type(value['text_required']) is not bool: raise ValueError('album_receipt_invalid')
    if type(ids) is not list or any(type(v) is not int or v<=0 for v in ids) or len(set(ids))!=len(ids): raise ValueError('album_receipt_invalid')
    if ids:
        if len(ids)!=count or type(group) is not str or not group.strip() or len(group)>256: raise ValueError('album_receipt_invalid')
    elif group is not None: raise ValueError('album_receipt_invalid')
    if text is not None and (type(text) is not int or text<=0 or text in ids or not value['text_required']): raise ValueError('album_receipt_invalid')
    status=value['status']
    if status not in {'new','album_sending','retry_album','album_sent','text_sending','retry_text','text_sent','complete','unknown'}: raise ValueError('album_receipt_invalid')
    if status in {'new','album_sending','retry_album'} and (ids or text is not None): raise ValueError('album_receipt_invalid')
    if status in {'album_sent','text_sending','retry_text','text_sent','complete'} and not ids: raise ValueError('album_receipt_invalid')
    if status in {'album_sent','text_sending','retry_text'} and text is not None: raise ValueError('album_receipt_invalid')
    if status in {'text_sending','retry_text','text_sent'} and not value['text_required']: raise ValueError('album_receipt_invalid')
    if status=='text_sent' and text is None: raise ValueError('album_receipt_invalid')
    if status=='complete' and value['text_required']!=(text is not None): raise ValueError('album_receipt_invalid')
    return value


def receipt(row, conn=None):
    from database import get_db_connection
    with nullcontext(conn) if conn is not None else get_db_connection() as c:
        found=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(receipt_key(row),)).fetchone()
    if not found: return None
    if len(found['value_json'].encode())>8192: raise ValueError('album_receipt_invalid')
    return _checked(row,m._json(found['value_json']))


def _save(row, value, expected, *, at=None):
    from database import get_db_connection, begin_write_transaction, using_postgres
    _checked(row,value)
    with get_db_connection() as c:
        begin_write_transaction(c.cursor())
        query='SELECT status,message,next_attempt_at,event_type,dedupe_key FROM scanner_telegram_outbox WHERE id=?'
        if using_postgres():query+=' FOR UPDATE'
        active=c.execute(query,(row['id'],)).fetchone()
        stamp=m._instant(at or _now())
        if (row.get('status')!=SENDING or not active or active['status']!=SENDING
                or active['message']!=row['message'] or active['event_type']!=row['event_type']
                or active['dedupe_key']!=row['dedupe_key'] or active['next_attempt_at']!=row.get('next_attempt_at')
                or stamp>=m._instant(active['next_attempt_at'])): raise ValueError('album_lease_revoked')
        old=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(receipt_key(row),)).fetchone()
        if (m._json(old['value_json']) if old else None)!=expected: raise ValueError('album_receipt_changed')
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',
                  (receipt_key(row),m.wire(value),stamp.isoformat()))


def _send_album(fields, members):
    """One call, no proxies/redirects/retry; only complete exact album ACKs count."""
    import requests
    from telegram_topics import without_news_metadata
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise ValueError('album_credentials_missing')
    session=requests.Session();session.trust_env=False
    try:
        if type(members) is not list or not 2<=len(members)<=10: raise ValueError('album_members_invalid')
        media=[];files={};total=0
        for index,item in enumerate(members):
            d=item['media'];kind=d['kind'];name='asset'+str(index)
            if kind not in {'photo','video'} or d['mime_type']!={'photo':'image/jpeg','video':'video/mp4'}[kind]: raise ValueError('album_members_invalid')
            if type(d['bytes']) is not int or d['bytes']<=0: raise ValueError('album_members_invalid')
            total+=d['bytes']
            if total>64*1024*1024: raise ValueError('album_members_invalid')
            data=m._read(d['sha256'],d['bytes'])
            files[name]=('relay'+str(index)+('.jpg' if kind=='photo' else '.mp4'),data,d['mime_type'])
            entry={'type':kind,'media':'attach://'+name}
            if index==0:entry['caption']=without_news_metadata(fields.get('caption',''))
            media.append(entry)
        data={k:v for k,v in fields.items() if k!='caption'};data['media']=m.wire(media)
        response=session.post('https://api.telegram.org/bot'+token+'/sendMediaGroup',data=data,files=files,timeout=30,allow_redirects=False)
        body=response.json()
        if response.status_code==429 and type(body) is dict and body.get('ok') is False and body.get('error_code')==429:
            return {'retry':True,'reason':'rate_limited'}
        if response.status_code!=200 or type(body) is not dict or body.get('ok') is not True:return {'unknown':True}
        result=body.get('result')
        if type(result) is not list or len(result)!=len(members):return {'unknown':True}
        ids=[];group=None
        for item,ack in zip(members,result):
            if (type(ack) is not dict or type(ack.get('message_id')) is not int or ack['message_id']<=0
                    or ack['message_id'] in ids or type(ack.get('chat')) is not dict
                    or type(ack['chat'].get('id')) is not int or str(ack['chat']['id'])!=str(fields['chat_id'])
                    or type(ack.get('message_thread_id')) is not int or ack['message_thread_id']!=fields.get('message_thread_id')
                    or type(ack.get('media_group_id')) is not str or not ack['media_group_id'].strip()
                    or len(ack['media_group_id'])>256):return {'unknown':True}
            kind=item['media']['kind']
            if (kind=='photo' and (type(ack.get('photo')) is not list or not ack['photo'] or 'video' in ack)
                    or kind=='video' and (type(ack.get('video')) is not dict or 'photo' in ack)):return {'unknown':True}
            if group is not None and ack['media_group_id']!=group:return {'unknown':True}
            ids.append(ack['message_id']);group=ack['media_group_id']
        return {'message_ids':ids,'media_group_id':group}
    except requests.ConnectTimeout:return {'retry':True,'reason':'connect_timeout'}
    except Exception:return {'unknown':True}
    finally:session.close()


def _current(row, at):
    import trump_telegram_album as a
    from trump_truth_posts import checked_envelope, delivery_message
    from telegram_topics import destination_fields, thread_id_for_event
    if not a.enabled():raise ValueError('album_disabled')
    envelope=checked_envelope(row,at)
    if (not envelope or envelope.get('media_version')!=VERSION or envelope.get('presentation')!='hebrew_v1'
            or type(envelope.get('album_ref')) is not str or not m._HASH.fullmatch(envelope['album_ref'])):raise ValueError('album_fenced')
    members=a.checked_manifest(row,envelope,at)
    text=delivery_message(row,at,media_attached=True)
    if type(text) is not str or not text:raise ValueError('album_presentation_unavailable')
    if thread_id_for_event('trump_truth_post') is None:raise ValueError('album_topic_missing')
    chat=os.getenv('TELEGRAM_CHAT_ID','').strip()
    if not chat or not os.getenv('TELEGRAM_BOT_TOKEN','').strip():raise ValueError('album_credentials_missing')
    fields=destination_fields(chat,'trump_truth_post')
    return envelope,members,text,m.delivery_plan(text,envelope['item']),fields


def dispatch(row,cfg,at=None):
    """Claim-specific WAL: known ACKs resume; ambiguous/crashed stages never replay."""
    terminal=lambda reason:m.wire({'terminal':True,'reason':reason})
    if cfg.get('telegram_enabled') is not True:return terminal('trump_album_disabled')
    try:
        current=_current(row,at or _now())
        envelope,members,text,plan,fields=current
        frozen={'version':VERSION,'binding':m._receipt_binding(row),'destination':_hash(m.wire(fields)),
                'album_ref':envelope['album_ref'],'manifest_sha256':_hash(m.wire(members)),'member_count':len(members),
                'text_sha256':_hash(text),'caption_sha256':_hash(plan['caption']),'text_required':plan['text'] is not None,
                'message_ids':[],'media_group_id':None,'text_message_id':None,'status':'new'}
        value=receipt(row)
        if value is not None:
            if any(value[k]!=v for k,v in frozen.items() if k not in {'status','message_ids','media_group_id','text_message_id'}):return terminal('trump_album_receipt_invalid')
            if value['status']=='complete':return 'sent'
            if value['status'] not in {'retry_album','album_sent','retry_text','text_sent'}:return terminal('trump_album_delivery_unknown_manual_review')
        else:value=frozen
        for stage in ('album','text'):
            if stage=='album' and value['message_ids']:continue
            if stage=='text' and (not value['text_required'] or value['text_message_id']):continue
            if _current(row,at or _now())!=current:return terminal('trump_album_presentation_changed')
            old=None if value is frozen else value
            value={**value,'status':stage+'_sending'};_save(row,value,old,at=at)
            if stage=='album':result=_send_album({**fields,'caption':plan['caption']},members)
            else:
                from telegram_presentation import telegram_text
                result=m._send('sendMessage',{**fields,'text':telegram_text(plan['text'],limit=16384),'disable_web_page_preview':True})
            old=value
            if result.get('retry') and result.get('reason') in {'rate_limited','connect_timeout'}:
                value={**value,'status':'retry_'+stage};_save(row,value,old,at=at)
                return m.wire({'terminal':False,'reason':'trump_album_'+result['reason'],'retry_after':60})
            if stage=='album' and result.get('message_ids'):
                value={**value,'message_ids':result['message_ids'],'media_group_id':result.get('media_group_id'),'status':'album_sent'}
            elif stage=='text' and type(result.get('message_id')) is int and result['message_id']>0:
                value={**value,'text_message_id':result['message_id'],'status':'text_sent'}
            else:
                value={**value,'status':'unknown'};_save(row,value,old,at=at)
                return terminal('trump_album_delivery_unknown_manual_review')
            _save(row,value,old,at=at)
        old=value;value={**value,'status':'complete'};_save(row,value,old,at=at)
        return 'sent'
    except Exception:return terminal('trump_album_delivery_unknown_manual_review')
