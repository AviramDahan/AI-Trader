"""Independent synthetic brief guards; no provider/model/Telegram/Production IO."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import socket
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from news_events.engine import Analysis, Pipeline, Policy, route
from news_events.market_briefs import eligible, source as matching_source
from news_events.model import Source
from news_events.store import Store


AT = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def event():
    original = dict(provider_id="synthetic", source_id="only",
        url="https://example.invalid/articles/brief-12345", publisher="Synthetic source",
        published_at=AT.isoformat(), collected_at=AT.isoformat(),
        title="S&P 500 rises 0.2%", source_excerpt="", rights="approved",
        source_type="official/regulatory", tickers=(), cik="", event_type="market",
        event_refs=(), claims={}, raw_metadata={})
    return dict(event_id="synthetic", evidence_version="v1", event_type="market",
        tickers=[], company_identity=[], conflicts=[], sources=[original],
        source_urls=[original["url"]], published_at=AT.isoformat(),
        title=original["title"], normalized_evidence=[{"text": original["title"]}])


def result(**changes):
    return dict(dict(related=True, relevance=.7, materiality="low", sentiment="neutral",
        title_he="לפי המקור, מדד S&P 500 עלה ב־0.2%",
        summary_he="המקור דיווח על העלייה; לא נמסרה סיבה ולא הוצגה המלצת מסחר.",
        interpretation_he="פרשנות סינתטית שלא תפורסם בעדכון הקצר."), **changes)


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Independent brief tests forbid external IO")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", denied)


@pytest.mark.parametrize("field,value", [
    ("title_he", ["טקסט"]), ("title_he", {"text": "טקסט"}),
    ("summary_he", ["טקסט"]), ("summary_he", {"text": "טקסט"}),
])
def test_malformed_retained_review_text_is_not_a_brief(field, value):
    assert not eligible(event(), result(**{field: value}))


def test_licensed_credits_cannot_truncate_mandatory_brief_source_or_time(monkeypatch):
    from news_events import runtime
    monkeypatch.setitem(sys.modules, "news_pipeline",
        SimpleNamespace(_publication_time_he=lambda value: "SYNTHETIC_TIME"))
    item = event()
    item["sources"] = [dict(item["sources"][0], publisher="Licensed source " + str(i),
        raw_metadata={"license_label": "Synthetic license " + str(i),
            "license_url": "https://example.invalid/license/" + str(i) + "x" * 180})
        for i in range(25)]
    # It is valid to reject an oversized brief; never silently lose its source,
    # time or required credits through the legacy 4000-character truncation.
    if not eligible(item, result()):
        return
    rendered = runtime.message(item, result(), "market_news", [])
    original = matching_source(item)
    assert "מקור: " + original["publisher"] + "\n" + original["url"] in rendered
    assert "פורסם: SYNTHETIC_TIME" in rendered
    assert all(s["raw_metadata"]["license_url"] in rendered for s in item["sources"])
    assert len(rendered) <= 4000


@pytest.mark.parametrize("bad", [False, None, 0, 1, "true", "false", [], {}])
def test_policy_requires_literal_true_not_truthy_values(bad):
    assert route(event(), result(), set(), set(), {},
        Policy(market_briefs_enabled=bad)) == ([], "low_importance")


@pytest.mark.parametrize("changes,reason", [
    ({"related": False}, "irrelevant"),
    ({"relevance": .299999}, "below_market_threshold"),
    ({"materiality": "unknown"}, "low_importance"),
])
def test_opt_in_does_not_relax_other_numeric_or_related_gates(changes, reason):
    assert route(event(), result(**changes), set(), set(), {},
        Policy(market_briefs_enabled=True)) == ([], reason)


def test_existing_threshold_boundary_and_source_url_are_retained():
    item = event()
    item["sources"][0]["url"] += "?api_key=not-a-real-key&utm_source=fixture&item=1"
    assert matching_source(item)["url"].endswith("?item=1")
    assert route(item, result(relevance=.3), set(), set(), {},
        Policy(market_briefs_enabled=True)) == ([("market_news", [])], None)


@pytest.mark.parametrize("case", ["ticker", "identity", "source_cik", "source_ticker",
    "provider_ticker", "company_type", "rights", "conflict", "mismatched_title",
    "no_evidence", "nonfactual_long_excerpt", "opinion", "unsafe_url"])
def test_every_source_and_company_boundary_is_fail_closed(case):
    item = event()
    if case == "ticker": item["tickers"] = ["FIX"]
    elif case == "identity": item["company_identity"] = [{"ticker": "FIX"}]
    elif case == "source_cik": item["sources"][0]["cik"] = "1234"
    elif case == "source_ticker": item["sources"][0]["tickers"] = ["FIX"]
    elif case == "provider_ticker": item["sources"][0]["raw_metadata"] = {"provider_tickers": ["FIX"]}
    elif case == "company_type": item["event_type"] = "earnings"
    elif case == "rights": item["sources"].append(dict(item["sources"][0], rights="internal_review"))
    elif case == "conflict": item["conflicts"] = [{"status": "contested"}]
    elif case == "mismatched_title": item["sources"][0]["title"] = "An unrelated headline"
    elif case == "no_evidence": item["normalized_evidence"] = []
    elif case == "nonfactual_long_excerpt":
        item["title"] = item["sources"][0]["title"] = "A general economic update"
        item["sources"][0]["source_excerpt"] = " ".join(["context"] * 20)
    elif case == "opinion": item["title"] = item["sources"][0]["title"] = "Could S&P 500 rise tomorrow?"
    elif case == "unsafe_url": item["sources"][0]["url"] = "https://user:password@example.invalid/news"
    assert not eligible(item, result())


@pytest.fixture
def canonical(tmp_path, monkeypatch):
    """Real canonical Store/Pipeline, isolated SQLite, delivery boundary fake."""
    from news_events import runtime
    real_pipeline = runtime.pipeline
    path = tmp_path / "briefs.sqlite"
    def connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c
    store = Store(connect, sandbox=True)
    store.install()
    with store.transaction(True) as c:
        c.execute("CREATE TABLE ne_cutover_receipts(source_url TEXT,topic TEXT,PRIMARY KEY(source_url,topic))")
        c.execute("CREATE TABLE ne_outbox(dedupe_key TEXT PRIMARY KEY,event_id TEXT,version TEXT,topic TEXT,epoch INT)")
        c.execute("CREATE TABLE scanner_telegram_outbox(dedupe_key TEXT PRIMARY KEY,event_type TEXT,message TEXT,published_at TEXT)")
        c.execute("CREATE TABLE scanner_trades(ticker TEXT,company TEXT,status TEXT,is_shadow INT)")
        c.execute("CREATE TABLE scanner_news_watchlist(ticker TEXT,company TEXT,enabled INT)")
    pipeline = Pipeline(store, {}, lambda: (set(), set()), not_before=AT - timedelta(days=1),
        policy=Policy(market_briefs_enabled=True))
    current = dict(mode="canonical", epoch=42, not_before=pipeline.not_before)
    def enqueue(c, key, kind, message, *, published_at):
        return c.execute("INSERT OR IGNORE INTO scanner_telegram_outbox VALUES(?,?,?,?)",
            (key, kind, message, published_at)).rowcount == 1
    status = Mock()
    monkeypatch.setitem(sys.modules, "scanner_engine",
        SimpleNamespace(enqueue_telegram=enqueue, set_service_status=status))
    monkeypatch.setitem(sys.modules, "news_pipeline",
        SimpleNamespace(_publication_time_he=lambda value: "SYNTHETIC_TIME"))
    monkeypatch.setattr(runtime, "state", lambda c=None: dict(current))
    monkeypatch.setattr(runtime, "active", lambda: current["mode"] == "canonical")
    monkeypatch.setattr(runtime, "membership", lambda c=None: (set(), set()))
    monkeypatch.setattr(runtime, "pipeline", lambda: pipeline)
    monkeypatch.setattr(runtime, "now", lambda: AT)
    return SimpleNamespace(p=pipeline, s=store, connect=connect, current=current,
        runtime=runtime, status=status, real_pipeline=real_pipeline)


def enqueue_brief(fixture):
    original = Source(**event()["sources"][0])
    eid = fixture.p.ingest(original, AT)
    analyzer = Mock(return_value=Analysis(result()))
    assert fixture.p.analyze(eid, analyzer, AT) == "done"
    assert fixture.runtime.queue_outbox(fixture.p, eid, AT) == 1
    with fixture.s.transaction() as c:
        row = dict(c.execute("SELECT * FROM scanner_telegram_outbox").fetchone())
    return eid, row, original, analyzer


def test_actual_pending_message_is_revoked_when_flag_off_then_restart_dedupes(canonical):
    from dataclasses import replace
    eid, row, original, analyzer = enqueue_brief(canonical)
    message = canonical.runtime.delivery_message(row)
    assert "עדכון שוק קצר" in message and original.url in message
    assert result()["interpretation_he"] not in message
    canonical.p.policy = replace(canonical.p.policy, market_briefs_enabled=False)
    assert canonical.runtime.delivery_message(row) is None
    restarted = Pipeline(Store(canonical.connect, sandbox=True), {}, canonical.p.membership,
        not_before=canonical.p.not_before, policy=replace(canonical.p.policy, market_briefs_enabled=True))
    assert restarted.ingest(original, AT + timedelta(seconds=1)) == eid
    assert restarted.analyze(eid, analyzer, AT + timedelta(seconds=1)) == "done"
    assert canonical.runtime.queue_outbox(restarted, eid, AT + timedelta(seconds=1)) == 0
    analyzer.assert_called_once()
    with canonical.s.transaction() as c:
        for name in ("ne_analysis", "ne_delivery", "ne_outbox", "scanner_telegram_outbox"):
            assert c.execute("SELECT count(*) FROM " + name).fetchone()[0] == 1


@pytest.mark.parametrize("change", ["expired", "epoch", "mode", "version", "review", "withdrawn",
    "rights", "conflict", "company_identity"])
def test_actual_send_time_revalidates_every_pending_guard(canonical, monkeypatch, change):
    eid, row, original, _ = enqueue_brief(canonical)
    assert canonical.runtime.delivery_message(row)
    if change == "expired": monkeypatch.setattr(canonical.runtime, "now", lambda: AT + timedelta(hours=7))
    elif change == "epoch": canonical.current["epoch"] += 1
    elif change == "mode": canonical.current["mode"] = "phase1"
    elif change == "withdrawn": canonical.s.withdraw(original.provider_id, original.source_id, AT)
    else:
        with canonical.s.transaction(True) as c:
            if change == "version": c.execute("UPDATE ne_events SET evidence_version='new-unreviewed' WHERE event_id=?", (eid,))
            elif change == "review": c.execute("UPDATE ne_events SET status='needs_material_review',reason='new_text_materiality_unverified' WHERE event_id=?", (eid,))
            else:
                body = json.loads(c.execute("SELECT body_json FROM ne_events WHERE event_id=?", (eid,)).fetchone()[0])
                if change == "rights": body["sources"][0]["rights"] = "internal_review"
                elif change == "conflict": body["conflicts"] = [{"status": "contested"}]
                elif change == "company_identity": body["company_identity"] = [{"ticker": "FIX"}]
                c.execute("UPDATE ne_events SET body_json=? WHERE event_id=?", (json.dumps(body), eid))
    assert canonical.runtime.delivery_message(row) is None


def test_enabling_flag_does_not_automatically_requeue_old_low_importance(canonical, monkeypatch):
    from dataclasses import replace
    original = Source(**event()["sources"][0])
    eid = canonical.p.ingest(original, AT)
    canonical.p.analyze(eid, lambda e: Analysis(result()), AT)
    canonical.p.policy = replace(canonical.p.policy, market_briefs_enabled=False)
    assert canonical.runtime.queue_outbox(canonical.p, eid, AT) == 0
    assert canonical.s.event(eid)["reason"] == "low_importance"
    canonical.p.policy = replace(canonical.p.policy, market_briefs_enabled=True)
    available = Mock(side_effect=AssertionError("Old low importance must not invoke AI"))
    monkeypatch.setitem(sys.modules, "ai_routing", SimpleNamespace(check_available=available))
    assert canonical.runtime.analyze_jobs(AT) == {"analyzed": 0, "alerts": 0, "errors": []}
    available.assert_not_called()
    with canonical.s.transaction() as c:
        assert c.execute("SELECT count(*) FROM scanner_telegram_outbox").fetchone()[0] == 0


@pytest.mark.parametrize("env_value,expected", [(None, False), ("false", False), ("1", False),
    ("yes", False), ("", False), ("true", True), (" TRUE ", True)])
def test_actual_runtime_policy_wiring_default_off(canonical, tmp_path, monkeypatch, env_value, expected):
    # Call the real runtime factory with only root-cache/connect/config mocked.
    cache = tmp_path / ".runtime"
    cache.mkdir()
    (cache / "stock-universe.json").write_text(json.dumps({"members": {"FIX": {"company": "Fixture Corporation"}}}))
    cfg = dict(alert_min_relevance=.55, broad_alert_min_relevance=.70, scan_bridge_max_age=6)
    monkeypatch.setitem(sys.modules, "news_pipeline", SimpleNamespace(ROOT=tmp_path,
        SEC_MAP_CACHE=tmp_path / "absent-sec-cache", feed_settings=lambda: cfg,
        _float_env=lambda name, default, lo, hi: default,
        _int_env=lambda name, default, lo, hi: default))
    monkeypatch.setattr(canonical.runtime, "connect", canonical.connect)
    if env_value is None: monkeypatch.delenv("NEWS_EVENTS_MARKET_BRIEFS_ENABLED", raising=False)
    else: monkeypatch.setenv("NEWS_EVENTS_MARKET_BRIEFS_ENABLED", env_value)
    actual = canonical.real_pipeline()
    assert actual.policy.market_briefs_enabled is expected
    assert (actual.policy.personal_relevance, actual.policy.stock_relevance,
        actual.policy.market_relevance, actual.policy.max_age_hours) == (.55, .70, .30, 168)


def test_existing_medium_and_company_outputs_are_unchanged(monkeypatch):
    from news_events import runtime
    monkeypatch.setitem(sys.modules, "news_pipeline",
        SimpleNamespace(_publication_time_he=lambda value: "SYNTHETIC_TIME"))
    medium = result(materiality="medium")
    assert runtime.message(event(), medium, "market_news", []) == (
        "📰 " + medium["title_he"] + "\n\n" + medium["summary_he"] + "\n\nפורסם: SYNTHETIC_TIME")
    company = event()
    company.update(tickers=["FIX"], company_identity=[{"ticker": "FIX"}], event_type="earnings")
    policy = Policy(market_briefs_enabled=True)
    assert route(company, result(), {"FIX"}, set(), {"FIX": {}}, policy) == ([], "low_importance")
    assert route(company, medium, {"FIX"}, set(), {"FIX": {}}, policy) == ([("portfolio_watchlist", ["FIX"])], None)


@pytest.mark.parametrize("faithful", [True, False])
def test_existing_independent_review_and_two_or_four_call_budget_remain(canonical, faithful):
    from news_events.analysis import CanonicalAnalyzer
    review = dict(faithful=faithful, fluent_hebrew=True, unsupported_claims=False,
        duplicate_of=0, material_new_fact=False, explanation="בדיקת מקור סינתטי בלבד",
        scope_related=True)
    def response(stage, *args):
        return (result() if stage in ("source_analysis", "editorial_repair") else review), {}
    client = Mock(side_effect=response)
    eid = canonical.p.ingest(Source(**event()["sources"][0]), AT)
    outcome = canonical.p.analyze(eid, CanonicalAnalyzer(client), AT)
    assert outcome == ("done" if faithful else "failed")
    assert client.call_count == (2 if faithful else 4)
    assert [call.args[0] for call in client.call_args_list] == (
        ["source_analysis", "quality_review"] if faithful else
        ["source_analysis", "quality_review", "editorial_repair", "repair_review"])
    assert canonical.runtime.queue_outbox(canonical.p, eid, AT) == int(faithful)
    assert canonical.s.event(eid)["status"] == ("analyzed" if faithful else "quality_failed")


def test_actual_dispatch_factory_rereads_environment_for_pending_item(canonical, tmp_path, monkeypatch):
    _, row, _, _ = enqueue_brief(canonical)
    cache = tmp_path / ".runtime"
    cache.mkdir()
    (cache / "stock-universe.json").write_text(json.dumps({"members": {"FIX": {"company": "Fixture Corporation"}}}))
    cfg = dict(alert_min_relevance=.55, broad_alert_min_relevance=.70, scan_bridge_max_age=6)
    monkeypatch.setitem(sys.modules, "news_pipeline", SimpleNamespace(ROOT=tmp_path,
        SEC_MAP_CACHE=tmp_path / "absent-sec-cache", feed_settings=lambda: cfg,
        _float_env=lambda name, default, lo, hi: default,
        _int_env=lambda name, default, lo, hi: default,
        _publication_time_he=lambda value: "SYNTHETIC_TIME"))
    monkeypatch.setattr(canonical.runtime, "connect", canonical.connect)
    monkeypatch.setattr(canonical.runtime, "pipeline", canonical.real_pipeline)
    monkeypatch.setenv("NEWS_EVENTS_MARKET_BRIEFS_ENABLED", "true")
    assert "עדכון שוק קצר" in canonical.runtime.delivery_message(row)
    monkeypatch.setenv("NEWS_EVENTS_MARKET_BRIEFS_ENABLED", "false")
    assert canonical.runtime.delivery_message(row) is None
