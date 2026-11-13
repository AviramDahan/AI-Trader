"""Trump-only complete Hebrew + literal source publication, at most three ACKs.

No generation, source retrieval or media download on dispatch. Legacy Hebrew
and media receipts cannot certify this version's English/source part.
"""
import hashlib
import os
from contextlib import nullcontext
from datetime import datetime, timezone

import trump_truth_media as media

VERSION='bilingual_v1'
RECEIPT_VERSION='trump_bilingual_delivery_v1'
PENDING,WORKING,READY,RETRY,SENDING=('trump_bilingual_'+s for s in ('pending','preparing','ready','retry','sending'))


def requested():return os.getenv('TELEGRAM_TRUMP_TRUTH_BILINGUAL_ENABLED','false').strip().lower()=='true'


def enabled():
    from trump_truth_posts import enabled as source_enabled
    from trump_truth_translation import enabled as hebrew_enabled
    return requested() and source_enabled() and hebrew_enabled()


def _now():return datetime.now(timezone.utc)


def _hash(value):return hashlib.sha256(value.encode()).hexdigest()


def _block(text,direction):
    # Whole-block isolates avoid the unbounded per-number bidi expansion that
    # can turn an accepted2400-unit translation into an oversized wire message.
    return ('\u2067' if direction=='he' else '\u2066')+text+'\u2069'


def plan(item,cache,has_asset=False):
    """Exact FINAL wire. Never clip or double-format any approved/source text."""
    from trump_truth_translation import source_text,validate_text
    from trump_truth_posts import CHANNEL,instant
    from telegram_presentation import utf16_length
    status=cache['status'];source=source_text(item)
    if type(has_asset) is not bool or type(cache.get('text_he')) is not str:raise ValueError('bilingual_cache_invalid')
    if status not in {'translated','unavailable','media_only','link_only'}:raise ValueError('bilingual_cache_invalid')
    if status!='translated' and (cache['text_he'] or (status in {'media_only','link_only'} and source)):raise ValueError('bilingual_cache_invalid')
    if status=='translated':
        hebrew=validate_text({'text_he':cache['text_he']},source)
        he='תרגום AI לעברית של קטע הדיווח (לא אימות עובדות):\n'+hebrew
    elif status=='unavailable':he='התרגום לעברית אינו זמין כרגע. קטע המקור מובא בנפרד; אין כאן תרגום מומצא.'
    elif status=='link_only':he='שיתוף מחדש ללא גוף הפוסט בדיווח הממסר. אין המצאה של תוכן הקישור.'
    else:he='לא סופק גוף טקסט לתרגום. אין תמלול או תיאור מומצא של מדיה.'
    if source:
        en='Original relay excerpt (usually English; not verified full primary text):\n'+source
    elif status=='link_only':en='Link-only repost: the relay did not supply the quoted post text. No quoted text is invented.'
    else:en='No source text was supplied. Media is not transcribed or described.'
    title='📣 טראמפ / Trump · Truth Social'+(' · שיתוף מחדש / Repost' if item['is_repost'] else '')
    stamp=instant(item['relay_published_at']).strftime('%d.%m.%Y %H:%M UTC')
    disclaimer='דיווח ממסר בלבד; לא אומת מול המקור. / Relay only; not primary verification.\nOriginal publication time: NOT VERIFIED. Relay time: '+stamp
    links=item['truth_url']+'\nhttps://t.me/'+CHANNEL+'/'+str(item['relay_message_id'])
    footer=_block(disclaimer+'\n'+links,'en')
    combined=_block(title+'\n\n'+he,'he')+'\n\n'+_block(en,'en')+'\n\n'+footer
    texts=([{'stage':'combined','method':'sendMessage','text':combined,'languages':['he','source']}] if utf16_length(combined)<=4096 else [
        {'stage':'hebrew','method':'sendMessage','text':_block(title+'\n\n'+he,'he')+'\n\n'+footer,'languages':['he']},
        {'stage':'english','method':'sendMessage','text':_block('Trump · original/source excerpt\n\n'+en,'en')+'\n\n'+footer,'languages':['source']}])
    if any(utf16_length(p['text'])>4096 for p in texts):raise ValueError('bilingual_whole_part_bound')
    if has_asset:
        d=item['media'];method='sendPhoto' if d['kind']=='photo' else 'sendVideo'
        if len(texts)==1 and utf16_length(combined)<=1024:
            return [{'stage':'media','method':method,'text':combined,'languages':['he','source']}]
        caption=_block('טראמפ · מדיה מהדיווח; אין תמלול או אימות.','he')+'\n'+_block('Trump · relay media; no transcription or primary verification.\n'+item['truth_url'],'en')
        if utf16_length(caption)>1024:raise ValueError('bilingual_caption_bound')
        texts.insert(0,{'stage':'media','method':method,'text':caption,'languages':[]})
    return texts


def _metadata(parts):
    return [{k:p[k] for k in ('stage','method','languages')}|{'sha256':_hash(p['text'])} for p in parts]


