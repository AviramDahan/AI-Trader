"""Pin the application's topics without removing unrelated existing pins."""
import asyncio
import argparse
import sys
from pathlib import Path
from dotenv import dotenv_values
from telethon import TelegramClient
from telethon.tl.functions.messages import GetForumTopicsRequest, ReorderPinnedForumTopicsRequest
from telethon.tl.functions.help import GetAppConfigRequest

ROOT = Path(__file__).resolve().parents[1]


async def main(apply=False):
    env = dotenv_values(ROOT / '.env')
    client = TelegramClient(str(ROOT / '.runtime/telegram-reader.session'), int(env['TELEGRAM_API_ID']),
                            env['TELEGRAM_API_HASH'], receive_updates=False, flood_sleep_threshold=0)
    async with client:
        chat = await client.get_entity(int(env['TELEGRAM_CHAT_ID']))
        config = await client(GetAppConfigRequest(hash=0))
        limits = {x.key: getattr(x.value, 'value', None) for x in config.config.value}
        limit = int(limits.get('topics_pinned_limit') or 5)
        current = await client(GetForumTopicsRequest(chat, None, 0, 0, 100))
        print('Pin limit:', limit)
        print('Topics:', [(t.id, getattr(t, 'title', ''), getattr(t, 'pinned', False)) for t in current.topics])
        keys = ['TELEGRAM_MARKET_NEWS_THREAD_ID', 'TELEGRAM_PERSONAL_NEWS_THREAD_ID',
                'TELEGRAM_STOCK_NEWS_THREAD_ID', 'TELEGRAM_PORTFOLIO_THREAD_ID']
        desired = [1] + [int(env[k]) for k in keys]
        managed = set(desired) | {int(env[k]) for k in ('TELEGRAM_SIGNALS_THREAD_ID', 'TELEGRAM_TRADES_THREAD_ID')}
        unrelated = [t.id for t in current.topics if getattr(t, 'pinned', False) and t.id not in managed]
        if unrelated:
            raise RuntimeError('Unrelated pinned topics found; not changing their order')
        if len(desired) > limit:
            raise RuntimeError('Requested order exceeds the server pin limit')
        order = desired
        if apply:
            await client(ReorderPinnedForumTopicsRequest(chat, order, force=True))
            result = await client(GetForumTopicsRequest(chat, None, 0, 0, 100))
            actual = [t.id for t in result.topics if getattr(t, 'pinned', False)]
            if actual != order:
                raise RuntimeError('Pinned order verification failed')
            print('Verified pinned order:', actual)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    asyncio.run(main(parser.parse_args().apply))
