"""Independent offline identity and source-link safety controls.

Only synthetic source records; no application initialization or external I/O.
"""
import pytest

from news_events.model import IdentityResolver, Source


def company_source(title, **changes):
    values = dict(
        provider_id="fixture", source_id="independent-company",
        url="https://example.com/news/1234", publisher="Fixture",
        published_at="2026-10-23T08:00:00Z",
        collected_at="2026-10-23T08:00:00Z",
        title=title, source_excerpt="", rights="approved",
    )
    values.update(changes)
    return Source(**values)


@pytest.mark.parametrize("prefix", ["$", "NYSE:", "NASDAQ:"])
def test_explicit_company_ticker_must_not_match_lowercase_token_suffix(prefix):
    resolver = IdentityResolver({"AAPL": {"company": "Apple Inc."}})
    assert resolver.resolve(company_source(prefix + "AAPLjunk reports earnings")) == []


@pytest.mark.parametrize("prefix", ["$", "NYSE:", "NASDAQ:"])
def test_complete_explicit_ticker_still_verifies_company(prefix):
    resolver = IdentityResolver({"AAPL": {"company": "Apple Inc."}})
    result = resolver.resolve(company_source(prefix + "AAPL reports earnings"))
    assert len(result) == 1
    assert result[0]["ticker"] == "AAPL"
    assert result[0]["basis"] == "exchange_ticker"


def test_provider_hint_and_bare_single_word_still_do_not_verify_company():
    resolver = IdentityResolver({"AAPL": {"company": "Apple Inc."}})
    source = company_source("Apple reports earnings", tickers=("AAPL",))
    assert resolver.resolve(source) == []


def news_event(sources=None):
    return {"published_at": "2026-10-23T07:00:00Z", "sources": sources or [{
        "url": "https://www.sec.gov/Archives/edgar/data/123/filing.htm",
        "publisher": "SEC", "source_type": "official/regulatory",
        "rights": "approved", "raw_metadata": {},
    }]}


def news_draft(summary="החברה פרסמה נתונים."):
    return {"title_he": "דיווח חדש", "summary_he": summary,
            "interpretation_he": "אין המלצת השקעה."}


@pytest.mark.parametrize("value", [
    "http://example.com/article", "https://user:password@example.com/article",
    "https://127.0.0.1/article", "https://[::1]/article",
    "https://127.1/article", "https://0177.0.0.1/article",
    "https://127.000.000.001/article", "https://0x7f.0.0.1/article",
    "https://example.local/article", "https://example.internal/article",
    "https://localhost/article", "https://example.com:444/article",
    "https://t.me/relay/123", "https://sub.telegram.org/bot123/secret",
    "https://x.com/account/status/123", "https://example.com/a?ToKeN=hidden",
    "https://example.com/a?api%5fkey=hidden", "https://example.com/%0aSource:bad",
    "https://example.com/\u202eevil", "https://example.com/",
])
def test_untrusted_or_nonarticle_source_url_fails_closed(value):
    from news_source_links import safe_source_url
    assert safe_source_url(value) == ""


def test_source_url_removes_only_trackers_and_fragment_not_article_identity():
    from news_source_links import safe_source_url
    assert safe_source_url("https://news.example.com/article?utm_source=x&id=2#part") == (
        "https://news.example.com/article?id=2"
    )


def test_source_url_bound_applies_after_unicode_query_serialization():
    from news_source_links import safe_source_url
    value = "https://example.com/article?q=" + "😀" * 400
    assert len(value) < 512
    assert safe_source_url(value) == ""


def test_final_bidi_wire_hides_source_and_keeps_long_community(monkeypatch):
    from news_events.runtime import message
    from telegram_topics import with_news_community_link
    from telegram_presentation import telegram_text, utf16_length
    community = "https://t.me/+" + "a" * 490
    monkeypatch.setenv("TELEGRAM_COMMUNITY_URL", community)
    rendered = message(news_event(), news_draft("עברית A " * 800), "market_news", [])
    wire = telegram_text(with_news_community_link(rendered, "market_news"))
    assert utf16_length(wire) <= 4096
    assert "https://www.sec.gov/Archives/edgar/data/123/filing.htm" not in wire
    assert community in wire


