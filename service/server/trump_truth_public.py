"""Bounded READ ONLY archive of already-sent Hebrew relay notices.

This is not dispatch eligibility: later flags/cutovers do not erase published
history. No inference, ingestion, model, provider or Telegram call is made here.
The source is a pinned relay, not verification of primary authorship or content.
"""
import json
import re
from datetime import datetime, timedelta, timezone

VERSION = 1
MAX_LIMIT = 20
SCAN_LIMIT = 61
HISTORY_DAYS = 7
MAX_RESPONSE_BYTES = 262144
POST_ID = re.compile(r'(?:[1-9][0-9]{15,19}|tg:1462338131:[1-9][0-9]{0,9})', re.ASCII)
TELEGRAM_KIND = 'trump_telegram_channel_v1'


def _json(raw, bound):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > bound:
        raise ValueError('public_archive_invalid')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result: raise ValueError('public_archive_invalid')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('public_archive_invalid')))


def historic_envelope(row, at):
    """Validate immutable retained source/fences, never today's send switches."""
    import trump_truth_posts as t
    try:
        at = t.instant(at)
        if row['status'] != 'sent' or row['event_type'] != t.EVENT:
            return None
        value = _json(row['message'], 16384)
        if (type(value) is not dict or not {'item','fence','presentation'} <= set(value)
            or set(value)-{'item','fence','presentation','media_version'} or value['presentation'] not in ('hebrew_v1','bilingual_v1')):
            return None  # Previous original-language envelopes never enter this archive.
        item, fence = value['item'], value['fence']
        if type(item) is not dict or type(fence) is not dict:
            return None
        post = item['truth_post_id']
        if (type(post) is not str or not POST_ID.fullmatch(post)
            or row['dedupe_key'] != t.PREFIX+post):
            return None
        if item.get('source_kind') == TELEGRAM_KIND:
            if value['presentation'] != 'hebrew_v1' or not t.valid_item(item, at, active=False):
                return None
        elif (not re.fullmatch(r'[1-9][0-9]{15,19}', post, re.ASCII)
            or item['source_kind'] != t.KIND or item['provider'] != 'telegram_channels'
            or item['relay_channel'] != t.CHANNEL or type(item['relay_channel_id']) is not int
            or item['relay_channel_id'] != t.CHANNEL_ID
            or type(item['relay_message_id']) is not int or item['relay_message_id'] <= 0
            or item['truth_url'] != 'https://truthsocial.com/@realDonaldTrump/'+post
            or item['source_verification'] != 'relay_only' or item['original_published_at'] is not None
            or type(item['has_media']) is not bool or type(item['is_repost']) is not bool
            or type(item['text_excerpt']) is not str or t.clean_excerpt(item['text_excerpt']) != item['text_excerpt']):
            return None
        activation, published, observed, sent, created = [t.instant(v) for v in
            (item['activation'], item['relay_published_at'], item['observed_at'], row['sent_at'], row['created_at'])]
        if not activation <= published <= observed <= sent <= at or not observed <= created <= sent:
            return None
        if 'media' in item or 'media_version' in value:
            from trump_truth_media import valid_descriptor, VERSION as media_version
            if not item['has_media'] or not valid_descriptor(item, at): return None
            if 'media_version' in value and (value['media_version'] != media_version or item['media']['status'] != 'available'):
                return None
            if item['media']['status'] == 'available' and ('media_version' not in value or
                t.instant(item['media']['captured_at']) > sent): return None
        if (set(fence) != {'mode','epoch','not_before','environment_not_before'}
            or fence['mode'] not in ('phase1','canonical') or type(fence['epoch']) is not int or fence['epoch'] < 0):
            return None
        for key in ('not_before','environment_not_before'):
            if type(fence[key]) is not str or (fence[key] and t.instant(fence[key]) > published):
                return None
        return value
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return None


def publication_proven(row, envelope, conn=None, at=None):
    """New bilingual publication needs every new staged ACK, not old sent alone.

    Structural validation is separate to keep retained source checks pure and
    avoid a receipt -> source -> receipt recursion. Caller first validates the
    historic envelope; no current dispatch switch or generation is consulted.
    """
    if envelope.get('presentation') == 'hebrew_v1': return True
    if envelope.get('presentation') != 'bilingual_v1': return False
    try:
        from trump_truth_bilingual import published_receipt
        return published_receipt(row, envelope, conn=conn, at=at) is True
    except (ImportError, ValueError, TypeError, KeyError, OSError, RecursionError):
        return False


