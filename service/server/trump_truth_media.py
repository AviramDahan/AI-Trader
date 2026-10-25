"""Opt-in genuine relay assets, private bounded cache and durable send stages.

No Truth/web URL is fetched. Only the existing authenticated, pinned public
reader may download an attached Telegram Photo or MP4 video Document. Missing
files stay link-only; this module never describes, transcribes or generates media.
"""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import threading
from contextlib import nullcontext
from datetime import datetime, timezone

VERSION = 'trump_truth_media_v1'
PENDING, WORKING, READY, RETRY, SENDING = ('trump_media_'+s for s in ('pending','preparing','ready','retry','sending'))
CACHE = Path(__file__).resolve().parents[2]/'.runtime/trump-truth-media-v1'
PHOTO_MAX, VIDEO_MAX = 8*1024*1024, 24*1024*1024
CACHE_MAX, CACHE_FILES = 128*1024*1024, 64
MAX_PER_MINUTE, MINUTE_BYTES = 2, 48*1024*1024
_lock = threading.Lock()
_budget_state = {'minute':None,'count':0,'bytes':0}
_verified_assets = {}
_HASH = re.compile('[0-9a-f]{64}')
_REASONS = {'not_acquired','marker_only','unsupported','dependency_unavailable',
    'budget_exhausted','download_unavailable','cache_unavailable'}


def _now():return datetime.now(timezone.utc)


def enabled():
    return os.getenv('TELEGRAM_TRUMP_TRUTH_MEDIA_ENABLED','false').strip().lower()=='true'


def wire(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def _json(raw):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('media_json_invalid')
            result[key]=value
        return result
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('media_json_invalid')))
    except (ValueError,RecursionError):raise ValueError('media_json_invalid') from None


def _instant(value):
    from trump_truth_posts import instant
    return instant(value)


def _types():
    from telethon.tl import types
    return types


def asset_candidate(message):
    """Strict file types; webpage previews, arbitrary documents and URLs fail."""
    try:
        t=_types();media=getattr(message,'media',None)
        if isinstance(media,t.MessageMediaPhoto) and isinstance(media.photo,t.Photo):
            photo=media.photo
            sizes=[]
            if not isinstance(photo.sizes,list) or len(photo.sizes)>16:return None
            for size in photo.sizes:
                value=getattr(size,'size',None)
                if type(value) is int and value>0:sizes.append(value)
                progressive=getattr(size,'sizes',None)
                if isinstance(progressive,list):sizes.extend(v for v in progressive if type(v) is int and v>0)
            if type(photo.id) is not int or photo.id<=0 or not sizes:return None
            size=max(sizes)
            if size>PHOTO_MAX:return None
            return {'kind':'photo','mime_type':'image/jpeg','declared_bytes':size,
                'asset_identity':hashlib.sha256(('photo:'+str(photo.id)).encode()).hexdigest()}
        if isinstance(media,t.MessageMediaDocument) and isinstance(media.document,t.Document):
            doc=media.document
            if (type(doc.id) is not int or doc.id<=0 or type(doc.size) is not int or not 0<doc.size<=VIDEO_MAX
                or doc.mime_type!='video/mp4' or not isinstance(doc.attributes,list) or len(doc.attributes)>16
                or not any(isinstance(v,t.DocumentAttributeVideo) for v in doc.attributes)):
                return None
            return {'kind':'video','mime_type':'video/mp4','declared_bytes':doc.size,
                'asset_identity':hashlib.sha256(('video:'+str(doc.id)).encode()).hexdigest()}
    except (ImportError,AttributeError,TypeError,ValueError):
        return None
    return None


def _binding(item):
    return hashlib.sha256(wire({k:item[k] for k in ('relay_channel_id','relay_message_id',
        'truth_post_id','truth_url','activation','relay_published_at','observed_at','text_excerpt','is_repost')}).encode()).hexdigest()


def describe(message,item):
    candidate=asset_candidate(message)
    return {'version':VERSION,'binding':_binding(item),'status':'not_acquired' if candidate else 'marker_only',
        'kind':candidate['kind'] if candidate else None,'mime_type':candidate['mime_type'] if candidate else None,
        'asset_identity':candidate['asset_identity'] if candidate else None,
        'sha256':None,'bytes':None,'captured_at':None,
        'reason':'not_acquired' if candidate else 'marker_only'}


