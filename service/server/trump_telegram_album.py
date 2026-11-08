"""Pinned Telegram albums: bounded, durable acquisition in existing catch-up.

No extra producer, schema, model or history replay. Unsupported/incomplete groups
hold this source cursor; other channels continue. Delivery has its own version.
"""
import copy
import hashlib
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from trump_truth_media import wire, _json

VERSION = 'trump_telegram_album_v1'
PENDING, WORKING, READY, RETRY, SENDING = ('trump_album_'+s for s in
    ('pending','preparing','ready','retry','sending'))
CLAIMED = 'trump_album_member_v1'
MAX_BYTES = 64*1024*1024
SETTLE_SECONDS = 60
STATE_BOUND = 65536


def enabled():
    from trump_telegram_channel import selected
    from trump_truth_posts import enabled as source_enabled
    from trump_truth_media import enabled as media_enabled
    return selected() and source_enabled() and media_enabled()


def _now():return datetime.now(timezone.utc)


def _key(group):
    if type(group) is not int or not 0<group<2**63:raise ValueError('album_identity')
    return VERSION+':acquire:'+str(group)


def _load(c,key,*,lock=False):
    from database import using_postgres
    q='SELECT value_json FROM scanner_settings WHERE key=?'
    if lock and using_postgres():q+=' FOR UPDATE'
    row=c.execute(q,(key,)).fetchone()
    if not row:return None
    if len(row['value_json'].encode())>STATE_BOUND:raise ValueError('album_state_bound')
    return _json(row['value_json'])


def _put(c,key,value,at):
    raw=wire(value)
    if len(raw.encode())>STATE_BOUND:raise ValueError('album_state_bound')
    c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?) '
        'ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at',
        (key,raw,at.isoformat()))


def fingerprint(members):
    # Observations/file downloads change clocks, not the immutable source revision.
    source=[]
    for item in members:
        v={k:v for k,v in item.items() if k not in {'media','observed_at','album_ref'}}
        v['asset_identity']=item['media']['asset_identity']
        source.append(v)
    return hashlib.sha256(wire(source).encode()).hexdigest()


def _source_members(messages,seed,current):
    from trump_telegram_channel import extract, CHANNEL_ID
    from trump_truth_media import asset_candidate
    from trump_truth_posts import instant
    group=getattr(seed,'grouped_id',None);_key(group)
    if (type(seed.id) is not int or not 0<seed.id<=2147483647 or
        getattr(getattr(seed,'peer_id',None),'channel_id',None)!=CHANNEL_ID):
        raise ValueError('album_identity')
    seen=set();pairs=[]
    for message in messages:
        if message is None:continue
        if (type(message.id) is not int or message.id in seen or
            not max(1,seed.id-10)<=message.id<=min(2147483647,seed.id+10) or
            getattr(getattr(message,'peer_id',None),'channel_id',None)!=CHANNEL_ID):
            raise ValueError('album_probe_identity')
        seen.add(message.id)
        if getattr(message,'grouped_id',None)!=group:continue
        item,reason=extract(message,current)
        candidate=asset_candidate(message)
        if reason or not item or not candidate or 'media' not in item:
            raise ValueError('album_member_invalid')
        pairs.append((message,item,candidate))
    pairs.sort(key=lambda p:p[0].id)
    ids=[p[0].id for p in pairs]
    if (not 2<=len(ids)<=10 or seed.id not in ids or ids!=list(range(ids[0],ids[-1]+1))
        or ids[0]<=seed.id-10 or ids[-1]>=seed.id+10):
        raise ValueError('album_membership_unverified')
    stamps=[instant(p[1]['relay_published_at']) for p in pairs]
    if max(stamps)-min(stamps)>timedelta(seconds=2):raise ValueError('album_time_span')
    if instant(current)-max(stamps)<timedelta(seconds=SETTLE_SECONDS):raise ValueError('album_settling')
    if len({p[1]['text_excerpt'] for p in pairs if p[1]['text_excerpt']})>1:
        raise ValueError('album_multiple_captions')  # No silently omitted translation.
    if sum(p[2]['declared_bytes'] for p in pairs)>MAX_BYTES:raise ValueError('album_bytes_bound')
    return pairs


def invalidate_group(message,current):
    """Observed edit revokes the frozen group; never re-publish its old members."""
    from trump_telegram_channel import CHANNEL_ID
    if getattr(getattr(message,'peer_id',None),'channel_id',None)!=CHANNEL_ID:return
    from database import get_db_connection,begin_write_transaction
    key=_key(getattr(message,'grouped_id',None))
    with get_db_connection() as c:
        begin_write_transaction(c.cursor())
        value=_load(c,key,lock=True)
        if value:
            value.update(phase='revoked',lease=None,lease_until=None)
            _put(c,key,value,current)