def _published_cache_allowed(row, envelope, raw):
    """New channel publications are Hebrew-only; old archive semantics stay frozen."""
    if envelope['item']['source_kind'] != TELEGRAM_KIND:
        return True
    import trump_truth_translation as h
    from jsonschema.exceptions import ValidationError
    try:
        cache = h.checked_cache(row, envelope, _json(raw, 8192))
        if h.source_text(envelope['item']):
            return cache['status'] == 'translated'
        return cache['status'] == 'media_only' and envelope['item']['has_media'] is True
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError, ValidationError):
        return False


def _projection(row, envelope, cache, at, conn):
    import trump_truth_posts as t
    import trump_truth_translation as h
    status, text = 'not_retained', None
    try:
        checked = h.checked_cache(row, envelope, _json(cache, 8192))
        if checked['status'] != 'working':
            status, text = checked['status'], checked['text_he'] or None
            # Same whole-wire constraint as dispatch: never advertise an approved
            # translation that current Telegram presentation would have to clip.
            from telegram_presentation import telegram_text, utf16_length
            if (envelope['presentation']=='hebrew_v1' and
                utf16_length(telegram_text(t.render(envelope['item'], checked), limit=16384)) > 4096):
                status, text = 'unavailable', None
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        pass
    item = envelope['item']
    media = {'status':'marker_only' if item['has_media'] else 'unavailable', 'kind':None}
    # Optional media module returns only a verified public token, never a source
    # access hash/file reference/private path. No download occurs on GET.
    try:
        from trump_truth_media import public_media
        projected = public_media(row, envelope, at, conn=conn)
        if (type(projected) is dict and projected.get('version') == 'trump_truth_media_v1'
            and projected.get('status') in ('unavailable','marker_only','disabled','none')):
            media = {'status':'unavailable' if projected['status']=='none' else projected['status'],'kind':None}
        elif (type(projected) is dict and projected.get('version') == 'trump_truth_media_v1'
            and projected.get('status') == 'available' and projected.get('kind') in ('photo','video')
            and type(projected.get('asset_token')) is str and re.fullmatch('[0-9a-f]{64}',projected['asset_token'])
            and projected.get('mime_type') == {'photo':'image/jpeg','video':'video/mp4'}[projected['kind']]
            and type(projected.get('bytes')) is int and 0 < projected['bytes'] <= {'photo':8,'video':24}[projected['kind']]*1024*1024):
            media = {key:projected[key] for key in ('version','status','kind','asset_token','mime_type','bytes')}
    except ImportError:
        pass
    except (ValueError, TypeError, KeyError, OSError):
        media = {'status':'unavailable','kind':None}
    channel_url = (item['truth_url'] if item['source_kind'] == TELEGRAM_KIND else
                   'https://t.me/'+item['relay_channel']+'/'+str(item['relay_message_id']))
    return dict(id='trump-truth:'+item['truth_post_id'], source_kind=item['source_kind'],
        source_verification=item['source_verification'], publication_policy=item['publication_policy'],
        truth_post_id=item['truth_post_id'], truth_url=item['truth_url'],
        relay_url=channel_url,
        source_excerpt=h.source_text(item), translation_status=status, text_he=text,
        relay_published_at=t.instant(item['relay_published_at']).isoformat(),
        observed_at=t.instant(item['observed_at']).isoformat(), original_published_at=None,
        sent_at=t.instant(row['sent_at']).isoformat(), is_repost=item['is_repost'],
        has_media=item['has_media'], delivery_status='sent', media=media)


