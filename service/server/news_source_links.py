"""News source validation and Telegram presentation helpers.

No URL is fetched here. Source metadata remains in the news event, while
Telegram messages omit ordinary source links and retain required license text.
"""
import ipaddress
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

URL = re.compile(r'https?://[^\s<>]+', re.I)
SOURCE_LINE = re.compile(r'^\s*(?:מקור|Source)\s*:\s*(https?://\S+)\s*$', re.I)
SOURCE_LABEL = re.compile(r'^\s*(?:מקור|Source)\s*:', re.I)
RELAY_HOSTS = ('t.me', 'telegram.me', 'telegram.org', 'twitter.com', 'x.com')
SECRET_KEYS = {'token', 'apikey', 'api_key', 'key', 'access_token', 'password',
               'secret', 'signature', 'auth', 'authorization'}


def safe_source_url(value):
    """A bounded public HTTPS article/filing link, or empty (fail closed)."""
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        return ''
    decoded = unquote(value)
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 or
           char in '<>"`\\' or '\u200b' <= char <= '\u200f' or
           '\u202a' <= char <= '\u202e' or '\u2066' <= char <= '\u2069' or
           char in '\u061c\ufeff' for char in decoded):
        return ''
    try:
        p = urlsplit(value)
        host = p.hostname or ''
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
            return ''
        if (not host.isascii() or len(host) > 253 or '.' not in host or
                not re.fullmatch(r'(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})', host.rsplit('.', 1)[-1]) or
                any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part)
                    for part in host.split('.')) or
                host.endswith(('.local', '.localhost', '.internal', '.invalid', '.test')) or
                any(host == relay or host.endswith('.' + relay) for relay in RELAY_HOSTS)):
            return ''
        try:
            ipaddress.ip_address(host)
            return ''
        except ValueError:
            pass
        query = parse_qsl(p.query, keep_blank_values=True)
        if any(key.casefold() in SECRET_KEYS for key, _ in query):
            return ''
        query = [(key, value) for key, value in query
                 if not key.casefold().startswith('utm_') and key.casefold() not in {'fbclid', 'gclid'}]
        if p.path in ('', '/') and not query:
            return ''  # A publisher homepage is not the cited article.
        normalized = urlunsplit(('https', host, p.path, urlencode(query), ''))
        return normalized if len(normalized) <= 512 else ''
    except (TypeError, ValueError, UnicodeError):
        return ''


def source_url(sources):
    candidates = sorted(enumerate(sources), key=lambda pair:
                        (pair[1].get('source_type') != 'official/regulatory', pair[0]))
    for _, source in candidates:
        if source.get('rights') != 'approved' or source.get('source_type') == 'social/relay':
            continue
        link = safe_source_url(source.get('url'))
        if link:
            return link
    return ''


def clean_draft(value):
    # Labels/URLs from model text are not authoritative attribution. A trusted
    # footer is composed separately from retained approved source metadata.
    return '\n'.join(URL.sub('', line).strip() for line in value.splitlines()
                     if not SOURCE_LABEL.match(line)).strip()


def append_source(body, sources, *, required_footer=''):
    tails = [required_footer] if required_footer else []
    suffix = '\n\n' + '\n\n'.join(tails) if tails else ''
    # Leave room for the existing community CTA (bounded to 512 URL characters)
    # and its Hebrew label; required license credits remain in the footer.
    from telegram_presentation import telegram_text, utf16_length
    budget = 3500 - utf16_length(telegram_text(suffix, limit=100_000))
    if budget < 1:
        raise ValueError('news_required_footer_too_long')
    clipped = telegram_text(body, limit=budget).rstrip()
    return clipped + suffix
