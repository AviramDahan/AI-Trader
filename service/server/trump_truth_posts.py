"""Opt-in Truth relay notices; optional isolated Hebrew, never trading input.

Only a pinned public broadcast and an exact author/header + footer link qualify.
That verifies the relay's claim, NOT primary authorship/content or full coverage.
"""
import json
import os
import re
import unicodedata
from datetime import datetime, timezone

CHANNEL = 'realdonaldtrump_truth'
CHANNEL_ID = 2310477090  # Public entity observed 2026-10-22; username alone is not identity.
KIND = 'trump_truth_relay_v1'
EVENT = 'trump_truth_post'
PREFIX = 'trump-truth:v1:'
HEADER = 'New Post by realDonaldTrump on Truth Social'
LABEL = 'Truth Social Post Link'
LINK = re.compile(r'https://truthsocial\.com/(?:@realDonaldTrump/|users/realDonaldTrump/statuses/)([1-9][0-9]{15,19})', re.ASCII)
ORIGINAL_POLICY = 'original_relay_v1'
POLICY_REJECTION = 'non_original_or_unverifiable'


def _classification_text(value):
    # Classification only: never rewrite the retained/displayed source. Inspect
    # the WHOLE bounded relay body before excerpt truncation or URL replacement.
    normalized = unicodedata.normalize('NFKC', value)
    return ''.join(ch for ch in normalized if unicodedata.category(ch) not in ('Cf', 'Cc')
                   or ch in '\n\r\t').replace('\ufe0e', '').replace('\ufe0f', '')


def _shared_body(value):
    if type(value) is not str or len(value) > 32768:
        return True
    text = _classification_text(value)
    return bool(re.search(
        r'(?im)(?:^\W*(?:RT(?=[:@\s])|RE[\s-]?TRUTH\b|RE[\s-]?POST(?:ED)?\b|'
        r'RE[\s-]?TWEET(?:ED)?\b|FORWARDED\s+FROM\b|QUOTE(?:D)?(?:\s+POST)?(?=\s*[:@]))|'
        r'(?<!\w)(?:RT|RE[\s-]?TRUTH|RE[\s-]?POST(?:ED)?|RE[\s-]?TWEET(?:ED)?|'
        r'FORWARDED\s+FROM|QUOTE(?:D)?(?:\s+POST)?)\s*[:@]|'
        r'>>\s*QUOTE\b|\[\s*(?:RETRUTH|REPOST|QUOTE)\s*\])', text)
        or re.search(r'https?://(?:www\.)?truthsocial\.com/(?:@[^/\s]+/(?:posts/)?|'
                     r'users/[^/\s]+/statuses/|statuses/)[0-9]+', text, re.I))


def original_policy_allows(item):
    """Conservative relay-marker policy, NOT primary authorship verification.

    No old queued record is upgraded by absence of RT. Only new pinned-source
    extraction assigns this policy after checking raw text AND entity targets.
    """
    from trump_telegram_channel import is_item,original
    if is_item(item):return original(item)
    return (type(item) is dict and item.get('publication_policy') == ORIGINAL_POLICY
            and item.get('is_repost') is False and not _shared_body(item.get('text_excerpt')))


def enabled():
    mode=os.getenv('TELEGRAM_TRUMP_SOURCE','truth_relay_v1').strip()
    if mode=='telegram_channel_v1':
        # Keep the LEGACY source OFF in the release environment: an older
        # rollback binary cannot accidentally resume the replaced relay.
        return (os.getenv('TELEGRAM_TRUMP_CHANNEL_ENABLED','false').strip().lower()=='true'
            and os.getenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false').strip().lower()=='false'
            and os.getenv('TELEGRAM_TRUMP_TRUTH_HEBREW_ENABLED','false').strip().lower()=='true')
    return mode=='truth_relay_v1' and os.getenv('TELEGRAM_TRUMP_TRUTH_ENABLED','false').strip().lower()=='true'


def source_channel():
    from trump_telegram_channel import selected,CHANNEL as new
    return new if selected() else CHANNEL


def source_channel_id():
    from trump_telegram_channel import selected,CHANNEL_ID as new
    return new if selected() else CHANNEL_ID