def report(conn, *, now=None, limit=MAX_LIMIT, before=None):
    from database import using_postgres
    from trump_truth_posts import EVENT, PREFIX, instant, ORIGINAL_POLICY, original_policy_allows
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT or (before is not None and
        (type(before) is not str or not POST_ID.fullmatch(before))):
        raise ValueError('public_archive_invalid_page')
    if using_postgres():
        if (conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] != 'on'
            or conn.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] != 'repeatable read'):
            raise RuntimeError('read_only_snapshot_required')
    elif conn.execute('PRAGMA query_only').fetchone()[0] != 1:
        raise RuntimeError('read_only_snapshot_required')
    at = instant(now or datetime.now(timezone.utc))
    since = (at-timedelta(days=HISTORY_DAYS)).isoformat()
    anchor = None
    if before:
        found = conn.execute("SELECT id FROM scanner_telegram_outbox WHERE event_type=? AND dedupe_key=? AND status='sent' AND julianday(sent_at)>=julianday(?) AND julianday(sent_at)<=julianday(?) LIMIT 1",
            (EVENT, PREFIX+before, since, at.isoformat())).fetchone()
        if not found: raise ValueError('public_archive_cursor_expired')
        anchor = found['id']
    fields = 'id,dedupe_key,event_type,substr(message,1,16385) AS message,status,created_at,sent_at'
    args = [EVENT, since, at.isoformat()]
    sql = 'SELECT '+fields+" FROM scanner_telegram_outbox WHERE event_type=? AND status='sent' AND julianday(sent_at)>=julianday(?) AND julianday(sent_at)<=julianday(?)"
    if anchor is not None: sql += ' AND id<?'; args.append(anchor)
    rows = [dict(r) for r in conn.execute(sql+' ORDER BY id DESC LIMIT '+str(SCAN_LIMIT), tuple(args)).fetchall()]
    # At most 60 source records and their exact translation keys are inspected.
    bounded = rows[:SCAN_LIMIT-1]
    keys = ['trump_truth_hebrew_v1:'+str(row['id']) for row in bounded]
    caches = {}
    if keys:
        caches = {r['key']:r['value_json'] for r in conn.execute('SELECT key,substr(value_json,1,8193) AS value_json FROM scanner_settings WHERE key IN ('+','.join('?' for _ in keys)+')',tuple(keys)).fetchall()}
    items, excluded, last, exhausted = [], 0, None, True
    for index, row in enumerate(bounded):
        key = row['dedupe_key']
        if type(key) is str and key.startswith(PREFIX) and POST_ID.fullmatch(key[len(PREFIX):]): last=key[len(PREFIX):]
        envelope = historic_envelope(row, at)
        raw_cache = caches.get('trump_truth_hebrew_v1:'+str(row['id']))
        if (envelope is None or not original_policy_allows(envelope['item'])
            or not publication_proven(row, envelope, conn=conn, at=at)
            or not _published_cache_allowed(row, envelope, raw_cache)): excluded += 1; continue
        projected = _projection(row, envelope, raw_cache, at, conn)
        if envelope['item']['source_kind'] == TELEGRAM_KIND and projected['translation_status'] not in ('translated','media_only'):
            excluded += 1; continue  # Never replace a whole Hebrew publication with an English fallback.
        items.append(projected)
        if len(items) == limit:
            exhausted = index == len(rows)-1
            break
    more = not exhausted or len(rows) == SCAN_LIMIT
    result = dict(version=VERSION, generated_at=at.isoformat(), status='READY', items=items,
        next_cursor=last if more else None,
        coverage=dict(status='BOUNDED_RETAINED_ARCHIVE', history_days=HISTORY_DAYS,
            publication_policy=(next(iter({item['publication_policy'] for item in items})) if len({item['publication_policy'] for item in items}) == 1 else
                                'VERSIONED_SOURCE_POLICY' if items else ORIGINAL_POLICY),
            publication_policies=[ORIGINAL_POLICY,'telegram_channel_original_v1'],
            authorship='SOURCE_CHANNEL_NOT_PRIMARY_VERIFICATION' if any(item['source_kind'] == TELEGRAM_KIND for item in items) else 'RELAY_CLAIM_NOT_PRIMARY_VERIFICATION',
            scanned=min(len(bounded),len(items)+excluded), excluded=excluded, scan_limit=SCAN_LIMIT-1,
            history_is_not_live_dispatch=True, original_publication_time='NOT_VERIFIED',
            delivery='STORED_SENT_STATUS_NOT_PHONE_RECEIPT', missing_cache='NOT_RETAINED_NOT_RECONSTRUCTED'))
    if len(json.dumps(result,ensure_ascii=False).encode()) > MAX_RESPONSE_BYTES:
        raise ValueError('public_archive_response_bound')
    return result


def payload(*, now=None, limit=MAX_LIMIT, before=None):
    from database import get_db_connection, using_postgres
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            conn.execute("SET LOCAL statement_timeout='5s'")
            conn.execute("SET LOCAL lock_timeout='2s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout='20s'")
        else:
            conn.execute('PRAGMA query_only=ON'); conn.execute('BEGIN')
        return report(conn, now=now, limit=limit, before=before)
    finally:
        conn.close()


def asset_payload(token, *, now=None):
    """Exact private index -> eligible sent notice -> hash-checked asset bytes."""
    from database import get_db_connection, using_postgres
    from trump_truth_media import public_asset
    if type(token) is not str or not re.fullmatch('[0-9a-f]{64}',token):
        raise ValueError('media_asset_unavailable')
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            conn.execute("SET LOCAL statement_timeout='5s'")
            conn.execute("SET LOCAL lock_timeout='2s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout='20s'")
        else:
            conn.execute('PRAGMA query_only=ON'); conn.execute('BEGIN')
        return public_asset(token, conn, now or datetime.now(timezone.utc))
    finally:
        conn.close()
