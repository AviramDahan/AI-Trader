"""Independent SEC response-deadline safety regressions, using local TLS only."""
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import urllib3.poolmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sec_transport as transport
import sec_intelligence as intelligence
from retry_policy import DeferredProviderError
from test_sec_transport import local_tls, stdlib_tls_context, tls_certificate
from test_sec_intelligence import isolated, filing

URL = "https://data.sec.gov/submissions/CIK0000320193.json"
UA = "Independent Fixture independent@example.com"


def test_mapping_isolation_and_repeated_success_cleanup(monkeypatch, tls_certificate):
    shared = urllib3.poolmanager.pool_classes_by_scheme
    previous = dict(shared)
    with local_tls(monkeypatch, tls_certificate, "normal") as owned:
        for _ in range(5):
            assert transport.fetch(URL, UA)[0] == b"ok"
        assert len(owned["timers"]) == 5
        assert all(not timer.is_alive() for timer in owned["timers"])
        assert urllib3.poolmanager.pool_classes_by_scheme is shared
        assert dict(shared) == previous
    with requests.Session() as unrelated:
        manager = unrelated.get_adapter("https://").poolmanager
        assert manager.pool_classes_by_scheme["https"] is previous["https"]


def test_timeout_does_not_change_global_pool_or_leave_work(monkeypatch, tls_certificate):
    shared = urllib3.poolmanager.pool_classes_by_scheme
    previous = dict(shared)
    monkeypatch.setattr(transport, "RESPONSE_TIMEOUT_SECONDS", .08)
    with local_tls(monkeypatch, tls_certificate, "body") as owned:
        for _ in range(3):
            started = time.monotonic()
            with pytest.raises(requests.exceptions.Timeout, match="sec_response_deadline"):
                transport.fetch(URL, UA)
            assert time.monotonic() - started < .35
        assert len(owned["timers"]) == 3
        assert all(not timer.is_alive() for timer in owned["timers"])
        assert urllib3.poolmanager.pool_classes_by_scheme is shared
        assert dict(shared) == previous


def test_dns_delay_demonstrates_response_only_not_full_call_deadline(monkeypatch, tls_certificate):
    # The system resolver precedes the established-response budget. This
    # controlled delay intentionally succeeds after more than that budget.
    monkeypatch.setattr(transport, "RESPONSE_TIMEOUT_SECONDS", .08)
    with local_tls(monkeypatch, tls_certificate, "normal"):
        loopback_dns = socket.getaddrinfo
        def slow_local_dns(*args, **kwargs):
            time.sleep(.16)
            return loopback_dns(*args, **kwargs)
        monkeypatch.setattr(socket, "getaddrinfo", slow_local_dns)
        began = time.monotonic()
        assert transport.fetch(URL, UA)[0] == b"ok"
        assert time.monotonic() - began >= .16


class Response:
    def __init__(self, status=200, headers=None, chunks=(b"ok",)):
        self.status_code = status
        self.headers = headers or {}
        self.chunks = chunks
        self.read = False
        self.closed = False
    def __enter__(self): return self
    def __exit__(self, *_): self.closed = True
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError("synthetic")
    def iter_content(self, _):
        self.read = True
        yield from self.chunks


def fake_session(monkeypatch, response):
    class Session:
        def __init__(self): self.closed = False; self.adapters = []; self.kwargs = None
        def __enter__(self): return self
        def __exit__(self, *_):
            for adapter in self.adapters: adapter.close()
            self.closed = True
        def mount(self, _, adapter): self.adapters.append(adapter)
        def get(self, _url, **kwargs): self.kwargs = kwargs; return response
    session = Session()
    monkeypatch.setattr(transport.requests, "Session", lambda: session)
    monkeypatch.setattr(transport, "reserve", lambda: None)
    return session


def test_cache_and_session_security_options_unchanged(monkeypatch):
    response = Response(304)
    session = fake_session(monkeypatch, response)
    assert transport.fetch(URL, UA, etag="fixture-tag", modified="fixture-time") == (
        None, {"etag": "fixture-tag", "modified": "fixture-time"})
    assert response.closed and session.closed and not response.read
    assert session.trust_env is False
    assert session.kwargs["allow_redirects"] is False
    assert session.kwargs["timeout"] == (4, 12)
    assert session.kwargs["stream"] is True
    assert session.kwargs["headers"]["Accept-Encoding"] == "identity"
    assert session.kwargs["headers"]["If-None-Match"] == "fixture-tag"
    assert session.kwargs["headers"]["If-Modified-Since"] == "fixture-time"