def instant(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not parsed.tzinfo or parsed.utcoffset() is None:
        raise ValueError('trump_truth_aware_time_required')
    return parsed.astimezone(timezone.utc)


def activation():
    # Explicit deployment boundary, advanced on every reactivation. No timestamp
    # synthesized at import/startup (which would replay or discard work on restart).
    return instant(os.environ['TELEGRAM_TRUMP_TRUTH_NOT_BEFORE']).isoformat()


def valid_entity(entity):
    return (getattr(entity, 'id', None) == source_channel_id() and getattr(entity, 'broadcast', False)
            and (getattr(entity, 'username', '') or '').lower() == source_channel())


def clean_excerpt(value,*,max_units=1600):
    # Text only, no source-supplied bidi controls or unsafe links in the excerpt.
    value = re.sub('[\x00-\x08\x0b-\x1f\x7f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', value)
    value = re.sub(r'https?://\S+', '[קישור בגוף הפוסט — לצפייה במקור]', value)
    if max_units is None:return value.strip()
    return value.encode('utf-16-le')[:max_units*2].decode('utf-16-le', errors='ignore').strip()


def extract(message, current):
    """Return item and fixed rejection code. Never guess URL from quoted RT text."""
    from trump_telegram_channel import selected,extract as new_extract
    if selected():return new_extract(message,current)
    if not enabled():
        return None, 'disabled'
    try:
        boundary = activation()
        stamp = instant(message.date)
        if stamp > instant(current):
            return None, 'future_relay_time'
        if stamp < instant(boundary):
            return None, 'outside_activation'
        if (getattr(message, 'action', None) or type(message.id) is not int or message.id <= 0
                or getattr(getattr(message, 'peer_id', None), 'channel_id', None) != CHANNEL_ID):
            return None, 'relay_identity'
        if any(getattr(message, field, None) is not None for field in
               ('fwd_from', 'forward', 'reply_to', 'reply_to_msg_id')):
            return None, POLICY_REJECTION
        text = message.message
        if not isinstance(text, str) or len(text) > 32768:
            return None, 'relay_format'
        lines = text.splitlines()
        if not lines or lines[0] != HEADER:
            return None, 'other_author_or_header'
        encoded = text.encode('utf-16-le')
        footers = []
        for entity in getattr(message, 'entities', None) or []:
            start, length = getattr(entity, 'offset', None), getattr(entity, 'length', None)
            if type(start) is not int or type(length) is not int or min(start, length) < 0:
                continue
            end = start + length
            if end * 2 > len(encoded):
                continue
            label = encoded[start*2:end*2].decode('utf-16-le', errors='strict')
            if label != LABEL:
                continue
            url = getattr(entity, 'url', '')
            match = LINK.fullmatch(url) if isinstance(url, str) else None
            # Exactly one FINAL labelled footer. An embedded or conflicting
            # footer/quoted link must not substitute the new post identity.
            before = encoded[:start*2].decode('utf-16-le')
            if not match or text[len(before)+len(LABEL):].strip() or not before.endswith('\n'):
                return None, 'primary_link_unverifiable'
            footers.append((match[1], before))
        if len(footers) != 1:
            return None, 'primary_link_unverifiable'
        post_id, before = footers[0]
        body = before[len(HEADER):].strip()
        if _shared_body(body):
            return None, POLICY_REJECTION
        body_end = len(before.encode('utf-16-le')) // 2
        for entity in getattr(message, 'entities', None) or []:
            start, length = getattr(entity, 'offset', None), getattr(entity, 'length', None)
            if type(start) is int and type(length) is int and start < body_end:
                target = getattr(entity, 'url', None)
                if isinstance(target, str) and _shared_body(target):
                    return None, POLICY_REJECTION  # Hidden TextUrl targets count too.
        item = dict(source_kind=KIND, provider='telegram_channels', relay_channel=CHANNEL,
            relay_channel_id=CHANNEL_ID, relay_message_id=message.id, truth_post_id=post_id,
            truth_url='https://truthsocial.com/@realDonaldTrump/'+post_id,
            relay_published_at=stamp.isoformat(), observed_at=instant(current).isoformat(),
            original_published_at=None, source_verification='relay_only',
            activation=boundary, text_excerpt=clean_excerpt(body),
            has_media=bool(getattr(message, 'photo', None) or getattr(message, 'document', None)
                           or 'This post contains the following media:' in body),
            is_repost=False, publication_policy=ORIGINAL_POLICY)
        from trump_truth_media import enabled as media_enabled, describe
        if media_enabled() and item['has_media']:
            item['media'] = describe(message, item)
        return item, None
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        return None, 'configuration_or_format_unverifiable'


def valid_item(item, current, *, active=True):
    from trump_telegram_channel import is_item,valid_item as new_valid,selected
    if is_item(item):return new_valid(item,current,active=active)
    if active and selected():return False
    try:
        match = LINK.fullmatch(item['truth_url'])
        from trump_truth_media import valid_descriptor
        return ((not active or enabled()) and item['source_kind'] == KIND and item['provider'] == 'telegram_channels'
            and (not active or original_policy_allows(item))
            and item['relay_channel'] == CHANNEL and type(item['relay_channel_id']) is int
            and item['relay_channel_id'] == CHANNEL_ID
            and type(item['relay_message_id']) is int and item['relay_message_id'] > 0
            and match is not None and match[1] == item['truth_post_id']
            and item['truth_url'] == 'https://truthsocial.com/@realDonaldTrump/'+match[1]
            and (not active or item['activation'] == activation())
            and instant(item['activation']) <= instant(item['relay_published_at']) <= instant(item['observed_at']) <= instant(current)
            and item['original_published_at'] is None and item['source_verification'] == 'relay_only'
            and isinstance(item['text_excerpt'], str) and clean_excerpt(item['text_excerpt']) == item['text_excerpt']
            and type(item['has_media']) is bool and type(item['is_repost']) is bool
            and ('media' not in item or (item['has_media'] and valid_descriptor(item,current))))
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        return False


def fence(cursor, item):
    from news_events.control import state
    control = state(cursor)
    environment_boundary = os.getenv('TELEGRAM_NEWS_NOT_BEFORE', '').strip()
    for boundary in (control.get('not_before'), environment_boundary):
        if boundary and instant(item['relay_published_at']) < instant(boundary):
            raise ValueError('trump_truth_cutover_fenced')
    return dict(mode=control['mode'], epoch=control['epoch'], not_before=control.get('not_before', ''),
                environment_not_before=environment_boundary)


def ingest(items, at=None):
    """Atomic outbox insert before reader checkpoint; repeated live/catch-up is safe."""
    from database import get_db_connection, begin_write_transaction
    from scanner_engine import enqueue_telegram
    current = at or datetime.now(timezone.utc)
    result = dict(received=len(items), inserted=0, sources=0, linked=0, duplicates=0,
                  rejected_invalid=0, rejected_date=0)
    if not enabled() or not items:
        result['rejected_invalid'] = len(items)
        return result
    from trump_truth_bilingual import requested as bilingual_requested,enabled as bilingual_enabled,VERSION as bilingual_version
    from trump_telegram_channel import selected
    if not selected() and bilingual_requested() and not bilingual_enabled():
        result['rejected_invalid']=len(items)
        return result  # Never silently fall back to a one-language contract.
    conn = get_db_connection()
    try:
        cur = conn.cursor(); begin_write_transaction(cur)
        for item in items:
            if not valid_item(item, current):
                result['rejected_invalid'] += 1
                continue
            envelope = dict(item=item, fence=fence(cur, item))
            from trump_truth_translation import enabled as hebrew_enabled
            if hebrew_enabled():envelope['presentation']='hebrew_v1'
            if not selected() and bilingual_enabled():envelope['presentation']=bilingual_version
            from trump_truth_media import enabled as media_enabled, VERSION as media_version
            if media_enabled() and item.get('media',{}).get('status')=='available':
                envelope['media_version']=media_version
            payload = json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))
            if len(payload) > 3900:
                if selected():
                    result['rejected_invalid']+=1
                    continue  # One bounded new-channel item cannot stall catch-up.
                raise ValueError('trump_truth_payload_bound')
            added = enqueue_telegram(cur, PREFIX+item['truth_post_id'], EVENT, payload,
                                     published_at=item['relay_published_at'])
            if added:
                # Old binaries do not recognize these queue states and cannot
                # accidentally dispatch raw envelopes to a trading fallback.
                status=('trump_bilingual_pending' if envelope.get('presentation')==bilingual_version else
                    'trump_media_pending' if envelope.get('media_version')==media_version else
                    'trump_hebrew_pending' if envelope.get('presentation')=='hebrew_v1' else 'trump_pending')
                cur.execute("UPDATE scanner_telegram_outbox SET status=? WHERE dedupe_key=? AND event_type=? AND status='pending'",
                            (status,PREFIX+item['truth_post_id'], EVENT))
            result['inserted'] += int(added)
            result['sources'] += int(added)
            result['duplicates'] += int(not added)
        conn.commit()
    finally:
        conn.close()
    return result


