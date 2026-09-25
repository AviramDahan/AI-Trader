"""Explicit user-authorized news-only cleanup; preserve topics and routing."""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from telethon import TelegramClient
from telethon.tl.functions.messages import GetForumTopicsByIDRequest

ROOT = Path(__file__).resolve().parents[1]
NEWS_KEYS = ('TELEGRAM_MARKET_NEWS_THREAD_ID', 'TELEGRAM_PERSONAL_NEWS_THREAD_ID',
             'TELEGRAM_STOCK_NEWS_THREAD_ID')
PROTECTED_KEYS = ('TELEGRAM_SIGNALS_THREAD_ID', 'TELEGRAM_TRADES_THREAD_ID',
                  'TELEGRAM_PORTFOLIO_THREAD_ID')


async def main(apply=False):
    cfg = dotenv_values(ROOT / '.env')
    topics = [int(cfg[key]) for key in NEWS_KEYS]
    protected = {int(cfg[key]) for key in PROTECTED_KEYS} | {1}
    if len(set(topics)) != 3 or set(topics) & protected:
        raise RuntimeError('News topic scope is ambiguous')
    client = TelegramClient(str(ROOT / '.runtime/telegram-reader.session'),
                            int(cfg['TELEGRAM_API_ID']), cfg['TELEGRAM_API_HASH'],
                            receive_updates=False, flood_sleep_threshold=0)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError('Authenticated Telegram session required')
        chat = await client.get_entity(int(cfg['TELEGRAM_CHAT_ID']))
        if not getattr(chat, 'forum', False):
            raise RuntimeError('Not a forum group')
        actual = await client(GetForumTopicsByIDRequest(chat, topics))
        if {t.id for t in actual.topics} != set(topics) or any('חדשות' not in t.title for t in actual.topics):
            raise RuntimeError('Topic identity mismatch')
        cutoff = datetime.now(timezone.utc)
        archive = []
        for topic in topics:
            async for message in client.iter_messages(chat, reply_to=topic):
                if message.id == topic or message.date > cutoff:
                    continue
                reply = message.reply_to
                parent = (getattr(reply, 'reply_to_top_id', None)
                          or getattr(reply, 'reply_to_msg_id', None))
                if parent != topic:
                    raise RuntimeError('Message outside selected news topic')
                archive.append({'id': message.id, 'topic': topic,
                                'date': message.date.isoformat(),
                                'text': message.message, 'record': message.to_dict()})
        print(json.dumps({'apply': apply, 'counts': {
            t.title: sum(m['topic'] == t.id for m in archive) for t in actual.topics}}, ensure_ascii=True))
        if not apply:
            return
        path = ROOT / '.runtime' / ('news-chat-cleanup-' + cutoff.strftime('%Y%m%dT%H%M%SZ') + '.json')
        path.write_text(json.dumps(archive, ensure_ascii=False, default=str), encoding='utf-8')
        # No topic deletion, no new IDs, no database reset, no test alerts.
        ids = [m['id'] for m in archive]
        for offset in range(0, len(ids), 100):
            await client.delete_messages(chat, ids[offset:offset+100], revoke=True)
        remaining = await client.get_messages(chat, ids=ids) if ids else []
        if any(m is not None for m in remaining):
            raise RuntimeError('Some selected messages remain; inspect archive before retry')
        print('Verified deleted messages:', len(ids))
        print('Private archive:', path)
    finally:
        await client.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    try:
        asyncio.run(main(parser.parse_args().apply))
    except Exception as exc:
        raise SystemExit(type(exc).__name__ + ': news cleanup stopped; no credentials logged')