@pytest.mark.parametrize("status,retry,expected", [(403,"0",30),(429,"9000",3600),(503,"not-a-date",300)])
def test_deferred_backoff_and_cleanup_unchanged(monkeypatch,status,retry,expected):
    response = Response(status, {"Retry-After": retry})
    session = fake_session(monkeypatch, response)
    with pytest.raises(DeferredProviderError) as error:
        transport.fetch(URL, UA)
    assert error.value.status == status and error.value.retry_after_seconds == expected
    assert response.closed and session.closed and not response.read


@pytest.mark.parametrize("response,reason", [
    (Response(headers={"Content-Length":"4"}), "sec_document_too_large"),
    (Response(chunks=(b"ab",b"cd")), "sec_document_too_large"),
    (Response(headers={"Content-Encoding":"gzip"}), "sec_response_not_plain_200"),
    (Response(status=302), "sec_response_not_plain_200")])
def test_size_encoding_and_redirect_boundaries(monkeypatch,response,reason):
    session = fake_session(monkeypatch, response)
    with pytest.raises(ValueError, match=reason):
        transport.fetch(URL, UA, max_bytes=3)
    assert response.closed and session.closed


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/submissions/CIK0000320193.json",
    "https://data.sec.gov.evil.invalid/submissions/CIK0000320193.json",
    "https://user@data.sec.gov/submissions/CIK0000320193.json",
    "https://data.sec.gov/submissions/CIK0000320193.json?redirect=x",
    "https://www.sec.gov/submissions/CIK0000320193.json"])
def test_rejection_precedes_fair_access_or_session(monkeypatch,url):
    def forbidden(*_,**__): raise AssertionError("invalid URL reached I/O boundary")
    monkeypatch.setattr(transport, "reserve", forbidden)
    monkeypatch.setattr(transport.requests, "Session", forbidden)
    with pytest.raises(ValueError): transport.fetch(url, UA)


def test_local_fair_access_gap_unchanged(monkeypatch):
    monkeypatch.setenv("AI_TRADER_CLOUD", "false")
    monkeypatch.setenv("STOCK_SCANNER_SEC_REQUEST_GAP_SECONDS", ".01")
    monkeypatch.setattr(transport, "_LOCAL_NEXT", 0.0)
    monkeypatch.setattr(transport.time, "monotonic", lambda: 10.0)
    sleeps = []
    monkeypatch.setattr(transport.time, "sleep", sleeps.append)
    transport.reserve(); transport.reserve(); transport.reserve()
    assert sleeps == [.5, 1.0]


def test_deadline_timeout_is_transient_for_actual_filing_caller(isolated, monkeypatch):
    now = datetime(2026, 10, 15, 5, tzinfo=timezone.utc)
    uid, _ = intelligence.save_universe(
        {"AAPL": {"company": "Synthetic", "indexes": ["sp500"]}},
        {"0000320193": ["AAPL"]}, now)
    intelligence._queue_filing(
        filing("0000320193-26-000099", "4", now - timedelta(hours=1)),
        "0000320193", ["AAPL"], uid, now, [10])
    monkeypatch.setenv("NEWS_SEC_USER_AGENT", UA)
    def deadline(*_, **__): raise requests.exceptions.Timeout("sec_response_deadline")
    monkeypatch.setattr(intelligence, "fetch", deadline)
    result = intelligence.process_jobs(now)
    assert result["processed"] == 0 and result["failed"] == 1
    with isolated() as connection:
        row = dict(connection.execute("SELECT status,attempts,next_attempt_at,error_code FROM si_filing_jobs").fetchone())
        assert row["status"] == "retry" and row["attempts"] == 1
        assert row["next_attempt_at"] and row["error_code"] == "Timeout"
        assert connection.execute("SELECT count(*) n FROM scanner_telegram_outbox").fetchone()["n"] == 0
    assert intelligence._discovery_error_code(requests.exceptions.Timeout("sec_response_deadline")) == "Timeout"