def render(item,hebrew=None,*,media_attached=False):
    from trump_telegram_channel import is_item
    if is_item(item):
        if not hebrew or hebrew['status'] not in ('translated','media_only'):return None
        body=(hebrew['text_he'] if hebrew['status']=='translated' else
              'פוסט מדיה ללא טקסט. אין תמלול או תיאור מומצא של המדיה.')
        return ('📣 עדכון המיוחס לטראמפ\n\n'+body+
            '\n\nתרגום AI; התוכן והשיוך לחשבון רשמי לא אומתו.\nזמן הדיווח: '+
            instant(item['relay_published_at']).strftime('%d.%m.%Y %H:%M UTC'))
    title = '📣 טראמפ · פוסט ב־Truth Social'
    if item['is_repost']:
        title += ' · שיתוף מחדש'
    parts = [title]
    from trump_truth_translation import source_text
    excerpt=source_text(item)
    if hebrew and hebrew['status']=='translated':
        parts += ['תרגום AI לעברית של קטע הדיווח (לא אימות עובדות):\n'+hebrew['text_he']]
    elif hebrew and hebrew['status']=='unavailable':
        parts += ['התרגום לעברית אינו זמין כרגע. לצפייה בתוכן יש לפתוח את הפוסט המקורי בקישור.']
    elif (hebrew and hebrew['status']=='link_only') or (not excerpt and item['is_repost'] and not item['has_media']):
        parts += ['שיתוף מחדש ללא גוף הפוסט בדיווח הממסר. התוכן זמין בקישור לפוסט המקורי.']
    elif (hebrew and hebrew['status']=='media_only') or not excerpt:
        parts += ['פוסט ללא קטע טקסט לתרגום. אין תמלול או תיאור AI של המדיה.']
    else:
        parts += ['קטע מהדיווח (שפת המקור):\n'+excerpt]
    if item['has_media']:
        parts += [('מצורפת מדיה מערוץ המעקב; לא בוצע אימות מול המקור.' if media_attached else
                   'קובץ המדיה אינו מצורף להודעה זו; לצפייה בפוסט המקורי.' if item.get('media',{}).get('status')=='available' else
                   'תמונה/סרטון: לצפייה בפוסט המקורי. המדיה לא הורדה.')]
    parts += ['דיווח מערוץ מעקב; התוכן לא אומת מול החשבון המקורי.\nזמן הפרסום המקורי: לא אומת.\nדווח בערוץ: '+instant(item['relay_published_at']).strftime('%d.%m.%Y %H:%M UTC'),
              'לפוסט המלא ב־Truth Social:\n'+item['truth_url']+'\nערוץ המעקב:\nhttps://t.me/'+CHANNEL+'/'+str(item['relay_message_id'])]
    return '\n\n'.join(parts)