def valid_descriptor(item,at):
    try:
        d=item['media']
        if (type(d) is not dict or set(d)!={'version','binding','status','kind','mime_type','asset_identity',
            'sha256','bytes','captured_at','reason'} or d['version']!=VERSION or d['binding']!=_binding(item)
            or d['status'] not in {'not_acquired','marker_only','unavailable','available'}):return False
        if d['status']=='marker_only':return (all(d[k] is None for k in ('kind','mime_type','asset_identity','sha256','bytes','captured_at')) and d['reason']=='marker_only')
        if d['kind'] not in {'photo','video'} or d['mime_type']!={'photo':'image/jpeg','video':'video/mp4'}[d['kind']]:return False
        if type(d['asset_identity']) is not str or not _HASH.fullmatch(d['asset_identity']):return False
        if d['status']!='available':return (d['reason'] in _REASONS and all(d[k] is None for k in ('sha256','bytes','captured_at')))
        return (d['reason'] is None and type(d['sha256']) is str and _HASH.fullmatch(d['sha256']) is not None
            and type(d['bytes']) is int and 0<d['bytes']<=({'photo':PHOTO_MAX,'video':VIDEO_MAX}[d['kind']])
            and _instant(item['observed_at'])<=_instant(d['captured_at'])<=_instant(at))
    except (KeyError,TypeError,ValueError,AttributeError):return False


def _secure(path,directory=False):
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode)):
        raise ValueError('media_cache_untrusted')
    if os.name!='nt' and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=(0o700 if directory else 0o600)):
        raise ValueError('media_cache_untrusted')
    return info


def _session_parent(path):
    # Existing session may live in an owned0755 runtime directory. Read/execute
    # listing does not grant session access: its file remains exact0600. Nobody
    # else may replace the path through group/other directory write authority.
    info=path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise ValueError('media_session_untrusted')
    if os.name!='nt' and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o022):raise ValueError('media_session_untrusted')
    return info