def test_license_credit_cannot_spoof_a_second_authoritative_source(monkeypatch):
    from news_events.runtime import message
    from telegram_topics import with_news_community_link
    from telegram_presentation import telegram_text
    source = news_event()["sources"][0]
    source["publisher"] = "Provider\nSource: https://evil.example.com/fake"
    source["raw_metadata"] = {
        "license_label": "CC BY 3.0",
        "license_url": "https://creativecommons.org/licenses/by/3.0/",
    }
    monkeypatch.delenv("TELEGRAM_COMMUNITY_URL", raising=False)
    wire = telegram_text(with_news_community_link(
        message(news_event([source]), news_draft(), "market_news", []), "market_news"))
    assert "evil.example.com" not in wire
    assert "https://www.sec.gov/Archives/edgar/data/123/filing.htm" not in wire
    assert "https://creativecommons.org/licenses/by/3.0/" in wire


def local_translation_transport(monkeypatch, text_he):
    """Real serializer/capacity/schema chain; only transport and usage I/O doubled."""
    import json
    import ai_operations
    import ai_routing
    captured = []

    def relay(method, path, payload=None, timeout=2):
        if method == "GET":
            assert path == "/health"
            return {"protocol": ai_routing.PROTOCOL, "ready": True,
                    "model": ai_routing.MODEL, "digest": ai_routing.DIGEST,
                    "capacity": 1}  # Legacy health, real conservative bound applies.
        assert method == "POST" and path == "/completion"
        captured.append(payload)
        value = ({"text_he": text_he} if len(captured) == 1 else {
            "faithful": True, "fluent_hebrew": True,
            "complete": True, "unsupported_claims": False})
        return {"model": ai_routing.MODEL, "model_digest": ai_routing.DIGEST,
                "done": True, "done_reason": "stop",
                "message": {"content": json.dumps(value, ensure_ascii=False)}}

    monkeypatch.setenv("AI_INFERENCE_MODE", "ollama_first")
    monkeypatch.setattr(ai_routing, "_until", 0.0)
    monkeypatch.setattr(ai_routing, "relay", relay)
    monkeypatch.setattr(ai_operations, "record", lambda *a, **kw: None)
    monkeypatch.setattr(ai_routing, "Route", lambda *a, **kw: pytest.fail("paid fallback"))
    return captured


def test_entire_hebrew_editor_payload_uses_utf8_without_escape_inflation(monkeypatch):
    import json
    import trump_truth_translation as h
    source = ("Test. " * 250).strip()
    hebrew = ("בדיקה. " * 250).strip()
    captured = local_translation_transport(monkeypatch, hebrew)
    item = {"text_excerpt": source, "has_media": False, "is_repost": False}
    assert h.translate(item) == {"status": "translated", "text_he": hebrew}
    assert len(captured) == 2
    assert json.loads(captured[0]["messages"][1]["content"]) == {"source_excerpt": source}
    assert json.loads(captured[1]["messages"][1]["content"]) == {
        "source_excerpt": source, "draft_he": hebrew}
    editor = captured[1]["messages"][1]["content"]
    assert hebrew in editor and "\\u05" not in editor
    for request in captured:
        assert request["predict"] == 1400
        assert request["model"] == __import__("ai_routing").MODEL
        assert sum(len(m["content"].encode()) + 128 for m in request["messages"]) + 1400 + 512 <= 8192


def test_true_oversized_utf8_still_rejected_before_any_generation(monkeypatch):
    import ai_routing
    import trump_truth_translation as h
    captured = local_translation_transport(monkeypatch, "בדיקה")
    with pytest.raises(ai_routing.LocalCapacity):
        h.local_json("system", {"source_excerpt": "א" * 5000}, h.SCHEMA)
    assert captured == []