def checked_envelope(row,at=None):
    """Source identity/fences only; never inference or presentation-cache trust."""
    from database import get_db_connection
    from telegram_topics import thread_id_for_event
    if not enabled() or thread_id_for_event(EVENT) is None:
        return None
    try:
        envelope = json.loads(row['message']); item = envelope['item']
        from trump_telegram_channel import is_item
        new=is_item(item)
        from trump_truth_bilingual import requested as bilingual_requested,enabled as bilingual_enabled,VERSION as bilingual_version
        if 'presentation' in envelope and envelope['presentation'] not in ('hebrew_v1',bilingual_version):return None
        if new and envelope.get('presentation')!='hebrew_v1':return None
        if not new and envelope.get('presentation')==bilingual_version:
            if not bilingual_enabled():return None
        elif not new and bilingual_requested():return None  # No old queued one-language fallback.
        if 'media_version' in envelope:
            from trump_truth_media import VERSION as media_version,enabled as media_enabled
            if envelope['media_version']!=media_version or not media_enabled():return None
        if row['event_type'] != EVENT or row['dedupe_key'] != PREFIX+item['truth_post_id']:
            return None
        if not valid_item(item, at or datetime.now(timezone.utc)):
            return None
        with get_db_connection() as conn:
            if envelope['fence'] != fence(conn.cursor(), item):
                return None
        return envelope
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        return None


def checked_archive(row,at=None):
    """Use the one pure retained-publication validator; NOT send authority."""
    from trump_truth_public import historic_envelope
    return historic_envelope(row,at or datetime.now(timezone.utc))


def delivery_message(row,at=None,*,media_attached=False):
    """No inference on the shared Telegram/trading-alert send path."""
    envelope=checked_envelope(row,at)
    if envelope is None:return None
    if envelope.get('presentation')=='bilingual_v1':return None  # Only the staged bilingual dispatcher may publish it.
    if str(row.get('status','')).startswith('trump_hebrew_') and envelope.get('presentation')!='hebrew_v1':return None
    from trump_truth_translation import enabled as hebrew_enabled,presentation
    hebrew=None
    if envelope.get('presentation')=='hebrew_v1':
        hebrew=presentation(row,envelope,at)
        if hebrew is None:return None
    elif hebrew_enabled():return None  # Never replay/translate old queued posts.
    message=render(envelope['item'],hebrew,media_attached=media_attached)
    if message is None:return None
    from telegram_presentation import telegram_text,utf16_length
    # Measure the ENTIRE final bidi wire, not the shorter pre-format text. The
    # shared sender retains its behavior, but must never clip this translation.
    if utf16_length(telegram_text(message,limit=16384))>4096:
        message=render(envelope['item'],{'status':'unavailable','text_he':''},media_attached=media_attached)
        if message is None:return None
    return message if utf16_length(telegram_text(message,limit=16384))<=4096 else None