def _store(data,digest):
    CACHE.mkdir(mode=0o700,parents=True,exist_ok=True);_secure(CACHE,True)
    target=CACHE/digest
    if target.exists() or target.is_symlink():
        if _read(digest,len(data))!=data:raise ValueError('media_cache_conflict')
        return
    files=list(CACHE.iterdir())
    if len(files)>=CACHE_FILES:raise ValueError('media_cache_full')
    total=0
    for path in files:
        if not _HASH.fullmatch(path.name):raise ValueError('media_cache_untrusted')
        total+=_secure(path).st_size
    if total+len(data)>CACHE_MAX:raise ValueError('media_cache_full')
    temp=CACHE/(digest+'.tmp-'+os.urandom(8).hex())
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,target)
        if os.name!='nt':
            directory=os.open(CACHE,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(directory)
            finally:os.close(directory)
        _remember(digest,_signature(_secure(target)))
    finally:
        if temp.exists():temp.unlink()


def _read(digest,size):
    if not isinstance(digest,str) or not _HASH.fullmatch(digest) or type(size) is not int or not 0<size<=VIDEO_MAX:
        raise ValueError('media_asset_invalid')
    _secure(CACHE,True);path=CACHE/digest
    before=_secure(path)
    if before.st_size!=size:raise ValueError('media_asset_invalid')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as f:data=f.read(size+1)
    after=_secure(path)
    if (len(data)!=size or hashlib.sha256(data).hexdigest()!=digest
        or _signature(before)!=_signature(after)):raise ValueError('media_asset_invalid')
    _remember(digest,_signature(after))
    return data


def _signature(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _remember(digest,signature):
    with _lock:
        if len(_verified_assets)>=CACHE_FILES:_verified_assets.clear()
        _verified_assets[digest]=signature


def _verify(digest,size):
    if type(digest) is not str or not _HASH.fullmatch(digest) or type(size) is not int or not 0<size<=VIDEO_MAX:raise ValueError('media_asset_invalid')
    _secure(CACHE,True);info=_secure(CACHE/digest)
    if info.st_size!=size:raise ValueError('media_asset_invalid')
    if _verified_assets.get(digest)!=_signature(info):_read(digest,size)


class _BoundedBytes(io.BytesIO):
    def __init__(self,limit):super().__init__();self.limit=limit
    def write(self,value):
        if self.tell()+len(value)>self.limit:raise ValueError('media_download_bound')
        return super().write(value)


async def capture(client,message,item,at,*,session_path=None):
    """Existing reader only, ≤2 files/48MiB per minute; ≤30s and one file/post.

    A failed/unsupported file cannot become a send instruction. No auth/session
    references are serialized. Capture errors are fixed codes, never exceptions.
    """
    if not enabled() or 'media' not in item:return item
    from trump_truth_posts import valid_item,source_channel_id,extract
    result=dict(item);d=dict(item['media']);result['media']=d
    candidate=asset_candidate(message)
    if not candidate or d['status']=='marker_only':return result
    literal,reason=extract(message,at)
    if (reason or not literal or any(item.get(k)!=v for k,v in literal.items() if k not in {'observed_at','media'})
        or not valid_item(item,at) or message.id!=item['relay_message_id']
        or getattr(getattr(message,'peer_id',None),'channel_id',None)!=source_channel_id()
        or _instant(message.date)!=_instant(item['relay_published_at'])
        or candidate['asset_identity']!=d['asset_identity']):
        d.update(status='unavailable',reason='unsupported');return result
    try:
        if session_path is None:
            from telegram_news_reader import SESSION
            session_path=SESSION
        session_path=Path(session_path)
        _session_parent(session_path.parent);_secure(session_path)
    except (OSError,ValueError):
        d.update(status='unavailable',reason='download_unavailable');return result
    limit=PHOTO_MAX if candidate['kind']=='photo' else VIDEO_MAX
    minute=int(_instant(at).timestamp())//60
    with _lock:
        if _budget_state['minute']!=minute:_budget_state.update(minute=minute,count=0,bytes=0)
        if _budget_state['count']>=MAX_PER_MINUTE or _budget_state['bytes']+candidate['declared_bytes']>MINUTE_BYTES:
            d.update(status='unavailable',reason='budget_exhausted');return result
        _budget_state['count']+=1;_budget_state['bytes']+=candidate['declared_bytes']
    try:
        output=_BoundedBytes(min(limit,candidate['declared_bytes']))
        await asyncio.wait_for(client.download_media(message,file=output),timeout=30)
        data=output.getvalue()
        if not data or (candidate['kind']=='photo' and not data.startswith(b'\xff\xd8\xff')) or (candidate['kind']=='video' and (len(data)<12 or data[4:8]!=b'ftyp')):
            raise ValueError('media_file_invalid')
        digest=hashlib.sha256(data).hexdigest();_store(data,digest)
        finished=_now()
        if finished<_instant(at):raise ValueError('media_clock_invalid')
        result['observed_at']=finished.isoformat()
        d.update(binding=_binding(result),status='available',reason=None,sha256=digest,bytes=len(data),captured_at=finished.isoformat())
    except asyncio.CancelledError:raise
    except Exception:d.update(status='unavailable',reason='download_unavailable')
    return result


def delivery_plan(text,item):
    from telegram_presentation import telegram_text,utf16_length
    full=telegram_text(text,limit=16384)
    if utf16_length(full)>4096:raise ValueError('media_text_bound')
    if utf16_length(full)<=1024:return {'caption':full,'text':None}
    caption=telegram_text('📣 טראמפ · מדיה מצורפת מהדיווח בערוץ המעקב.\nאין תמלול או אימות תוכן.\n'+item['truth_url'],limit=16384)
    if utf16_length(caption)>1024:raise ValueError('media_caption_bound')
    return {'caption':caption,'text':text}


def receipt_key(row):
    if type(row['id']) is not int or row['id']<=0:raise ValueError('media_row_invalid')
    return VERSION+':'+str(row['id'])


def _receipt_binding(row):
    return hashlib.sha256(wire({'id':row['id'],'event_type':row['event_type'],
        'dedupe_key':row['dedupe_key'],'message':row['message']}).encode()).hexdigest()


def _public_token(binding,digest):
    # One immutable publication receipt, not one mutable latest-post alias for
    # identical bytes. An uncommitted later post cannot hide an older sent one.
    return hashlib.sha256(wire({'binding':binding,'asset_sha256':digest}).encode()).hexdigest()


def _receipt(row,conn=None):
    from database import get_db_connection
    with nullcontext(conn) if conn is not None else get_db_connection() as c:
        found=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(receipt_key(row),)).fetchone()
    if not found:return None
    if len(found['value_json'].encode())>8192:raise ValueError('media_receipt_invalid')
    return _checked_receipt(row,_json(found['value_json']))


def _checked_receipt(row,value):
    fields={'version','binding','destination','asset_sha256','text_sha256','text_required','media_message_id','text_message_id','status'}
    if type(value) is not dict or set(value)!=fields or value['version']!=VERSION or value['binding']!=_receipt_binding(row):raise ValueError('media_receipt_invalid')
    if any(type(value[k]) is not str or not _HASH.fullmatch(value[k]) for k in ('binding','destination','asset_sha256','text_sha256')):raise ValueError('media_receipt_invalid')
    if type(value['text_required']) is not bool:raise ValueError('media_receipt_invalid')
    if any(value[k] is not None and (type(value[k]) is not int or value[k]<=0) for k in ('media_message_id','text_message_id')):raise ValueError('media_receipt_invalid')
    status=value['status'];media_id=value['media_message_id'];text_id=value['text_message_id']
    if status not in {'new','media_sending','retry_media','media_sent','text_sending','retry_text','text_sent','complete','unknown'}:raise ValueError('media_receipt_invalid')
    if status in {'new','media_sending','retry_media'} and (media_id is not None or text_id is not None):raise ValueError('media_receipt_invalid')
    if status in {'media_sent','text_sending','retry_text','text_sent','complete'} and media_id is None:raise ValueError('media_receipt_invalid')
    if status in {'media_sent','text_sending','retry_text'} and text_id is not None:raise ValueError('media_receipt_invalid')
    if status=='text_sent' and text_id is None:raise ValueError('media_receipt_invalid')
    if status=='complete' and ((value['text_required'] and text_id is None) or (not value['text_required'] and text_id is not None)):
        raise ValueError('media_receipt_invalid')
    return value


def _save(row,value,expected,*,at=None):
    from database import get_db_connection,begin_write_transaction
    _checked_receipt(row,value)
    with get_db_connection() as c:
        begin_write_transaction(c.cursor())
        active=c.execute('SELECT status,message,next_attempt_at FROM scanner_telegram_outbox WHERE id=?',(row['id'],)).fetchone()
        stamp=_instant(at or _now())
        if (not active or active['status']!=SENDING or active['message']!=row['message']
            or active['next_attempt_at']!=row.get('next_attempt_at')
            or stamp>=_instant(active['next_attempt_at'])):raise ValueError('media_lease_revoked')
        old=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(receipt_key(row),)).fetchone()
        if (_json(old['value_json']) if old else None)!=expected:raise ValueError('media_receipt_changed')
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',
            (receipt_key(row),wire(value),stamp.isoformat()))
        if value['status']=='complete' and type(value.get('media_message_id')) is int and value['media_message_id']>0:
            public={'version':VERSION,'asset_sha256':value['asset_sha256'],'row_id':row['id'],'binding':value['binding']}
            c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',
                (VERSION+':asset:'+_public_token(value['binding'],value['asset_sha256']),wire(public),stamp.isoformat()))


