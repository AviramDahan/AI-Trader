"""Read-only Mini App authorization. Launch hints are never authority.

Validate the existing Main Mini App bot's signed initData, then check membership
of the configured PRIVATE logs group with its existing Admin bot. No send API,
user details, credentials or initData are logged or persisted. Fail closed.
"""
import hashlib
import hmac
import json
import os
import re
import threading
import time
from urllib.parse import parse_qsl

import requests
from fastapi import HTTPException

_lock = threading.Lock()
_members = {}
MAX_AUTH_AGE = 3600


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate_field')
        out[key] = value
    return out


def verified_user(raw, bot_token, now=None):
    """Official Telegram HMAC contract, bounded parsing and authentication age."""
    try:
        if not isinstance(raw, str) or not 0 < len(raw) <= 8192 or not bot_token:
            raise ValueError()
        fields = _unique(parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                                   max_num_fields=20, encoding='utf-8', errors='strict'))
        received = fields.pop('hash')
        if not re.fullmatch('[0-9a-f]{64}', received):
            raise ValueError()
        data = '\n'.join(f'{key}={fields[key]}' for key in sorted(fields))
        secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received, expected):
            raise ValueError()
        stamp = fields['auth_date']
        if not re.fullmatch('[0-9]{1,12}', stamp):
            raise ValueError()
        age = (time.time() if now is None else now) - int(stamp)
        if not -30 <= age <= MAX_AUTH_AGE:
            raise ValueError()
        user = json.loads(fields['user'], object_pairs_hook=_unique)
        uid = user.get('id') if isinstance(user, dict) else None
        if type(uid) is not int or not 0 < uid < 2**53:
            raise ValueError()
        return uid
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise HTTPException(401, 'telegram_authentication_required') from None


def require_logs_member(raw):
    bot = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    # Existing private alerts use the main bot when no separate Admin bot exists.
    admin_bot = os.getenv('TELEGRAM_ADMIN_BOT_TOKEN', '').strip() or bot
    chat = os.getenv('TELEGRAM_ADMIN_CHAT_ID', '').strip()
    # Never use the public community as a private authorization destination.
    if (not bot or not admin_bot or not re.fullmatch('-[0-9]{1,20}', chat)
            or chat == os.getenv('TELEGRAM_CHAT_ID', '').strip()):
        raise HTTPException(503, 'private_logs_access_not_configured')
    uid = verified_user(raw, bot)
    # Bot rotations/group changes invalidate the bounded, in-memory cache.
    key = (hashlib.sha256((bot + '\0' + admin_bot + '\0' + chat).encode()).digest(), uid)
    now = time.monotonic()
    with _lock:
        entry = _members.get(key)
        if entry and now < entry[0]:
            if not entry[1]:
                raise HTTPException(403, 'private_logs_membership_required')
            return
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get('https://api.telegram.org/bot' + admin_bot + '/getChatMember',
                             params={'chat_id': chat, 'user_id': uid}, timeout=(2, 3),
                             allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise ValueError()
                content = bytearray()
                for part in response.iter_content(4096):
                    content.extend(part)
                    if len(content) > 16384 or time.monotonic() - now > 5:
                        raise ValueError()
                data = json.loads(content)
        member = data.get('result', {}) if isinstance(data, dict) else {}
        if not data.get('ok') or not isinstance(member, dict):
            raise ValueError()
        # Binding to the requested ID guards malformed/misrouted provider replies.
        if member.get('user', {}).get('id') != uid:
            raise ValueError()
        allowed = member.get('status') in {'creator', 'administrator', 'member'} or (
            member.get('status') == 'restricted' and member.get('is_member') is True)
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        # Do not turn a network error into an authorization success or expose URLs.
        raise HTTPException(503, 'private_logs_membership_unavailable') from None
    with _lock:
        if len(_members) >= 512:
            _members.clear()
        _members[key] = (time.monotonic() + (30 if allowed else 5), allowed)
    if not allowed:
        raise HTTPException(403, 'private_logs_membership_required')