def _reserve_budget(c,at,size):
    # Survives process restart; existing media.capture also enforces the shared
    # in-process budget including non-album posts. Neither limit is increased.
    from trump_truth_media import MAX_PER_MINUTE,MINUTE_BYTES
    key=VERSION+':budget';minute=int(at.timestamp())//60
    _put_if_missing(c,key,{'minute':minute,'count':0,'bytes':0},at)
    value=_load(c,key,lock=True)
    if value['minute']!=minute:value={'minute':minute,'count':0,'bytes':0}
    if value['count']>=MAX_PER_MINUTE or value['bytes']+size>MINUTE_BYTES:return False
    value['count']+=1;value['bytes']+=size;_put(c,key,value,at)
    return True


def _put_if_missing(c,key,value,at):
    c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO NOTHING',
        (key,wire(value),at.isoformat()))


async def collect_album(client,entity,seed,current):
    """Return (one representative+ref, reason, maxmember). No partial output.

    Supported coverage is contiguous 2..10 member photo/MP4 groups, two stable
    bounded observations >=60s apart. Telegram has no album-complete marker;
    noncontiguous/large/multi-caption groups stay explicitly unverified.
    """
    from database import get_db_connection,begin_write_transaction
    from trump_truth_posts import instant
    from trump_truth_media import capture,_verify
    if not enabled():return None,'album_disabled',seed.id
    from trump_truth_posts import valid_entity
    if not valid_entity(entity):return None,'album_source_identity',seed.id
    group=getattr(seed,'grouped_id',None);key=_key(group)
    messages=await client.get_messages(entity,ids=list(range(max(1,seed.id-10),min(2147483647,seed.id+10)+1)))
    try:pairs=_source_members(messages,seed,current)
    except ValueError as exc:return None,str(exc),seed.id
    members=[p[1] for p in pairs];ref=fingerprint(members);last=pairs[-1][0].id
    token=uuid.uuid4().hex
    with get_db_connection() as c:
        begin_write_transaction(c.cursor())
        initial=dict(version=VERSION,fingerprint=ref,first_seen=current.isoformat(),phase='settling',
            members=[],lease=None,lease_until=None)
        _put_if_missing(c,key,initial,current)
        value=_load(c,key,lock=True)
        if value.get('phase')=='revoked':return None,'album_revoked',last
        if value.get('fingerprint')!=ref:
            # Observed source revision invalidates a queued/partly acquired group.
            value.update(phase='revoked',lease=None,lease_until=None);_put(c,key,value,current)
            return None,'album_revision_changed',last
        if instant(current)-instant(value['first_seen'])<timedelta(seconds=SETTLE_SECONDS):
            return None,'album_settling',last
        if value.get('lease_until') and instant(value['lease_until'])>instant(current):
            return None,'album_acquisition_owned',last
        value.update(lease=token,lease_until=(instant(current)+timedelta(seconds=90)).isoformat())
        _put(c,key,value,current)
    try:
        acquired={i['relay_message_id']:i for i in value['members']}
        for message,item,candidate in pairs:
            old=acquired.get(message.id)
            if old:
                # Preserve the actual acquisition clock/binding; do not download
                # the first two files again when resuming the third next minute.
                _verify(old['media']['sha256'],old['media']['bytes'])
                continue
            at=_now() if current is None else instant(current)
            with get_db_connection() as c:
                begin_write_transaction(c.cursor())
                owned=_load(c,key,lock=True)
                if owned.get('lease')!=token or owned.get('phase')=='revoked':return None,'album_lease_revoked',last
                if not _reserve_budget(c,at,candidate['declared_bytes']):return None,'album_media_budget_deferred',last
            got=await capture(client,message,item,at)
            if got.get('media',{}).get('status')!='available':return None,'album_media_deferred',last
            acquired[message.id]=got
            with get_db_connection() as c:
                begin_write_transaction(c.cursor())
                owned=_load(c,key,lock=True)
                if owned.get('lease')!=token or owned.get('phase')=='revoked':return None,'album_lease_revoked',last
                owned['members']=[acquired[i] for i in sorted(acquired)]
                _put(c,key,owned,instant(got['observed_at']))
        with get_db_connection() as c:
            begin_write_transaction(c.cursor())
            value=_load(c,key,lock=True)
            if value.get('lease')!=token or value.get('phase')=='revoked':return None,'album_lease_revoked',last
            value.update(phase='ready',lease=None,lease_until=None)
            _put(c,key,value,current)
        representative=next((i for i in value['members'] if i['text_excerpt']),value['members'][0])
        return dict(representative,album_ref=ref),None,last
    finally:
        with get_db_connection() as c:
            begin_write_transaction(c.cursor())
            value=_load(c,key,lock=True)
            if value and value.get('lease')==token:
                value.update(lease=None,lease_until=None);_put(c,key,value,current)


