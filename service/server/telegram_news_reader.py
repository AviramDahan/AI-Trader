"""Read only explicitly configured public broadcast channels; never send or join."""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = Path(os.getenv('TELEGRAM_SESSION_PATH', str(ROOT / '.runtime/telegram-reader.session')))
MAX_DEFERRED_MEDIA = 50
MEDIA_RETRY_SECONDS = 300


def streaming_enabled():
    return (os.getenv('TELEGRAM_NEWS_STREAM_ENABLED', 'false').lower() == 'true'
            and os.getenv('TELEGRAM_NEWS_READER_ENABLED', 'false').lower() == 'true')


def stream_item(message, allowed, current):
    name = allowed.get(getattr(getattr(message, 'peer_id', None), 'channel_id', None))
    return message_item(message, name, current) if name else None


async def telegram_news_stream_loop():
    """Allowlisted updates plus durable catch-up; never join/send.

    Live events do not advance the catch-up cursor: an out-of-order event must
    not cause missing history after reconnect. Ingestion is idempotent.
    """
    if not streaming_enabled() or os.getenv('STOCK_SCANNER_ENABLED','false').lower() != 'true':
        return
    from telethon import TelegramClient, events
    from news_pipeline import ingest_items, run_feed_cycle, initialize_providers
    from database import get_db_connection
    from scanner_engine import set_service_status
    while True:
        client = None
        retry = 60
        try:
            names = channel_names()
            if not SESSION.exists():
                raise ValueError('Reader login required')
            client = TelegramClient(str(SESSION), int(os.environ['TELEGRAM_API_ID']),
                                    os.environ['TELEGRAM_API_HASH'], receive_updates=True,
                                    flood_sleep_threshold=0, request_retries=0,
                                    connection_retries=1, timeout=10)
            await asyncio.wait_for(client.connect(), timeout=30)
            if not await client.is_user_authorized():
                raise ValueError('Reader login expired')
            allowed = {}
            for name in names:
                from trump_truth_posts import source_channel, valid_entity
                CHANNEL=source_channel()
                try:
                    entity = await client.get_entity(name)
                    if name == CHANNEL and not valid_entity(entity):
                        raise ValueError('Trump relay identity changed')
                except Exception:
                    if name != CHANNEL:
                        raise
                    # One new feed cannot disable the established news sources.
                    set_service_status('trump_truth_posts', 'degraded', 'Relay identity/access not verified')
                    continue
                if not getattr(entity,'broadcast',False) or not getattr(entity,'username',None):
                    raise ValueError('Not a public broadcast channel')
                allowed[entity.id] = name

            trump_ready = False
            async def on_message(event):
                from trump_truth_posts import source_channel_id
                CHANNEL_ID=source_channel_id()
                from trump_telegram_channel import CHANNEL_ID as NEW_ID, CHANNEL as NEW_CHANNEL
                peer=getattr(getattr(event.message,'peer_id',None),'channel_id',None)
                group=getattr(event.message,'grouped_id',None)
                # Revocation precedes readiness: a reconnect must not ignore an
                # observed edit of an already queued album while catch-up starts.
                if (peer==NEW_ID and allowed.get(peer)==NEW_CHANNEL and type(group) is int
                    and 0<group<2**63 and isinstance(event,events.MessageEdited.Event)):
                    from trump_telegram_album import invalidate_group
                    await asyncio.to_thread(invalidate_group,event.message,datetime.now(timezone.utc))
                if getattr(getattr(event.message, 'peer_id', None), 'channel_id', None) == CHANNEL_ID and not trump_ready:
                    return  # Catch-up owns the first persisted activation cursor.
                if getattr(getattr(event.message,'peer_id',None),'channel_id',None)==NEW_ID:
                    if getattr(event.message,'grouped_id',None) is not None:
                        return  # Existing catch-up alone owns bounded album assembly.
                    if getattr(event.message,'photo',None) or getattr(event.message,'document',None):
                        return  # Do not spend capture budget twice via live+catch-up.
                item = stream_item(event.message, allowed, datetime.now(timezone.utc))
                if item:
                    try:
                        if item.get('source_kind') in {'trump_truth_relay_v1','trump_telegram_channel_v1'}:
                            from trump_truth_media import capture
                            item=await capture(client,event.message,item,datetime.now(timezone.utc))
                        await asyncio.to_thread(ingest_items, [item])
                        set_service_status('news_stream','ok','Public allowlisted update ingested',success=True)
                    except Exception as exc:
                        set_service_status('news_stream','error',type(exc).__name__)

            client.add_event_handler(on_message, events.NewMessage())
            client.add_event_handler(on_message, events.MessageEdited())
            await asyncio.to_thread(initialize_providers)
            while client.is_connected():
                conn = get_db_connection()
                state = dict(conn.execute("SELECT * FROM scanner_news_providers WHERE provider='telegram_channels'").fetchone())
                conn.close()
                current = datetime.now(timezone.utc)
                result = await asyncio.wait_for(collect(client,state,current,names),timeout=60)
                cycle = await asyncio.to_thread(run_feed_cycle, {'telegram_channels':lambda *_: result}, current, True,
                                                telegram_stream=True)
                if isinstance(cycle, dict) and cycle.get('providers', {}).get('telegram_channels', {}).get('status') in {'ok', 'no_new', 'degraded'}:
                    from trump_truth_posts import source_channel, activation, enabled
                    CHANNEL=source_channel()
                    checkpoint = result.get('checkpoint', {}).get('channels', {}).get(CHANNEL, {})
                    try:
                        trump_ready = enabled() and checkpoint.get('trump_activation') == activation()
                    except (KeyError, TypeError, ValueError):
                        trump_ready = False  # Only the dedicated source is blocked.
                set_service_status('news_stream','degraded' if result['errors'] else 'ok',
                                   'Live updates with 60-second cursor catch-up',success=not result['errors'])
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            retry = max(60, int(getattr(exc,'seconds',0) or 0))
            set_service_status('news_stream','error',type(exc).__name__)
        finally:
            if client:
                await client.disconnect()
        await asyncio.sleep(retry)


