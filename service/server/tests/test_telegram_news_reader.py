import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import telegram_news_reader as reader

NOW = datetime(2026, 9, 25, 10, tzinfo=timezone.utc)


def message(number=10, age=0, text='Economic news'):
    return SimpleNamespace(id=number, date=NOW-timedelta(hours=age), message=text, action=None)


def client():
    return SimpleNamespace(get_entity=AsyncMock(return_value=SimpleNamespace(broadcast=True, username='channel')),
                           get_messages=AsyncMock(return_value=[message()]))


def test_allowlist_normalizes_and_rejects_private_identifiers():
    with patch.dict(os.environ, TELEGRAM_NEWS_SOURCE_CHANNELS='@FinancialJuice,financialjuice,WalterBloomberg'):
        assert reader.channel_names() == ['financialjuice', 'walterbloomberg']
    with patch.dict(os.environ, TELEGRAM_NEWS_SOURCE_CHANNELS='financialjuice,WalterBloomberg,WatcherGuru'):
        assert reader.channel_names() == ['financialjuice','walterbloomberg','watcherguru']
    for invalid in ('', '+972123456789', 'https://t.me/channel', '-100123456'):
        with patch.dict(os.environ, TELEGRAM_NEWS_SOURCE_CHANNELS=invalid), pytest.raises(ValueError):
            reader.channel_names()


def test_no_stale_future_empty_or_service_messages():
    for msg in (message(age=7), message(age=-1), message(text='')):
        assert reader.message_item(msg, 'channel', NOW) is None
    msg = message(); msg.action = object()
    assert reader.message_item(msg, 'channel', NOW) is None
    item = reader.message_item(message(), 'channel', NOW)
    assert item['tickers'] == []
    assert item['url'] == 'https://t.me/channel/10'


def test_bootstrap_then_restart_uses_persisted_cursor():
    fake = client()
    fake.get_messages.return_value = [message(11), message(10, age=2)]
    first = asyncio.run(reader.collect(fake, {}, NOW, ['channel']))
    assert len(first['items']) == 1
    assert first['checkpoint']['channels']['channel']['last_id'] == 11
    fake.get_messages.return_value = []
    second = asyncio.run(reader.collect(fake, {'checkpoint_json': json.dumps(first['checkpoint'])}, NOW, ['channel']))
    assert second['items'] == []
    assert fake.get_messages.call_args.kwargs == {'limit': 50, 'min_id': 11, 'reverse': True}


def test_failure_preserves_cursor_and_other_channel_continues():
    fake = client()
    class Flood(Exception):
        seconds = 600
    fake.get_entity.side_effect = [Flood(), SimpleNamespace(broadcast=True, username='goodchannel')]
    state = {'checkpoint_json': json.dumps({'channels': {'badchannel': {'last_id': 8}}})}
    result = asyncio.run(reader.collect(fake, state, NOW, ['badchannel', 'goodchannel']))
    assert len(result['items']) == 1
    assert result['status'] == 'degraded'
    assert result['checkpoint']['channels']['badchannel']['last_id'] == 8
    assert result['checkpoint']['channels']['badchannel']['retry_after'] == NOW.timestamp()+600
    fake.get_entity.reset_mock()
    asyncio.run(reader.collect(fake, {'checkpoint_json': json.dumps(result['checkpoint'])}, NOW, ['badchannel']))
    fake.get_entity.assert_not_called()


def test_private_or_group_entity_never_read():
    fake = client()
    fake.get_entity.return_value = SimpleNamespace(broadcast=False, username='groupname')
    assert asyncio.run(reader.collect(fake, {}, NOW, ['groupname']))['errors']
    fake.get_messages.assert_not_called()


def test_disabled_needs_no_session_or_dependency():
    with patch.dict(os.environ, TELEGRAM_NEWS_READER_ENABLED='false'):
        assert reader.fetch_telegram_news({}, NOW)['items'] == []


def test_stream_ignores_non_allowlisted_chats_and_does_not_advance_cursor():
    msg=message();msg.peer_id=SimpleNamespace(channel_id=123)
    allowed={123:'channel'}
    assert reader.stream_item(msg,allowed,NOW)['url']=='https://t.me/channel/10'
    assert allowed=={123:'channel'}
    msg.peer_id=SimpleNamespace(channel_id=999)
    assert reader.stream_item(msg,allowed,NOW) is None
    msg.peer_id=SimpleNamespace(user_id=123)
    assert reader.stream_item(msg,allowed,NOW) is None


def test_stream_disabled_has_no_client_or_session_access(monkeypatch):
    monkeypatch.setenv('TELEGRAM_NEWS_STREAM_ENABLED','false')
    asyncio.run(reader.telegram_news_stream_loop())


def test_stream_ingests_live_event_catches_up_and_disconnects(monkeypatch, tmp_path):
    from unittest.mock import Mock
    import news_pipeline
    import database
    import scanner_engine
    for key in ('TELEGRAM_NEWS_STREAM_ENABLED','TELEGRAM_NEWS_READER_ENABLED','STOCK_SCANNER_ENABLED'):
        monkeypatch.setenv(key,'true')
    monkeypatch.setenv('TELEGRAM_API_ID','123')
    monkeypatch.setenv('TELEGRAM_API_HASH','test-only')
    monkeypatch.setenv('TELEGRAM_NEWS_SOURCE_CHANNELS','channel')
    session=tmp_path/'test.session';session.touch()
    monkeypatch.setattr(reader,'SESSION',session)
    fake=client()
    fake.connect=AsyncMock();fake.disconnect=AsyncMock()
    fake.is_user_authorized=AsyncMock(return_value=True)
    fake.get_entity.return_value=SimpleNamespace(id=123,broadcast=True,username='channel')
    fake.is_connected=Mock(return_value=True)
    handlers=[]
    fake.add_event_handler=lambda handler,event: handlers.append(handler)
    monkeypatch.setitem(sys.modules,'telethon',SimpleNamespace(
        TelegramClient=Mock(return_value=fake),
        events=SimpleNamespace(NewMessage=lambda:None,MessageEdited=lambda:None)))
    connection=Mock()
    connection.execute.return_value.fetchone.return_value={'checkpoint_json':'{}'}
    monkeypatch.setattr(database,'get_db_connection',lambda:connection)
    ingest=Mock();cycle=Mock();status=Mock()
    monkeypatch.setattr(news_pipeline,'ingest_items',ingest)
    monkeypatch.setattr(news_pipeline,'initialize_providers',Mock())
    monkeypatch.setattr(news_pipeline,'run_feed_cycle',cycle)
    monkeypatch.setattr(scanner_engine,'set_service_status',status)
    async def stop_after_event(seconds):
        msg=message();msg.date=datetime.now(timezone.utc)
        msg.peer_id=SimpleNamespace(channel_id=123)
        await handlers[0](SimpleNamespace(message=msg))
        raise asyncio.CancelledError()
    monkeypatch.setattr(reader.asyncio,'sleep',stop_after_event)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(reader.telegram_news_stream_loop())
    assert len(handlers)==2
    assert ingest.call_args.args[0][0]['url']=='https://t.me/channel/10'
    assert cycle.call_count==1
    fake.disconnect.assert_awaited_once()
    assert status.call_args.args[1]=='ok'
