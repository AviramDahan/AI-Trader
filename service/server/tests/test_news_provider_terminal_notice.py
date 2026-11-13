"""Admin wording only: no provider request, Telegram send or state mutation."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_events import provider_config as controls
from news_events.model import fingerprint, timestamp
from news_events.press_feed import PressFeedProvider
from news_events.providers import Config

NOW = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
NEXT = '2026-10-20T17:02:00+00:00'


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', Mock(side_effect=AssertionError('no network')))


def state(code=301, **changes):
    return dict(status='requires_configuration', terminal=True, http_status=code,
                error='http_error', attempts=1, next_at=NEXT,
                last_success='2026-10-20T10:00:00+00:00',
                last_attempt='2026-10-20T14:00:00+00:00') | changes


def notify(monkeypatch, value, pid='prnewswire', before=None):
    enqueue = Mock()
    monkeypatch.setitem(sys.modules, 'ai_operations', SimpleNamespace(enqueue=enqueue))
    controls.notify_changes({pid: before or {}}, {pid: value}, NOW)
    return enqueue


def provider():
    return PressFeedProvider(Config('prnewswire', 'https://feed.example/rss', 'Synthetic',
                                    enabled=True, rights='approved'))


def test_terminal301_cannot_advertise_ignored_next_at_as_retry(monkeypatch):
    value = state()
    assert provider().recover_terminal(value, NOW) is None
    original = copy.deepcopy(value)
    enqueue = notify(monkeypatch, value)
    enqueue.assert_called_once()
    text = enqueue.call_args.args[1]
    assert 'HTTP: 301' in text and 'Status: requires_configuration' in text
    assert 'Next check: ' + NEXT not in text
    assert 'not scheduled' in text and 'operator review' in text
    assert value == original


@pytest.mark.parametrize('consumed', [False, True])
def test_terminal403_explains_conditional_probe_without_promised_time(monkeypatch, consumed):
    value = state(403)
    if consumed:
        value['checkpoint_json'] = '{"access_recovery_for":"2026-10-20T10:00:00+00:00"}'
    assert bool(provider().recover_terminal(value, NOW)) is not consumed
    original = copy.deepcopy(value)
    text = notify(monkeypatch, value).call_args.args[1]
    assert 'Next check: ' + NEXT not in text
    assert 'conditional' in text and '403' in text
    for condition in ('approval', 'cooldown', 'unused'):
        assert condition in text
    assert value == original


def test_unverified403_does_not_claim_the_press_recovery_allowance(monkeypatch):
    value = state(403, last_success=None)
    assert provider().recover_terminal(value, NOW) is None
    text = notify(monkeypatch, value).call_args.args[1]
    assert 'Next check: ' + NEXT not in text
    assert 'operator review' in text and 'conditional 403' not in text


def test_disabled_provider_is_not_labelled_an_operator_incident(monkeypatch):
    value = state(None, status='disabled', error='provider_not_enabled', next_at=None)
    text = notify(monkeypatch, value).call_args.args[1]
    assert 'DISABLED' in text and 'provider disabled' in text
    assert 'operator review' not in text


def test_nonterminal_message_and_dedupe_are_exactly_unchanged(monkeypatch):
    value = state(429, status='rate_limited', terminal=False)
    key, text = notify(monkeypatch, value).call_args.args
    expected_key = 'news_provider_transition:prnewswire:' + fingerprint([
        timestamp(NOW), (value['status'], value['error'], value['http_status'])])
    assert key == expected_key
    assert text == ('AI-Trader Admin\nNews provider: prnewswire — DEGRADED'
                    '\nStatus: rate_limited\nReason: http_error\nHTTP: 429'
                    '\nNext check: ' + NEXT)


def test_same_signature_does_not_send_new_notice_for_next_at_change(monkeypatch):
    old = state()
    value = old | {'next_at': '2026-10-20T18:00:00+00:00'}
    notify(monkeypatch, value, before=old).assert_not_called()


def test_non_press403_does_not_invent_press_recovery(monkeypatch):
    text = notify(monkeypatch, state(403), pid='benzinga').call_args.args[1]
    assert 'conditional 403' not in text and 'operator review' in text
