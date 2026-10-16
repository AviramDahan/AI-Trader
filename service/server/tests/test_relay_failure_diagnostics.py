"""Synthetic private transport only; no real socket, generation, DB or Telegram."""
import http.client
import json
import socket
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_routing as routing


@pytest.mark.parametrize('status,raw,error,reason,observed_status', [
    (503, b'PRIVATE_SENTINEL', None, 'relay_http_error', 503),
    (200, b'x' * (routing.MAX_BYTES + 1), None, 'relay_response_too_large', 200),
    (200, b'PRIVATE_SENTINEL', None, 'relay_invalid_json', 200),
    (200, b'{}', socket.timeout('PRIVATE_SENTINEL'), 'relay_timeout', None),
    (200, b'{}', OSError('PRIVATE_SENTINEL'), 'relay_socket_error', None),
    (200, b'{}', http.client.BadStatusLine('PRIVATE_SENTINEL'), 'relay_http_protocol_error', None),
], ids=['http_503', 'oversized', 'invalid_json', 'timeout', 'socket', 'protocol'])
def test_fixed_failure_reason_survives_without_transport_text(monkeypatch, status, raw, error, reason, observed_status):
    response = Mock(status=status)
    response.read.return_value = raw
    conn = Mock(sock=None)
    conn.getresponse.return_value = response
    if error:
        conn.request.side_effect = error
    monkeypatch.setattr(routing, 'UnixHTTP', Mock(return_value=conn))
    timer = Mock()
    monkeypatch.setattr(routing.threading, 'Timer', Mock(return_value=timer))
    with pytest.raises(requests.ConnectionError) as caught:
        routing.relay('POST', '/completion', {'synthetic': True}, timeout=2)
    exc = caught.value
    assert type(exc) is requests.ConnectionError
    assert str(exc) == 'local_relay_unavailable' and exc.response is None
    diagnostic = getattr(exc, 'local_transport_failure', {})
    assert diagnostic == {'reason': reason, **({'http_status': observed_status} if observed_status is not None else {})}
    assert 'PRIVATE_SENTINEL' not in json.dumps(diagnostic)
    conn.request.assert_called_once()
    conn.close.assert_called_once()
    timer.start.assert_called_once()
    timer.cancel.assert_called_once()
    if not error:
        response.close.assert_called_once()


@pytest.mark.parametrize('status,raw,expected', [
    (200, b'{"ok":true}', {'ok': True}),
    (413, b'{"reason":"local_context_capacity"}', 'capacity'),
])
def test_valid_response_and_capacity_keep_existing_contract(monkeypatch, status, raw, expected):
    response = Mock(status=status)
    response.read.return_value = raw
    conn = Mock(sock=None)
    conn.getresponse.return_value = response
    monkeypatch.setattr(routing, 'UnixHTTP', Mock(return_value=conn))
    monkeypatch.setattr(routing.threading, 'Timer', Mock(return_value=Mock()))
    if expected == 'capacity':
        with pytest.raises(routing.LocalCapacity) as caught:
            routing.relay('POST', '/completion', {})
        assert routing.fallback_reason(caught.value) == 'local_context_capacity'
        assert not getattr(caught.value, 'local_transport_failure', None)
    else:
        assert routing.relay('POST', '/completion', {}) == expected
    conn.request.assert_called_once()
    conn.close.assert_called_once()
    response.close.assert_called_once()


def test_request_size_rejection_is_not_relabelled_or_sent(monkeypatch):
    conn = Mock()
    monkeypatch.setattr(routing, 'UnixHTTP', conn)
    with pytest.raises(requests.ConnectionError, match='local_request_too_large'):
        routing.relay('POST', '/completion', {'synthetic': 'x' * routing.MAX_BYTES})
    conn.assert_not_called()


@pytest.mark.parametrize('value', [None, [], 'PRIVATE_SENTINEL',
    {'reason': 'PRIVATE_SENTINEL'}, {'reason': ['relay_http_error']},
    type('UntrustedDict', (dict,), {})({'reason': 'relay_http_error'})])
def test_unknown_or_nonplain_diagnostic_is_not_trusted(value):
    assert routing.safe_local_transport_failure(value) == {}


@pytest.mark.parametrize('status', [True, False, 99, 600, -1, 503.0, '503', None])
def test_status_must_be_a_real_bounded_integer(status):
    assert routing.safe_local_transport_failure({'reason': 'relay_http_error',
        'http_status': status, 'body': 'PRIVATE_SENTINEL'}) == {'reason': 'relay_http_error'}


def test_failure_diagnostic_is_a_sanitized_copy_not_mutable_input():
    original = {'reason': 'relay_http_error', 'http_status': 503, 'body': 'PRIVATE_SENTINEL'}
    actual = routing.safe_local_transport_failure(original)
    original['reason'] = 'PRIVATE_SENTINEL'
    assert actual == {'reason': 'relay_http_error', 'http_status': 503}

