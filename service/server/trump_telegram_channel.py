"""Versioned Telegram channel source, not a Truth Social authorship claim.

Legacy envelope field names truth_post_id/truth_url are storage compatibility
slots: the explicit tg namespace and literal Telegram URL never invent a Truth ID.
"""
import os
import re
from datetime import timedelta

CHANNEL = 'real_donaldjtrump'
CHANNEL_ID = 1462338131  # Public identity observed read-only 2026-10-25.
KIND = 'trump_telegram_channel_v1'
POLICY = 'telegram_channel_original_v1'
SELECTOR = 'telegram_channel_v1'
URL_PREFIX = 'https://t.me/real_DonaldJTrump/'
POST_ID = re.compile(r'tg:1462338131:([1-9][0-9]{0,9})', re.ASCII)


def selected():
    return os.getenv('TELEGRAM_TRUMP_SOURCE','truth_relay_v1').strip() == SELECTOR


def is_item(item):
    return type(item) is dict and item.get('source_kind') == KIND


def require_hebrew(text):
    # A token of Hebrew must not disguise an otherwise untranslated English
    # body. Numbers/punctuation are excluded; proper names may remain Latin.
    he=len(re.findall('[\u05d0-\u05ea]',text))
    if not he or he<len(re.findall('[A-Za-z]',text)):
        raise ValueError('translation_not_hebrew')


def original(item):
    from trump_truth_posts import _shared_body
    return (is_item(item) and item.get('publication_policy') == POLICY
            and item.get('is_repost') is False and not _shared_body(item.get('text_excerpt')))


def valid_item(item,current,*,active=True):
    from trump_truth_posts import instant,activation,enabled,clean_excerpt
    from trump_truth_media import valid_descriptor
    try:
        post = POST_ID.fullmatch(item['truth_post_id'])
        return (is_item(item) and (not active or (selected() and enabled()))
            and original(item) and item['provider']=='telegram_channels'
            and item['relay_channel']==CHANNEL and type(item['relay_channel_id']) is int
            and item['relay_channel_id']==CHANNEL_ID and type(item['relay_message_id']) is int
            and 0<item['relay_message_id']<=2147483647
            and post is not None and str(item['relay_message_id'])==post[1]
            and item['truth_url']==URL_PREFIX+post[1]
            and item['source_verification']=='channel_only' and item['original_published_at'] is None
            and (not active or item['activation']==activation())
            and instant(item['activation'])<=instant(item['relay_published_at'])<=instant(item['observed_at'])<=instant(current)
            and (not active or instant(current)-instant(item['relay_published_at'])<=timedelta(hours=24))
            and type(item['text_excerpt']) is str and clean_excerpt(item['text_excerpt'],max_units=2400)==item['text_excerpt']
            and type(item['has_media']) is bool
            and (bool(item['text_excerpt']) or item['has_media'])
            and ('media' not in item or (item['has_media'] and valid_descriptor(item,current))))
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError):
        return False


def extract(message,current):
    from trump_truth_posts import enabled,instant,activation,_shared_body,clean_excerpt
    if not selected() or not enabled():return None,'disabled'
    try:
        if (type(message.id) is not int or not 0<message.id<=2147483647
            or getattr(getattr(message,'peer_id',None),'channel_id',None)!=CHANNEL_ID
            or getattr(message,'action',None)):
            return None,'relay_identity'
        if any(getattr(message,k,None) is not None for k in ('fwd_from','forward','reply_to','reply_to_msg_id')):
            return None,'non_original_or_unverifiable'
        stamp,boundary=instant(message.date),activation()
        if stamp>instant(current):return None,'future_relay_time'
        if stamp<instant(boundary):return None,'outside_activation'
        text=message.message or ''
        if type(text) is not str or len(text)>32768:return None,'relay_format'
        if _shared_body(text) or any(_shared_body(getattr(e,'url','')) for e in (getattr(message,'entities',None) or [])):
            return None,'non_original_or_unverifiable'
        cleaned=clean_excerpt(text,max_units=None)
        # Bounded source excerpt; do not silently clip a long channel post.
        if max(len(text.encode('utf-16-le')),len(cleaned.encode('utf-16-le')))//2>2400:
            return None,'source_text_bound'
        media=bool(getattr(message,'photo',None) or getattr(message,'document',None))
        if not cleaned and not media:return None,'relay_format'
        item=dict(source_kind=KIND,provider='telegram_channels',relay_channel=CHANNEL,
            relay_channel_id=CHANNEL_ID,relay_message_id=message.id,
            truth_post_id='tg:'+str(CHANNEL_ID)+':'+str(message.id),truth_url=URL_PREFIX+str(message.id),
            relay_published_at=stamp.isoformat(),observed_at=instant(current).isoformat(),
            original_published_at=None,source_verification='channel_only',activation=boundary,
            text_excerpt=cleaned,has_media=media,is_repost=False,publication_policy=POLICY)
        from trump_truth_media import enabled as media_enabled,describe
        if media_enabled() and media:item['media']=describe(message,item)
        return item,None
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError):
        return None,'configuration_or_format_unverifiable'
