"""Read only explicitly configured public broadcast channels; never send or join."""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / '.runtime/telegram-reader.session'


def channel_names():
    names = list(dict.fromkeys(x.strip().lstrip('@').lower() for x in
                              os.getenv('TELEGRAM_NEWS_SOURCE_CHANNELS', '').split(',') if x.strip()))
    if not names or len(names) > 5 or any(not re.fullmatch(r'[a-z][a-z0-9_]{4,31}', x) for x in names):
        raise ValueError('Configure 1-5 public broadcast usernames')
    return names


def message_item(message, username, current):
    text = (getattr(message, 'message', None) or '').strip()
    published = getattr(message, 'date', None)
    if not text or not published or getattr(message, 'action', None):
        return None
    published = published.astimezone(timezone.utc)
    if published > current or published < current - timedelta(hours=6):
        return None
    # Do not mistake a Telegram relay for Reuters/Bloomberg/the primary source.
    return dict(provider='telegram_channels', publisher='Telegram @' + username,
                title=text.splitlines()[0][:500], source_excerpt=text[:2500],
                url=f'https://t.me/{username}/{message.id}', published_at=published.isoformat(),
                tickers=[], scope='market', source_kind='telegram_post', headline_only=True,
                news_category='world')


async def collect(client, state, current, names):
    checkpoints = dict(json.loads(state.get('checkpoint_json') or '{}').get('channels') or {})
    output, errors = [], []
    for name in names:
        prior = dict(checkpoints.get(name) or {})
        if float(prior.get('retry_after', 0)) > current.timestamp():
            errors.append(name + ':backoff'); continue
        try:
            entity = await client.get_entity(name)
            if not getattr(entity, 'broadcast', False) or not getattr(entity, 'username', None):
                raise ValueError('Not a public broadcast channel')
            cursor = int(prior.get('last_id', 0))
            # New source: at most 30 recent posts, with one-hour bootstrap window.
            # Existing cursor: oldest unread first so a busy source cannot lose gaps.
            messages = await client.get_messages(entity, limit=50 if cursor else 30,
                                                 min_id=cursor, reverse=bool(cursor))
            last_id = cursor
            for message in messages:
                last_id = max(last_id, int(message.id))
                if not cursor and message.date < current - timedelta(hours=1):
                    continue
                item = message_item(message, name, current)
                if item:
                    output.append(item)
            checkpoints[name] = {'last_id':last_id, 'last_success_at':current.isoformat()}
        except Exception as exc:
            seconds = int(getattr(exc, 'seconds', 0) or 0)
            checkpoints[name] = {**prior, 'retry_after':current.timestamp() + max(300, seconds),
                                 'error':type(exc).__name__}
            errors.append(name + ':' + type(exc).__name__)
    return {'items':output, 'checkpoint':{'channels':checkpoints}, 'errors':errors,
            'status':'degraded' if errors else 'ok',
            'coverage':'Public broadcast allowlist: ' + ', '.join(names) +
                       '; newest 30 on bootstrap (1h), up to 50 unread per channel/cycle; no private chats; relay sources unverified'}


def fetch_telegram_news(state, at):
    if os.getenv('TELEGRAM_NEWS_READER_ENABLED','false').lower() != 'true':
        return {'items':[], 'coverage':'Telegram channel reader disabled'}
    if not SESSION.exists() or not os.getenv('TELEGRAM_API_ID') or not os.getenv('TELEGRAM_API_HASH'):
        raise ValueError('Telegram reader requires local API credentials and authorized session')
    names = channel_names()
    async def run():
        from telethon import TelegramClient
        client = TelegramClient(str(SESSION), int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'],
                                receive_updates=False, flood_sleep_threshold=0, request_retries=0,
                                connection_retries=1, timeout=10)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise ValueError('Telegram reader login expired; run local login helper')
            return await collect(client, state, at, names)
        finally:
            await client.disconnect()
    async def bounded():
        return await asyncio.wait_for(run(), timeout=60)
    return asyncio.run(bounded())