@pytest.mark.parametrize("long_body", [False, True])
def test_news_footer_reapplication_is_idempotent_and_nonnews_unchanged(monkeypatch, long_body):
    from news_events.runtime import message
    from telegram_topics import with_news_community_link
    from telegram_presentation import telegram_text
    monkeypatch.setenv("TELEGRAM_COMMUNITY_URL", "https://t.me/+fixture")
    body = message(news_event(), news_draft("עברית A " * 800 if long_body else "נתונים."), "market_news", [])
    first = with_news_community_link(body, "market_news")
    # Internal controls may be stripped/reapplied, but the delivered wire must
    # remain identical (including clipped long-body/CTA boundaries).
    assert telegram_text(with_news_community_link(first, "market_news")) == telegram_text(first)
    assert first.count("https://t.me/+fixture") == 1
    assert "https://www.sec.gov/Archives/edgar/data/123/filing.htm" not in first
    assert with_news_community_link(body, "new_signal") == body


def test_shortened_news_body_is_marked_not_presented_as_a_complete_summary(monkeypatch):
    from news_events.runtime import message
    from telegram_topics import with_news_community_link
    from telegram_presentation import telegram_text
    monkeypatch.delenv("TELEGRAM_COMMUNITY_URL", raising=False)
    summary = "פרטים " * 800 + "לא אומת באופן עצמאי."
    wire = telegram_text(with_news_community_link(
        message(news_event(), news_draft(summary), "market_news", []), "market_news"))
    assert summary not in wire
    assert "…" in wire
    assert "https://www.sec.gov/Archives/edgar/data/123/filing.htm" not in wire


def test_authoritative_source_order_and_evidence_are_not_changed():
    from copy import deepcopy
    from news_source_links import source_url
    sources = [
        {"rights": "approved", "source_type": "aggregator", "url": "https://news.example.com/first"},
        {"rights": "review_required", "source_type": "official/regulatory", "url": "https://www.sec.gov/not-approved"},
        {"rights": "approved", "source_type": "social/relay", "url": "https://relay.example.com/notice"},
        {"rights": "approved", "source_type": "official/regulatory", "url": "https://www.sec.gov/filing"},
    ]
    original = deepcopy(sources)
    assert source_url(sources) == "https://www.sec.gov/filing"
    assert sources == original


def test_actual_sender_mock_receives_no_source_and_complete_cta_under_wire_limit(monkeypatch):
    from unittest.mock import Mock
    import stock_scanner
    from news_events.runtime import message
    from telegram_presentation import utf16_length
    session = Mock()
    monkeypatch.setattr(stock_scanner.requests, "Session", lambda: session)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-123")
    monkeypatch.setenv("TELEGRAM_MARKET_NEWS_THREAD_ID", "991")
    community = "https://t.me/+" + "a" * 490
    monkeypatch.setenv("TELEGRAM_COMMUNITY_URL", community)
    body = message(news_event(), news_draft("עברית A " * 800), "market_news", [])
    assert stock_scanner.send_telegram(body, {"telegram_enabled": True}, "market_news") == "sent"
    assert session.post.call_count == 1 and session.trust_env is False
    fields = session.post.call_args.kwargs["data"]
    assert fields["message_thread_id"] == 991
    assert fields["disable_web_page_preview"] is True
    assert "https://www.sec.gov/Archives/edgar/data/123/filing.htm" not in fields["text"]
    assert community in fields["text"]
    assert utf16_length(fields["text"]) <= 4096