def _send(method,fields,asset=None):
    """One Bot API call; no retry adapter, redirects, proxy or unknown-ACK retry."""
    import requests
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token:raise ValueError('media_credentials_missing')
    session=requests.Session();session.trust_env=False
    try:
        kw={'data':fields,'timeout':30,'allow_redirects':False}
        if asset:
            name,data,mime=asset;kw['files']={'photo' if method=='sendPhoto' else 'video':(name,data,mime)}
        response=session.post('https://api.telegram.org/bot'+token+'/'+method,**kw)
        body=response.json()
        if response.status_code==429 and isinstance(body,dict) and body.get('ok') is False:
            return {'retry':True,'reason':'rate_limited'}
        if response.status_code!=200 or type(body) is not dict or body.get('ok') is not True:return {'unknown':True}
        result=body.get('result')
        if (type(result) is not dict or type(result.get('message_id')) is not int or result['message_id']<=0
            or type(result.get('chat')) is not dict or type(result['chat'].get('id')) is not int
            or str(result['chat']['id'])!=str(fields['chat_id'])
            or type(result.get('message_thread_id')) is not int
            or result['message_thread_id']!=fields.get('message_thread_id')):return {'unknown':True}
        return {'message_id':result['message_id']}
    except requests.ConnectTimeout:return {'retry':True,'reason':'connect_timeout'}
    except Exception:return {'unknown':True}
    finally:session.close()


