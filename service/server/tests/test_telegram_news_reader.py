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