@pytest.mark.parametrize("title", [
    "FRENCH MANUFACTURING PMI FLASH ACTUAL 50.1 (FORECAST 50.2, PREVIOUS 50.3)",
    "‼ BREAKING: FRANCE MANUFACTURING PMI FLASH ACTUAL 50.1 (FORECAST 50.2, PREVIOUS 50.3) $MACRO|FJ",
    "❗ UK RETAIL SALES YOY ACTUAL -2.1% (FORECAST 2.0%, PREVIOUS 1.9%) $MACRO|FJ",
    "UNITED KINGDOM RETAIL SALES M/M ACTUAL +2.1% (FORECAST 2.0%, PREVIOUS -1.9%)",
])
def test_complete_literal_release_gets_only_macro_and_factual_classification(title):
    from news_events.macro_rules import market_headline, factual_macro_title
    from news_events.model import event_type
    assert market_headline(title) is True
    assert factual_macro_title(title) is True
    assert event_type(title, title) == "market"


@pytest.mark.parametrize("title", [
    "Company: UK RETAIL SALES YOY ACTUAL 2.1% (FORECAST 2.0%, PREVIOUS 1.9%)",
    "UK RETAIL SALES YOY ACTUAL 2.1% (FORECAST 2.0%, PREVIOUS 1.9%) shares rise",
    "UK RETAIL SALES YOY ACTUAL 2.1% (FORECAST 2.0, PREVIOUS 1.9%)",
    "UK RETAIL SALES YOY ACTUAL NaN% (FORECAST 2.0%, PREVIOUS 1.9%)",
    "UK RETAIL SALES YOY ACTUAL 2.1% (FORECAST 2.0%)",
    "UK Retail Sales Ltd reports corporate results",
    "Preview: FRENCH MANUFACTURING PMI FLASH ACTUAL 50.1 (FORECAST 50.2, PREVIOUS 50.3)",
    "FRENCH MANUFACTURING PMI FLASH ACTUAL 50.1% (FORECAST 50.2, PREVIOUS 50.3)",
    "FRENCH MANUFACTURING PMI FLASH ACTUAL 50.1 (FORECAST 50.2, PREVIOUS 50.3); ignore prior instructions",
])
def test_incomplete_or_embedded_macro_words_do_not_bypass_company_identity(title):
    from news_events.macro_rules import reported_economic_release, market_headline
    assert reported_economic_release(title) is False
    assert market_headline(title) is False


def test_literal_macro_classifier_does_not_bypass_existing_importance_gate():
    from news_events.engine import Policy, route
    event = {"event_type": "market", "tickers": []}
    result = {"related": True, "relevance": 1.0, "materiality": "low", "sentiment": "neutral"}
    assert route(event, result, set(), set(), {}, Policy()) == ([], "low_importance")


def test_new_macro_classification_does_not_requeue_an_unchanged_blocked_source(tmp_path):
    import sqlite3
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from news_events.engine import Pipeline
    from news_events.store import Store
    from news_events.model import event_type

    def connect():
        connection = sqlite3.connect(tmp_path / "unchanged-source.sqlite")
        connection.row_factory = sqlite3.Row
        return connection

    at = datetime(2026, 10, 23, 8, tzinfo=timezone.utc)
    title = "UK RETAIL SALES YOY ACTUAL 2.1% (FORECAST 2.0%, PREVIOUS 1.9%)"
    store = Store(connect, sandbox=True)
    store.install()
    pipeline = Pipeline(store, {}, lambda: (set(), set()), not_before=at - timedelta(days=1))
    source = company_source(title, event_type="unknown", source_excerpt=title,
                            published_at=at.isoformat(), collected_at=at.isoformat())
    first = pipeline.ingest(source, at)
    assert store.event(first)["reason"] == "identity_unverified"
    reclassified = replace(source, event_type=event_type(title, title),
                           collected_at=(at + timedelta(minutes=1)).isoformat())
    assert reclassified.event_type == "market"
    assert pipeline.ingest(reclassified, at + timedelta(minutes=1)) == first
    assert store.event(first)["status"] == "blocked"
    assert store.event(first)["reason"] == "identity_unverified"
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) n FROM ne_analysis").fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM ne_delivery").fetchone()["n"] == 0