def receipt_key(row):
    if type(row['id']) is not int or row['id']<=0:raise ValueError('bilingual_row_invalid')
    return RECEIPT_VERSION+':'+str(row['id'])


def _checked(row,value):
    fields={'version','binding','destination','asset_sha256','plan','acks','status','active_stage'}
    if (type(value) is not dict or set(value)!=fields or value['version']!=RECEIPT_VERSION
        or value['binding']!=media._receipt_binding(row)):raise ValueError('bilingual_receipt_invalid')
    for key in ('binding','destination'):
        if type(value[key]) is not str or not media._HASH.fullmatch(value[key]):raise ValueError('bilingual_receipt_invalid')
    if value['asset_sha256'] is not None and (type(value['asset_sha256']) is not str or not media._HASH.fullmatch(value['asset_sha256'])):raise ValueError('bilingual_receipt_invalid')
    p=value['plan']
    if type(p) is not list or not 1<=len(p)<=3:raise ValueError('bilingual_receipt_invalid')
    names=[];languages=set()
    for part in p:
        if type(part) is not dict or set(part)!={'stage','method','languages','sha256'}:raise ValueError('bilingual_receipt_invalid')
        name=part['stage'];names.append(name)
        if type(part['sha256']) is not str or not media._HASH.fullmatch(part['sha256']):raise ValueError('bilingual_receipt_invalid')
        if part['languages'] not in ([],['he'],['source'],['he','source']):raise ValueError('bilingual_receipt_invalid')
        languages.update(part['languages'])
        if name=='media':
            if part['method'] not in ('sendPhoto','sendVideo') or value['asset_sha256'] is None:raise ValueError('bilingual_receipt_invalid')
        elif part['method']!='sendMessage':raise ValueError('bilingual_receipt_invalid')
    if names not in (['combined'],['hebrew','english'],['media'],['media','combined'],['media','hebrew','english']) or languages!={'he','source'}:raise ValueError('bilingual_receipt_invalid')
    expected_languages={'combined':['he','source'],'hebrew':['he'],'english':['source']}
    for part in p:
        expected=expected_languages.get(part['stage'],['he','source'] if len(p)==1 else [])
        if part['languages']!=expected:raise ValueError('bilingual_receipt_invalid')
    if ('media' in names)!=(value['asset_sha256'] is not None):raise ValueError('bilingual_receipt_invalid')
    acks=value['acks']
    if type(acks) is not dict or any(k not in names or type(v) is not int or v<=0 for k,v in acks.items()):raise ValueError('bilingual_receipt_invalid')
    if set(acks)!=set(names[:len(acks)]):raise ValueError('bilingual_receipt_invalid')
    status=value['status'];active=value['active_stage']
    if status not in {'new','sending','retry','complete','unknown'}:raise ValueError('bilingual_receipt_invalid')
    if status=='complete':
        if set(acks)!=set(names) or active is not None:raise ValueError('bilingual_receipt_invalid')
    elif status=='new':
        if active is not None:raise ValueError('bilingual_receipt_invalid')
    elif len(acks)>=len(names) or active!=names[len(acks)]:raise ValueError('bilingual_receipt_invalid')
    return value


def receipt(row,conn=None):
    from database import get_db_connection
    with nullcontext(conn) if conn is not None else get_db_connection() as c:
        found=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(receipt_key(row),)).fetchone()
    if not found:return None
    if len(found['value_json'].encode())>8192:raise ValueError('bilingual_receipt_invalid')
    return _checked(row,media._json(found['value_json']))


def _save(row,value,expected,at=None):
    from database import get_db_connection,begin_write_transaction
    _checked(row,value)
    with get_db_connection() as c:
        begin_write_transaction(c.cursor())
        active=c.execute('SELECT status,message,next_attempt_at FROM scanner_telegram_outbox WHERE id=?',(row['id'],)).fetchone()
        stamp=media._instant(at or _now())
        if (not active or active['status']!=SENDING or active['message']!=row['message']
            or active['next_attempt_at']!=row.get('next_attempt_at') or stamp>=media._instant(active['next_attempt_at'])):raise ValueError('bilingual_lease_revoked')
        old=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(receipt_key(row),)).fetchone()
        if (media._json(old['value_json']) if old else None)!=expected:raise ValueError('bilingual_receipt_changed')
        c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',(receipt_key(row),media.wire(value),stamp.isoformat()))
        if value['status']=='complete' and value['asset_sha256'] is not None:
            index={'version':media.VERSION,'asset_sha256':value['asset_sha256'],'row_id':row['id'],'binding':value['binding']}
            token=media._public_token(value['binding'],value['asset_sha256'])
            c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',(media.VERSION+':asset:'+token,media.wire(index),stamp.isoformat()))