def _manifest(envelope,at,c):
    from trump_truth_posts import valid_item,instant
    from trump_truth_media import _verify
    item=envelope['item'];group=item['telegram_grouped_id']
    value=_load(c,_key(group))
    if (not value or value.get('version')!=VERSION or value.get('phase')!='ready'
        or value.get('fingerprint')!=envelope.get('album_ref')):raise ValueError('album_manifest_unavailable')
    members=value['members']
    if (type(members) is not list or not 2<=len(members)<=10
        or fingerprint(members)!=envelope['album_ref']
        or any(not valid_item(i,at) or i.get('telegram_grouped_id')!=group or
            i.get('media',{}).get('status')!='available' for i in members)):
        raise ValueError('album_manifest_invalid')
    ids=[i['relay_message_id'] for i in members]
    if ids!=list(range(ids[0],ids[0]+len(ids))):raise ValueError('album_manifest_invalid')
    if sum(i['media']['bytes'] for i in members)>MAX_BYTES:raise ValueError('album_bytes_bound')
    if max(instant(i['relay_published_at']) for i in members)-min(instant(i['relay_published_at']) for i in members)>timedelta(seconds=2):
        raise ValueError('album_time_span')
    captions={i['text_excerpt'] for i in members if i['text_excerpt']}
    if len(captions)>1 or item not in members or (captions and item['text_excerpt'] not in captions):
        raise ValueError('album_representative_invalid')
    for member in members:_verify(member['media']['sha256'],member['media']['bytes'])
    return members


def album_key(item):return 'trump-album:v1:1462338131:'+str(item['telegram_grouped_id'])


def ingest_album(cur,item,current):
    """Reserve every old per-message dedupe key in the SAME outbox transaction."""
    from trump_truth_posts import fence,PREFIX,EVENT
    from scanner_engine import enqueue_telegram
    item=copy.deepcopy(item);ref=item.pop('album_ref',None)
    envelope=dict(item=item,fence=fence(cur,item),presentation='hebrew_v1',media_version=VERSION,album_ref=ref)
    # Lock group before any claims; all concurrent readers follow this lock order.
    _load(cur,_key(item['telegram_grouped_id']),lock=True)
    members=_manifest(envelope,current,cur)
    key=album_key(item);payload=wire(envelope)
    if len(payload)>3900:raise ValueError('album_envelope_bound')
    if cur.execute('SELECT id FROM scanner_telegram_outbox WHERE dedupe_key=?',(key,)).fetchone():return False
    keys=[PREFIX+i['truth_post_id'] for i in members]
    for member_key in keys:
        if cur.execute('SELECT id FROM scanner_telegram_outbox WHERE dedupe_key=?',(member_key,)).fetchone():
            return False  # Includes sent, unknown, old pending: never take over.
    if not enqueue_telegram(cur,key,EVENT,payload,published_at=item['relay_published_at']):return False
    cur.execute("UPDATE scanner_telegram_outbox SET status=? WHERE dedupe_key=? AND status='pending'",(PENDING,key))
    for member,member_key in zip(members,keys):
        if not enqueue_telegram(cur,member_key,EVENT,VERSION+':member:'+ref,published_at=member['relay_published_at']):
            raise ValueError('album_member_claim_collision')  # Roll back whole batch.
        cur.execute("UPDATE scanner_telegram_outbox SET status=? WHERE dedupe_key=? AND status='pending'",(CLAIMED,member_key))
    return True


def checked_manifest(row,envelope,at,conn=None):
    from database import get_db_connection
    from trump_truth_posts import PREFIX,EVENT
    if (envelope.get('media_version')!=VERSION or row['event_type']!=EVENT
        or row['dedupe_key']!=album_key(envelope['item'])):raise ValueError('album_envelope_invalid')
    with nullcontext(conn) if conn is not None else get_db_connection() as c:
        members=_manifest(envelope,at,c)
        for item in members:
            claim=c.execute('SELECT status,message,event_type FROM scanner_telegram_outbox WHERE dedupe_key=?',
                (PREFIX+item['truth_post_id'],)).fetchone()
            if (not claim or claim['status']!=CLAIMED or claim['event_type']!=EVENT or
                claim['message']!=VERSION+':member:'+envelope['album_ref']):raise ValueError('album_claim_lost')
    return members