def channel_names():
    names = list(dict.fromkeys(x.strip().lstrip('@').lower() for x in
                              os.getenv('TELEGRAM_NEWS_SOURCE_CHANNELS', '').split(',') if x.strip()))
    from trump_truth_posts import source_channel, enabled,CHANNEL as OLD
    from trump_telegram_channel import CHANNEL as NEW
    CHANNEL=source_channel()
    # At most five ordinary sources, plus this one fixed, separately approved
    # source. It is never accepted as a generic economically-filtered relay.
    names = [name for name in names if name not in {OLD,NEW}]
    if len(names) > 5 or any(not re.fullmatch(r'[a-z][a-z0-9_]{4,31}', x) for x in names):
        raise ValueError('Configure 1-5 public broadcast usernames')
    if enabled():
        names.append(CHANNEL)
    if not names:
        raise ValueError('Configure 1-5 public broadcast usernames')
    return names


def message_item(message, username, current):
    from trump_truth_posts import source_channel,extract,CHANNEL as OLD,CHANNEL_ID as OLD_ID
    from trump_telegram_channel import CHANNEL as NEW,CHANNEL_ID as NEW_ID
    if username.lower() in {OLD,NEW} or getattr(getattr(message, 'peer_id', None), 'channel_id', None) in {OLD_ID,NEW_ID}:
        return extract(message,current)[0] if username.lower()==source_channel() else None
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
            from trump_truth_posts import source_channel, enabled, activation, valid_entity, extract
            CHANNEL=source_channel()
            special = name == CHANNEL
            if special and (not enabled() or not valid_entity(entity)):
                raise ValueError('Trump relay disabled or identity changed')
            cursor = int(prior.get('last_id', 0))
            if special and prior.get('trump_activation') != activation():
                # No historical burst on initial activation/reactivation/restore.
                # Install one latest-ID fence; live events wait until persisted.
                latest = await client.get_messages(entity, limit=1)
                checkpoints[name] = {'last_id': max([int(m.id) for m in latest] or [0]),
                    'last_success_at': current.isoformat(), 'trump_activation': activation(),
                    'coverage': 'relay_only_bootstrap_fence_no_history_primary_coverage_unknown'}
                continue
            # New source: at most 30 recent posts, with one-hour bootstrap window.
            # Existing cursor: oldest unread first so a busy source cannot lose gaps.
            messages = await client.get_messages(entity, limit=50 if cursor or special else 30,
                                                 min_id=cursor, reverse=bool(cursor or special))
            from trump_telegram_channel import selected as channel_selected
            separate_media = special and channel_selected()
            deferred = {}
            media_available_this_cycle = True
            retry_id = None
            if separate_media:
                now = int(current.timestamp())
                saved = prior.get('deferred_media', [])
                deferred = {entry['id']: entry for entry in saved if entry['expires'] > now}
                if len(deferred) < len(saved):
                    errors.append(name + ':deferred_media_expired')
                due = min(deferred.values(), key=lambda item: item['retry'], default=None)
                if due and due['retry'] <= now:
                    try:
                        seed = await asyncio.wait_for(client.get_messages(entity, ids=due['id']), timeout=5)
                    except Exception as exc:
                        due['retry'] = now + max(MEDIA_RETRY_SECONDS, int(getattr(exc, 'seconds', 0) or 0))
                        errors.append(name + ':deferred_media_source_unavailable')
                    else:
                        if seed is None:
                            deferred.pop(due['id'])
                            errors.append(name + ':deferred_media_source_missing')
                        elif seed.id == due['id'] and getattr(seed, 'grouped_id', None) == due['group']:
                            retry_id = seed.id
                            messages = [seed, *messages]
                        else:
                            deferred.pop(due['id'])
                            errors.append(name + ':deferred_media_source_changed')
            last_id = cursor
            rejected = {}
            for message in messages:
                retrying = message.id == retry_id
                if retrying:
                    retry_id = None  # The normal page may also contain this seed.
                if special and message.id<=last_id and not retrying:continue
                group = getattr(message, 'grouped_id', None)
                if separate_media and not retrying and group is not None and any(
                    entry['group'] == group for entry in deferred.values()
                ):
                    last_id = max(last_id, message.id)
                    continue
                if not special:last_id=max(last_id,int(message.id))
                if not special and not cursor and message.date < current - timedelta(hours=1):
                    continue
                if special:
                    from database import get_db_connection
                    from trump_truth_posts import PREFIX
                    known=None
                    if name=='real_donaldjtrump' and (getattr(message,'grouped_id',None) is not None or
                        getattr(message,'photo',None) or getattr(message,'document',None)):
                        with get_db_connection() as lookup:
                            known=lookup.execute('SELECT id FROM scanner_telegram_outbox WHERE dedupe_key=?',
                                (PREFIX+'tg:1462338131:'+str(message.id),)).fetchone()
                    if known:
                        deferred.pop(message.id, None)
                        last_id=max(last_id,int(message.id));continue
                    item, reason = extract(message, current)
                    if separate_media and item and item['has_media']:
                        if current - message.date > timedelta(hours=24):
                            errors.append(name + ':deferred_media_expired')
                            deferred.pop(message.id, None)
                            last_id = max(last_id, message.id)
                            continue
                        if not retrying and len(deferred) >= MAX_DEFERRED_MEDIA:
                            errors.append(name + ':deferred_media_capacity')
                            break  # No cursor movement over a post we cannot retain.
                        if media_available_this_cycle:
                            media_available_this_cycle = False
                            try:
                                item, reason, group_last = await asyncio.wait_for(
                                    _acquire_media(client, entity, message, item, current), timeout=35)
                            except TimeoutError:
                                item, reason, group_last = None, 'media_deferred_timeout', message.id
                        else:
                            item, reason, group_last = None, 'media_deferred_cycle_budget', message.id
                        if item:
                            output.append(item)
                            deferred.pop(message.id, None)
                            last_id = max(last_id, group_last)
                        else:
                            errors.append(name + ':' + reason)
                            retry_delay = 60 if reason in {'album_settling', 'album_media_budget_deferred',
                                                          'media_deferred_cycle_budget'} else MEDIA_RETRY_SECONDS
                            deferred[message.id] = dict(id=message.id, group=group,
                                retry=now + retry_delay,
                                expires=int(message.date.timestamp()) + 24 * 3600)
                            last_id = max(last_id, message.id)
                        continue
                    if reason:
                        deferred.pop(message.id, None)
                        rejected[reason] = rejected.get(reason, 0) + 1
                        if reason not in {'other_author_or_header', 'outside_activation', 'non_original_or_unverifiable'}:
                            errors.append(name + ':' + reason)
                else:
                    item = message_item(message, name, current)
                if item:
                    if special:
                        # Durable per-member/standalone claims precede capture
                        # so catch-up never reacquires an already queued file.
                        from database import get_db_connection
                        from trump_truth_posts import PREFIX
                        known=None
                        if item['has_media']:
                            with get_db_connection() as lookup:
                                known=lookup.execute('SELECT id FROM scanner_telegram_outbox WHERE dedupe_key=?',
                                    (PREFIX+item['truth_post_id'],)).fetchone()
                        if known:
                            last_id=max(last_id,int(message.id));continue
                        from trump_truth_media import capture
                        item=await capture(client,message,item,current)
                    output.append(item)
                last_id=max(last_id,int(message.id))
            checkpoints[name] = {'last_id':last_id, 'last_success_at':current.isoformat()}
            if special:
                checkpoints[name].update(trump_activation=activation(), rejected=rejected,
                    coverage='relay_only_oldest_unread_50_per_cycle_primary_coverage_unknown')
                if separate_media:
                    checkpoints[name]['deferred_media'] = list(deferred.values())
                    if deferred and not any(error.startswith(name + ':') for error in errors):
                        errors.append(name + ':deferred_media_waiting')
        except Exception as exc:
            seconds = int(getattr(exc, 'seconds', 0) or 0)
            checkpoints[name] = {**prior, 'retry_after':current.timestamp() + max(300, seconds),
                                 'error':type(exc).__name__}
            errors.append(name + ':' + type(exc).__name__)
    return {'items':output, 'checkpoint':{'channels':checkpoints}, 'errors':errors,
            'status':'degraded' if errors else 'ok',
            'coverage':'Public broadcast allowlist: ' + ', '.join(names) +
                       '; ordinary bootstrap 30 (1h); Trump first-ID fence no history; up to 50 unread/channel/cycle; no private chats; primary coverage unknown'}


async def _acquire_media(client, entity, message, item, current):
    if getattr(message, 'grouped_id', None) is not None:
        from trump_telegram_album import collect_album
        return await collect_album(client, entity, message, current)
    from trump_truth_media import capture
    result = await capture(client, message, item, current)
    if result.get('media', {}).get('status') == 'available':
        return result, None, message.id
    return None, 'media_deferred', message.id


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