def _current(row,at):
    from trump_truth_posts import checked_envelope
    from trump_truth_translation import presentation
    if not enabled():return None
    envelope=checked_envelope(row,at)
    if not envelope or envelope.get('presentation')!=VERSION:return None
    cache=presentation(row,envelope,at)
    if cache is None:return None
    has_asset=envelope.get('media_version')==media.VERSION
    if has_asset and not media.enabled():return None
    return envelope,plan(envelope['item'],cache,has_asset)


def dispatch(row,cfg,at=None):
    terminal=lambda reason:media.wire({'terminal':True,'reason':reason})
    from telegram_topics import destination_fields,thread_id_for_event
    if cfg.get('telegram_enabled') is not True:return terminal('trump_bilingual_disabled')
    try:
        current=_current(row,at or _now())
        if current is None:return terminal('trump_bilingual_fenced')
        envelope,parts=current;d=envelope['item'].get('media')
        has_asset=envelope.get('media_version')==media.VERSION
        if has_asset and (not media.valid_descriptor(envelope['item'],at or _now()) or d['status']!='available'):return terminal('trump_bilingual_asset_invalid')
        data=media._read(d['sha256'],d['bytes']) if has_asset else None
        chat=os.getenv('TELEGRAM_CHAT_ID','').strip()
        if not chat or not os.getenv('TELEGRAM_BOT_TOKEN','').strip():return 'missing_credentials'
        if thread_id_for_event('trump_truth_post') is None:return terminal('trump_bilingual_topic_missing')
        fields=destination_fields(chat,'trump_truth_post')
        frozen={'version':RECEIPT_VERSION,'binding':media._receipt_binding(row),'destination':_hash(media.wire(fields)),
            'asset_sha256':d['sha256'] if has_asset else None,'plan':_metadata(parts),'acks':{},'status':'new','active_stage':None}
        value=receipt(row)
        if value:
            if any(value[k]!=frozen[k] for k in ('version','binding','destination','asset_sha256','plan')):return terminal('trump_bilingual_receipt_invalid')
            if value['status']=='complete':return 'sent'
            if value['status'] not in {'new','retry'}:return terminal('trump_bilingual_delivery_unknown_manual_review')
        else:value=frozen
        for part in parts:
            name=part['stage']
            if name in value['acks']:continue
            if _current(row,at or _now())!=current:return terminal('trump_bilingual_presentation_changed')
            old=None if value is frozen else value
            pending={**value,'status':'sending','active_stage':name};_save(row,pending,old,at);value=pending
            if name=='media':
                result=media._send(part['method'],{**fields,'caption':part['text']},('relay.jpg' if d['kind']=='photo' else 'relay.mp4',data,d['mime_type']))
            else:result=media._send('sendMessage',{**fields,'text':part['text'],'disable_web_page_preview':True})
            old=value
            if result.get('retry'):
                value={**value,'status':'retry'};_save(row,value,old,at)
                return media.wire({'terminal':False,'reason':'trump_bilingual_'+result['reason'],'retry_after':60})
            if type(result.get('message_id')) is not int or result['message_id']<=0:
                value={**value,'status':'unknown'};_save(row,value,old,at)
                return terminal('trump_bilingual_delivery_unknown_manual_review')
            value={**value,'acks':{**value['acks'],name:result['message_id']},'status':'new','active_stage':None}
            _save(row,value,old,at)
        old=value;value={**value,'status':'complete'};_save(row,value,old,at)
        return 'sent'
    except Exception:return terminal('trump_bilingual_delivery_unknown_manual_review')


def published_receipt(row,envelope,conn=None,at=None):
    """Historic complete bilingual proof; no flags/fence/inference or recursion.

    A missing translation cache remains NOT_RETAINED, not reconstruction. If a
    cache exists, its exact accepted plan must match the actual sent part hashes.
    """
    try:
        if (row.get('status')!='sent' or envelope.get('presentation')!=VERSION
            or media._json(row['message'])!=envelope or media._instant(row['sent_at'])>media._instant(at or _now())):return False
        value=receipt(row,conn)
        if not value or value['status']!='complete':return False
        has_asset=envelope.get('media_version')==media.VERSION
        if value['asset_sha256']!=(envelope['item'].get('media',{}).get('sha256') if has_asset else None):return False
        from database import get_db_connection
        from trump_truth_translation import cache_key,checked_cache
        with nullcontext(conn) if conn is not None else get_db_connection() as c:
            found=c.execute('SELECT value_json FROM scanner_settings WHERE key=?',(cache_key(row),)).fetchone()
        if found:
            if len(found['value_json'].encode())>8192:return False
            cache=checked_cache(row,envelope,media._json(found['value_json']))
            if _metadata(plan(envelope['item'],cache,has_asset))!=value['plan']:return False
        return True
    except (KeyError,ValueError,TypeError,AttributeError):return False


def media_receipt(row,envelope,conn=None,at=None):
    if not published_receipt(row,envelope,conn,at):return None
    value=receipt(row,conn)
    return {'status':'complete','binding':value['binding'],'asset_sha256':value['asset_sha256'],
        'media_message_id':value['acks'].get('media')}
