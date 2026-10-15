"""Reported index/commodity headline coverage; isolated SQLite and mocked AI only."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_events.engine import Analysis, Pipeline
from news_events.factual_evidence import factual_title, sufficient
from news_events.macro_rules import factual_macro_title, market_headline, reported_market_movement
from news_events.model import Source, event_type
from news_events.store import Store


OBSERVED = [
    "Nasdaq nears one-month low as AI stocks slide on debt concerns",
    "Gold rebounds as yields dip, dollar softens despite hot U.S. inflation data",
]
REPORTED = OBSERVED + [
    "Nasdaq Composite rose 1.2% as yields retreated",
    "Nasdaq 100 slipped 2% yesterday",
    "S&P 500 gained 1.5% after the economic release",
    "Dow Jones fell 200 points amid higher bond yields",
    "Dow Jones Industrial Average closed lower",
    "FTSE 100 climbed 1% after the economic release",
    "DAX index traded lower",
    "Nikkei 225 gained 1%",
    "Hang Seng rallied 3%",
    "Russell 2000 declined 0.5%",
    "Stoxx 600 opened higher",
    "Gold rebounded 2% overnight",
    "Spot gold touched $2,000",
    "Silver prices fell 1%",
    "Copper prices rose above $4",
    "Brent crude rose above $84",
    "WTI crude oil dropped 2%",
    "Natural gas prices settled higher",
    "Gold neared a record high",
    "S&P 500 hits a record high",
    "Gold prices reached $2,000",
    "Nasdaq nears a two-week high",
]
NOT_REPORTED_MARKET_MOVE = [
    "Nasdaq Inc. rises 2%",
    "Nasdaq shares rise 2%",
    "Nasdaq stock gains after quarterly results",
    "Nasdaq rises after earnings beat",
    "Nasdaq fell after a merger announcement",
    "S&P Global gains 2%",
    "S&P Global reports quarterly results",
    "Gold Hart Copper acquires a mine",
    "Goldcorp shares rise 2%",
    "Gold rises after announcing a dividend",
    "Copper Corp. climbs 2%",
    "Example Mining says gold rises",
    "Nasdaq may rise 2%",
    "Nasdaq will fall 2%",
    "Nasdaq could rise 2%",
    "Nasdaq is projected to rise 2%",
    "Gold rises if yields fall",
    "Gold rises unless demand falls",
    "Gold rises to $3,000 tomorrow",
    "Gold hits 3000 tomorrow",
    "Gold reaches a record high tomorrow",
    "Nasdaq rises 2% next week",
    "Gold reaches $3,000 next year",
    "Gold hits 3000 tonight",
    "Gold hits 3000 by 2027",
    "Gold hits 2jobs",
    "Gold hits 3D printing milestone",
    "Gold reaches 2.0API milestone",
    "Gold hits 3-month growth target",
    "Gold rebounds: why it is the best investment",
    "Gold rises: sponsored investment guide",
    "Gold rebounds: subscribe for a secret trading strategy",
    "Gold price forecast rises to $3,000",
    "Could Nasdaq surge tomorrow?",
    "Nasdaq nears a breakout",
    "Gold gains momentum",
    "Gold opens a new mine",
    "Gold settles a lawsuit",
]


@pytest.fixture(autouse=True)
def deny_external_work(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("Movement fixture forbids external work")
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)


@pytest.mark.parametrize("title", REPORTED)
def test_shared_reported_move_classifies_and_supplies_only_original_title(title):
    assert reported_market_movement(title)
    assert market_headline(title)
    assert factual_macro_title(title)
    assert event_type(title, "") == "market"


@pytest.mark.parametrize("title", NOT_REPORTED_MARKET_MOVE)
def test_new_rule_never_admits_company_forecast_promotion_or_partial_measurement(title):
    # Existing unrelated legacy macro patterns are not replaced by this rule.
    assert not reported_market_movement(title)
    assert not market_headline(title)
    assert not factual_macro_title(title)


@pytest.fixture
def isolated_pipeline(tmp_path):
    path = tmp_path / "movement-only.sqlite"
    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    store = Store(connect, sandbox=True)
    store.install()
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    pipeline = Pipeline(store, {}, lambda: [set(), set()], not_before=now - timedelta(days=2))
    return pipeline, store, now


def item(title, now, **changes):
    return replace(Source(
        "synthetic_primary", "movement", "https://example.invalid/news/movement",
        "Synthetic primary", now.isoformat(), now.isoformat(), title, "",
        event_type=event_type(title, ""), rights="approved"), **changes)


def analyzer(related=True, relevance=.4):
    return Mock(return_value=Analysis(dict(
        related=related, title_he="התקבל דיווח על תנועת השוק",
        summary_he="המקור דיווח על תנועה בשוק.",
        interpretation_he="זהו דיווח מקור ולא המלצת מסחר.",
        sentiment="neutral", materiality="low", relevance=relevance)))


@pytest.mark.parametrize("title", OBSERVED)
def test_pipeline_title_only_reaches_existing_analysis_then_deduplicates(isolated_pipeline, title):
    pipeline, store, now = isolated_pipeline
    source = item(title, now)
    eid = pipeline.ingest(source, now)
    event = store.event(eid)
    assert event["status"] == "pending"
    assert factual_title(event["body"]) and sufficient(event["body"])
    ai = analyzer()
    assert pipeline.analyze(eid, ai, now) == "done"
    assert pipeline.deliver_preview(eid, now)[0]["topic"] == "market_news"
    received = ai.call_args.args[0]
    assert received["title"] == title
    assert received["sources"][0]["source_excerpt"] == ""
    assert received["sources"][0]["title"] == title
    assert pipeline.ingest(source, now + timedelta(seconds=1)) == eid
    restarted = Pipeline(Store(store.connect, sandbox=True), {}, pipeline.membership,
                         not_before=pipeline.not_before)
    assert restarted.analyze(eid, ai, now + timedelta(seconds=1)) == "done"
    assert restarted.deliver_preview(eid, now + timedelta(seconds=1)) == []
    ai.assert_called_once()


@pytest.mark.parametrize("rights", ["review_required", "internal_review"])
def test_title_only_keeps_rights_gate(isolated_pipeline, rights):
    pipeline, store, now = isolated_pipeline
    eid = pipeline.ingest(item(OBSERVED[0], now, rights=rights), now)
    assert not sufficient(store.event(eid)["body"])
    ai = Mock()
    assert pipeline.analyze(eid, ai, now) == "insufficient_information"
    ai.assert_not_called()


def test_existing_market_age_gate_prevents_stale_analysis(isolated_pipeline):
    pipeline, _, now = isolated_pipeline
    source = item(OBSERVED[0], now, published_at=(now - timedelta(hours=7)).isoformat())
    eid = pipeline.ingest(source, now)
    ai = Mock()
    assert pipeline.analyze(eid, ai, now) == "stale_or_future"
    ai.assert_not_called()


@pytest.mark.parametrize("related,relevance", [(False, .9), (True, .29)])
def test_factual_title_never_overrides_downstream_related_or_relevance(isolated_pipeline, related, relevance):
    pipeline, _, now = isolated_pipeline
    eid = pipeline.ingest(item(OBSERVED[1], now), now)
    ai = analyzer(related, relevance)
    assert pipeline.analyze(eid, ai, now) == "done"
    assert pipeline.queue(eid, now) == []


def test_corporate_classification_is_not_replaced_by_commodity_word():
    assert event_type("Gold Hart Copper acquires a mine", "") == "merger"
    assert event_type("Nasdaq Inc. reports quarterly earnings", "") == "earnings"
    assert event_type("S&P Global appoints a new CEO", "") == "management"