def dispatch(row,cfg,at=None):
    """Called ONLY for a durably claimed media row; every remote stage has a WAL.

    Known media ACK is never resent. A crash/ambiguous ACK is terminal, including
    text stage after media; no media-stage error causes a fallback text send.
    """
    terminal=lambda reason:wire({'terminal':True,'reason':reason})
    from trump_truth_posts import checked_envelope,delivery_message
    from telegram_topics import destination_fields,thread_id_for_event
    stamp=at or _now()
    if not enabled() or cfg.get('telegram_enabled') is not True:return terminal('trump_media_disabled')
    envelope=checked_envelope(row,stamp)
    if not envelope or envelope.get('media_version')!=VERSION:return terminal('trump_media_fenced')
    d=envelope['item'].get('media')
    if not valid_descriptor(envelope['item'],stamp) or d['status']!='available':return terminal('trump_media_unavailable')
    chat=os.getenv('TELEGRAM_CHAT_ID','').strip()
    if not chat or not os.getenv('TELEGRAM_BOT_TOKEN','').strip():return 'missing_credentials'
    if thread_id_for_event('trump_truth_post') is None:return terminal('trump_media_topic_missing')
    fields=destination_fields(chat,'trump_truth_post')
    try:
        data=_read(d['sha256'],d['bytes'])
        text=delivery_message(row,stamp,media_attached=True)
        if text is None:return terminal('trump_media_presentation_unavailable')
        plan=delivery_plan(text,envelope['item'])
        frozen={'version':VERSION,'binding':_receipt_binding(row),'destination':hashlib.sha256(wire(fields).encode()).hexdigest(),
            'asset_sha256':d['sha256'],'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'text_required':plan['text'] is not None,'media_message_id':None,'text_message_id':None,'status':'new'}
        value=_receipt(row)
        if value:
            if any(value.get(k)!=v for k,v in frozen.items() if k not in {'status','media_message_id','text_message_id'}):return terminal('trump_media_receipt_invalid')
            if value['status']=='complete':return 'sent'
            if value['status'] not in {'retry_media','media_sent','retry_text'}:return terminal('trump_media_delivery_unknown_manual_review')
        else:value=frozen
        for stage in ('media','text'):
            if stage=='media' and value.get('media_message_id'):continue
            if stage=='text' and plan['text'] is None:continue
            if stage=='text' and value.get('text_message_id'):continue
            # Current source/permissions must still hold before EACH side effect.
            check_at=_now() if at is None else at
            if not enabled() or checked_envelope(row,check_at)!=envelope:return terminal('trump_media_fenced')
            # Media ACK is not permission to publish a revoked/lost/replaced
            # Hebrew cache. Revalidate the exact frozen full presentation, never
            # regenerate it or fall back to the source body between stages.
            if delivery_message(row,check_at,media_attached=True)!=text:return terminal('trump_media_presentation_changed')
            expected=dict(value);value=dict(value,status=stage+'_sending');_save(row,value,expected if expected['status']!='new' else None,at=at)
            if stage=='media':
                method='sendPhoto' if d['kind']=='photo' else 'sendVideo'
                result=_send(method,{**fields,'caption':plan['caption']},('relay.jpg' if d['kind']=='photo' else 'relay.mp4',data,d['mime_type']))
            else:
                from telegram_presentation import telegram_text
                result=_send('sendMessage',{**fields,'text':telegram_text(plan['text'],limit=16384),'disable_web_page_preview':True})
            expected=dict(value)
            if result.get('retry'):
                value=dict(value,status='retry_'+stage);_save(row,value,expected,at=at)
                return wire({'terminal':False,'reason':'trump_media_'+result['reason'],'retry_after':60})
            if not result.get('message_id'):
                value=dict(value,status='unknown');_save(row,value,expected,at=at)
                return terminal('trump_media_delivery_unknown_manual_review')
            value=dict(value,**{stage+'_message_id':result['message_id']},status=stage+'_sent');_save(row,value,expected,at=at)
        expected=dict(value);value=dict(value,status='complete');_save(row,value,expected,at=at)
        return 'sent'
    except Exception:return terminal('trump_media_delivery_unknown_manual_review')


def prepare(limit=1,at=None):
    """No AI/fetch: only non-Hebrew media rows become ready in the existing loop."""
    if limit!=1:raise ValueError('media_prepare_limit')
    if not enabled():return {'prepared':0}
    from trump_truth_translation import enabled as hebrew_enabled
    if hebrew_enabled():return {'prepared':0}
    from database import get_db_connection,begin_write_transaction,using_postgres
    from trump_truth_posts import checked_envelope
    stamp=(at or datetime.now(timezone.utc)).isoformat()
    with get_db_connection() as c:
        begin_write_transaction(c.cursor())
        query='SELECT * FROM scanner_telegram_outbox WHERE event_type=? AND status=? AND next_attempt_at<=? ORDER BY id LIMIT 1'
        if using_postgres():query+=' FOR UPDATE SKIP LOCKED'
        found=c.execute(query,('trump_truth_post',PENDING,stamp)).fetchone()
        if not found:return {'prepared':0}
        row=dict(found);envelope=checked_envelope(row,at)
        status=READY if envelope and envelope.get('media_version')==VERSION and 'presentation' not in envelope else 'cancelled'
        c.execute('UPDATE scanner_telegram_outbox SET status=? WHERE id=? AND status=?',(status,row['id'],PENDING))
        return {'prepared':int(status==READY)}


def public_media(row,envelope,at=None,conn=None):
    """Published archive only; never expose transient refs, paths or Bot URLs."""
    result={'version':VERSION,'status':'unavailable','kind':None,'asset_token':None,'mime_type':None,'bytes':None}
    try:
        from trump_truth_posts import checked_archive
        if row.get('status')!='sent' or checked_archive(row,at)!=envelope:return result
        item=envelope['item'];d=item.get('media')
        if not d:return dict(result,status='marker_only' if item['has_media'] else 'none')
        if not valid_descriptor(item,at or datetime.now(timezone.utc)) or d['status']!='available':return result
        if envelope.get('presentation')=='bilingual_v1':
            from trump_truth_bilingual import media_receipt
            r=media_receipt(row,envelope,conn,at)
        else:r=_receipt(row,conn)
        if (not r or r.get('status')!='complete' or r.get('asset_sha256')!=d['sha256']
            or type(r.get('media_message_id')) is not int or r['media_message_id']<=0):return result
        _verify(d['sha256'],d['bytes'])
        return dict(result,status='available',kind=d['kind'],asset_token=_public_token(r['binding'],d['sha256']),mime_type=d['mime_type'],bytes=d['bytes'])
    except (ValueError,TypeError,KeyError,OSError):return result


def read_public_asset(token,row,envelope,at=None,conn=None):
    proof=public_media(row,envelope,at,conn)
    if proof['status']!='available' or proof['asset_token']!=token:raise ValueError('media_asset_unavailable')
    return _read(envelope['item']['media']['sha256'],proof['bytes']),proof['mime_type']


def public_asset(token,conn,at=None):
    """Constant-bound opaque-token lookup; caller owns a READ ONLY snapshot."""
    if not isinstance(token,str) or not _HASH.fullmatch(token):raise ValueError('media_asset_unavailable')
    found=conn.execute('SELECT value_json FROM scanner_settings WHERE key=?',(VERSION+':asset:'+token,)).fetchone()
    if not found or len(found['value_json'].encode())>1024:raise ValueError('media_asset_unavailable')
    value=_json(found['value_json'])
    if (type(value) is not dict or set(value)!={'version','asset_sha256','row_id','binding'} or value['version']!=VERSION
        or type(value['asset_sha256']) is not str or not _HASH.fullmatch(value['asset_sha256'])
        or type(value['binding']) is not str or not _HASH.fullmatch(value['binding'])
        or _public_token(value['binding'],value['asset_sha256'])!=token
        or type(value['row_id']) is not int or value['row_id']<=0):raise ValueError('media_asset_unavailable')
    row=conn.execute('SELECT id,dedupe_key,event_type,message,status,created_at,sent_at FROM scanner_telegram_outbox WHERE id=? AND event_type=? AND status=?',
        (value['row_id'],'trump_truth_post','sent')).fetchone()
    if not row:raise ValueError('media_asset_unavailable')
    row=dict(row)
    if _receipt_binding(row)!=value['binding']:raise ValueError('media_asset_unavailable')
    from trump_truth_posts import checked_archive
    envelope=checked_archive(row,at)
    if envelope is None:raise ValueError('media_asset_unavailable')
    return read_public_asset(token,row,envelope,at,conn)
