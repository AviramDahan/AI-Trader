import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database
import news_pipeline
import scanner_engine


UTC = timezone.utc


class NewsPipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_path = database._SQLITE_DB_PATH
        database._SQLITE_DB_PATH = str(Path(self.directory.name) / "news.db")
        database.init_database()
        conn = database.get_db_connection()
        conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','test-token',100000)")
        conn.commit(); conn.close()
        with patch.dict(os.environ, {"STOCK_SCANNER_EXIT_STRATEGY": "single"}, clear=False):
            scanner_engine.initialize_runtime()
        self.clock = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

    def tearDown(self):
        database._SQLITE_DB_PATH = self.original_path
        self.directory.cleanup()

    def rows(self, sql, params=()):
        conn = database.get_db_connection()
        values = [dict(row) for row in conn.execute(sql, params).fetchall()]
        conn.close()
        return values

    def item(self, provider="federal_reserve", url="https://example.test/release", ticker=None):
        return {"provider": provider, "publisher": "Original Publisher", "title": "Company reports material update",
                "url": url, "published_at": self.clock.isoformat(), "source_excerpt": "Published source metadata.",
                "tickers": [ticker] if ticker else [], "scope": "universe" if ticker else "market",
                "source_kind": "headline_summary", "headline_only": True}

    def open_trade(self):
        signal = {"signal_id": 1, "ticker": "AAPL", "company": "Apple", "action": "BUY", "entry": 100,
                  "stop_loss": 97, "confidence": .9, "time_horizon": "1-4 weeks", "reason": "Verified thesis.",
                  "telegram_reason_he": "תזה מאומתת.", "relevant_news": [], "telegram_news_he": []}
        candidate = {"ticker": "AAPL", "company": "Apple", "technical_score": 7, "combined_rank_score": .9}
        with patch.object(scanner_engine, "now_z", return_value=(self.clock - timedelta(minutes=5)).isoformat()):
            scanner_engine.record_signal(signal, candidate, {"news_relevance": .9, "news_sentiment": .5}, {}, "scan")
        scanner_engine.process_bar("AAPL", {"at": self.clock.isoformat().replace("+00:00", "Z"),
                                              "open": 100, "high": 101, "low": 99, "close": 100})

    def test_periodic_collection_deduplicates_cross_provider_and_preserves_sources(self):
        def first(state, at):
            return {"items": [self.item()], "coverage": "fake shared feed", "checkpoint": {"cursor": "one"}}

        result = news_pipeline.run_feed_cycle({"federal_reserve": first}, self.clock, force=True)
        self.assertEqual(result["items_inserted"], 1)
        second_item = self.item("bls", "https://second.example.test/release")
        news_pipeline.ingest_items([second_item], self.clock + timedelta(minutes=1))
        self.assertEqual(len(self.rows("SELECT * FROM scanner_news")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_news_sources")), 2)
        row = self.rows("SELECT * FROM scanner_news")[0]
        self.assertEqual(row["analysis_status"], "pending_analysis")
        self.assertIn("headline_and_feed_summary", row["source_facts_json"])

    def test_provider_cadence_rate_limit_backoff_and_recovery(self):
        calls = []

        def limited(state, at):
            calls.append(at)
            if len(calls) == 1:
                raise news_pipeline.ProviderRateLimited("limited", 600)
            return {"items": [], "coverage": "recovered"}

        first = news_pipeline.run_feed_cycle({"federal_reserve": limited}, self.clock, force=True)
        self.assertEqual(first["errors"], ["federal_reserve:rate_limited"])
        self.assertEqual(self.rows("SELECT status FROM scanner_news_providers WHERE provider='federal_reserve'")[0]["status"], "rate_limited")
        skipped = news_pipeline.run_feed_cycle({"federal_reserve": limited}, self.clock + timedelta(minutes=5))
        self.assertEqual(skipped["providers_checked"], 0)
        recovered = news_pipeline.run_feed_cycle({"federal_reserve": limited}, self.clock + timedelta(minutes=11))
        self.assertFalse(recovered["errors"])
        self.assertEqual(self.rows("SELECT status FROM scanner_news_providers WHERE provider='federal_reserve'")[0]["status"], "ok")

    def test_changed_source_version_requeues_once_without_losing_other_sources(self):
        first = self.item()
        news_pipeline.ingest_items([first], self.clock)
        news_pipeline.analyze_news_jobs(
            analyzer=lambda rows: [{"id": rows[0]["id"], "related": True, "summary_he": "תקציר.",
                                    "sentiment": "neutral", "materiality": "low",
                                    "thesis_effect": "unchanged", "interpretation_he": "לא ברור.",
                                    "relevance": .5}], at=self.clock)
        updated = {**first, "title": "Company reports a revised material update",
                   "source_excerpt": "Revised published metadata."}
        news_pipeline.ingest_items([updated], self.clock + timedelta(minutes=5))
        self.assertEqual(len(self.rows("SELECT * FROM scanner_news")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_news_sources")), 1)
        self.assertEqual(self.rows("SELECT status FROM scanner_news_jobs")[0]["status"], "pending")
        news_pipeline.ingest_items([updated], self.clock + timedelta(minutes=6))
        self.assertEqual(len(self.rows("SELECT * FROM scanner_news_sources")), 1)

    def test_old_archive_item_is_not_queued_as_fresh_news(self):
        old = {**self.item(), "published_at": (self.clock - timedelta(days=10)).isoformat()}
        result = news_pipeline.ingest_items([old], self.clock)
        self.assertEqual(result["inserted"], 0)
        self.assertFalse(self.rows("SELECT * FROM scanner_news_jobs"))

    def test_material_open_position_news_is_immediate_deduped_and_never_mutates_trade(self):
        self.open_trade()
        before = self.rows("SELECT remaining_quantity,current_stop FROM scanner_trades WHERE is_shadow=0")[0]
        news_pipeline.ingest_items([self.item("yahoo_priority", "https://example.test/aapl", "AAPL")], self.clock)

        def analyzer(rows):
            return [{"id": rows[0]["id"], "related": True, "summary_he": "החברה פרסמה עדכון מהותי.",
                     "sentiment": "positive", "materiality": "high", "thesis_effect": "supports",
                     "interpretation_he": "פרשנות AI זהירה: העדכון עשוי לתמוך בתזה, אך קיימת אי־ודאות.",
                     "relevance": .98}]

        first = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
        second = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock + timedelta(minutes=1))
        after = self.rows("SELECT remaining_quantity,current_stop FROM scanner_trades WHERE is_shadow=0")[0]
        self.assertEqual(first["alerts"], 1)
        self.assertEqual(second["alerts"], 0)
        self.assertEqual(before, after)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_trade_news")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='position_news'")), 1)

    def test_watchlist_collects_and_alerts_without_signal_or_position(self):
        scanner_engine.set_news_watchlist("NVDA", "NVIDIA")
        selected, _, coverage = news_pipeline._priority_tickers(20, {})
        self.assertIn(("NVDA", "NVIDIA"), selected)
        self.assertIn("1 watchlist", coverage)
        news_pipeline.ingest_items([self.item("yahoo_priority", "https://example.test/nvda", "NVDA")], self.clock)
        self.assertEqual(self.rows("SELECT scope FROM scanner_news")[0]["scope"], "watchlist")
        self.assertEqual(self.rows("SELECT priority FROM scanner_news_jobs")[0]["priority"], 80)

        def analyzer(rows):
            return [{"id": rows[0]["id"], "related": True, "title_he": "עדכון מהותי",
                     "summary_he": "החברה פרסמה עדכון מהותי.", "sentiment": "positive",
                     "materiality": "high", "thesis_effect": "unchanged",
                     "interpretation_he": "עשויה להיות השפעה חיובית, אך קיימת אי־ודאות.", "relevance": .98}]

        first = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
        second = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock + timedelta(minutes=1))
        self.assertEqual(first["alerts"], 1)
        self.assertEqual(second["alerts"], 0)
        self.assertFalse(self.rows("SELECT * FROM scanner_signals"))
        self.assertFalse(self.rows("SELECT * FROM scanner_trades"))
        alerts = self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='watchlist_news'")
        self.assertEqual(len(alerts), 1)
        self.assertIn("ללא עסקה", alerts[0]["message"])

    def test_multi_ticker_news_alerts_position_and_other_watchlist_without_duplicates(self):
        self.open_trade()
        scanner_engine.set_news_watchlist("NVDA", "NVIDIA")
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_news_watchlist SET created_at=? WHERE ticker='NVDA'",
                     ((self.clock - timedelta(minutes=1)).isoformat(),))
        conn.commit(); conn.close()
        item = self.item("yahoo_priority", "https://example.test/aapl-nvda")
        item["tickers"] = ["AAPL", "NVDA"]
        news_pipeline.ingest_items([item], self.clock)

        def analyzer(rows):
            return [{"id": rows[0]["id"], "related": True, "title_he": "עדכון משותף",
                     "summary_he": "עדכון מהותי לשתי החברות.", "sentiment": "positive",
                     "materiality": "high", "thesis_effect": "supports",
                     "interpretation_he": "עשויה להיות השפעה חיובית, אך קיימת אי־ודאות.", "relevance": .98}]

        first = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
        second = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock + timedelta(minutes=1))
        self.assertEqual(first["alerts"], 2)
        self.assertEqual(second["alerts"], 0)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='position_news'")), 1)
        watched = self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='watchlist_news'")
        self.assertEqual(len(watched), 1)
        self.assertIn("NVDA", watched[0]["message"])

    def test_distinct_high_quality_stock_news_all_alert_without_position_or_watchlist(self):
        news_pipeline.ingest_items([self.item("yahoo_priority", "https://example.test/nvda-broad", "NVDA")], self.clock)

        def analyzer(rows):
            return [{"id": row["id"], "related": True, "title_he": "עדכון מהותי",
                     "summary_he": "עדכון חשוב למניה.", "sentiment": "positive",
                     "materiality": "high", "thesis_effect": "unchanged",
                     "interpretation_he": "ייתכן אפקט חיובי, אך קיימת אי־ודאות.", "relevance": .95}
                    for row in rows]

        with patch.dict(os.environ, {
            "STOCK_SCANNER_TELEGRAM_BROAD_NEWS_MIN_RELEVANCE": ".80",
        }, clear=False):
            first = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
            later = {**self.item("yahoo_priority", "https://example.test/nvda-broad-2", "NVDA"),
                     "title": "A second material NVDA update"}
            news_pipeline.ingest_items([later], self.clock + timedelta(hours=1))
            second = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock + timedelta(hours=1))
        self.assertEqual(first["alerts"], 1)
        self.assertEqual(second["alerts"], 1)
        alerts = self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='stock_news'")
        self.assertEqual(len(alerts), 2)
        self.assertIn("NVDA", alerts[0]["message"])
        self.assertIn("אינה סיגנל", alerts[0]["message"])

    def test_broad_stock_news_requires_high_materiality_and_strict_relevance(self):
        items = []
        for index, ticker in enumerate(("NVDA", "AMD"), 1):
            item = self.item("yahoo_priority", f"https://example.test/weak-{index}", ticker)
            item["title"] = f"Candidate update {index}"
            items.append(item)
        news_pipeline.ingest_items(items, self.clock)

        def analyzer(rows):
            output = []
            for index, row in enumerate(rows):
                output.append({"id": row["id"], "related": True, "summary_he": "עדכון.",
                               "sentiment": "positive", "materiality": "medium" if index == 0 else "high",
                               "thesis_effect": "unchanged", "interpretation_he": "לא ברור.",
                               "relevance": .95 if index == 0 else .70})
            return output

        news_pipeline.analyze_news_jobs(limit=10, analyzer=analyzer, at=self.clock)
        self.assertFalse(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='stock_news'"))

    def test_broad_stock_news_requires_strict_provider_verified_ticker(self):
        conn = database.get_db_connection()
        conn.execute("""INSERT INTO scanner_news(
            fingerprint,ticker,scope,title,publisher,url,published_at,analysis_status,fetched_at,
            verified_tickers_json,content_hash,provider,updated_at)
            VALUES('unverified-nvda','NVDA','universe','Unverified ticker claim','Publisher',
                   'https://example.test/unverified',?,'pending_analysis',?,'[]','v1','legacy',?)""",
                     (self.clock.isoformat(), self.clock.isoformat(), self.clock.isoformat()))
        news_id = conn.execute("SELECT id FROM scanner_news WHERE fingerprint='unverified-nvda'").fetchone()[0]
        conn.execute("""INSERT INTO scanner_news_jobs(news_id,priority,status,next_attempt_at,created_at,updated_at)
                      VALUES(?,70,'pending',?,?,?)""", (news_id, self.clock.isoformat(), self.clock.isoformat(), self.clock.isoformat()))
        conn.commit(); conn.close()
        result = news_pipeline.analyze_news_jobs(analyzer=lambda rows: [{
            "id": rows[0]["id"], "related": True, "summary_he": "טענה לא מאומתת.",
            "sentiment": "positive", "materiality": "high", "thesis_effect": "unchanged",
            "interpretation_he": "אין אימות טיקר.", "relevance": .99,
        }], at=self.clock)
        self.assertEqual(result["alerts"], 0)
        self.assertFalse(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='stock_news'"))

    def test_broad_news_relevance_floor_cannot_be_lowered_below_eighty_percent(self):
        with patch.dict(os.environ, {"STOCK_SCANNER_TELEGRAM_BROAD_NEWS_MIN_RELEVANCE": ".65"}, clear=False):
            self.assertEqual(news_pipeline.feed_settings()["broad_alert_min_relevance"], .80)

    def test_all_distinct_official_high_quality_market_news_alert(self):
        items = []
        for index in range(3):
            item = self.item("federal_reserve", f"https://example.test/fed-{index}")
            item["title"] = f"Federal Reserve material release {index}"
            items.append(item)
        news_pipeline.ingest_items(items, self.clock)

        def analyzer(rows):
            return [{"id": row["id"], "related": True, "title_he": "עדכון מאקרו",
                     "summary_he": "הפדרל ריזרב פרסם עדכון.", "sentiment": "mixed",
                     "materiality": "high", "thesis_effect": "unchanged",
                     "interpretation_he": "עשויה להיות השפעה רחבה, אך קיימת אי־ודאות.", "relevance": .95}
                    for row in rows]

        result = news_pipeline.analyze_news_jobs(limit=10, analyzer=analyzer, at=self.clock)
        self.assertEqual(result["alerts"], 3)
        alerts = self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='market_news'")
        self.assertEqual(len(alerts), 3)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_news_broadcast_alerts WHERE channel='market'")), 3)

    def test_legacy_translated_item_is_fully_analyzed_after_verified_watchlist_upgrade(self):
        scanner_engine.set_news_watchlist("INTC", "Intel")
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_news_watchlist SET created_at=? WHERE ticker='INTC'",
                     ((self.clock - timedelta(minutes=1)).isoformat(),))
        conn.execute("""INSERT INTO scanner_news(
            fingerprint,ticker,scope,title,publisher,url,published_at,analysis_status,fetched_at,
            verified_tickers_json,content_hash,updated_at)
            VALUES('legacy-intc','INTC','watchlist','Intel announces verified update','Publisher',
                   'https://example.test/intc',?,'translated',?,'[\"INTC\"]','v1',?)""",
                     (self.clock.isoformat(), self.clock.isoformat(), self.clock.isoformat()))
        conn.commit(); conn.close()

        def analyzer(rows):
            self.assertEqual(len(rows), 1)
            return [{"id": rows[0]["id"], "related": True, "title_he": "עדכון מאינטל",
                     "summary_he": "אינטל פרסמה עדכון מאומת.", "sentiment": "positive",
                     "materiality": "high", "thesis_effect": "unchanged",
                     "interpretation_he": "עשויה להיות השפעה חיובית, אך קיימת אי־ודאות.",
                     "relevance": .95}]

        first = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
        second = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock + timedelta(minutes=1))
        self.assertEqual(first["alerts"], 1)
        self.assertEqual(second["alerts"], 0)
        self.assertEqual(self.rows("SELECT analysis_status FROM scanner_news")[0]["analysis_status"], "analyzed")
        alerts = self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='watchlist_news'")
        self.assertEqual(len(alerts), 1)
        self.assertIn("INTC", alerts[0]["message"])

    def test_verified_tickers_override_wrong_legacy_ticker_and_low_relevance_never_alerts(self):
        scanner_engine.set_news_watchlist("INTC", "Intel")
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_news_watchlist SET created_at=? WHERE ticker='INTC'",
                     ((self.clock - timedelta(minutes=1)).isoformat(),))
        conn.execute("""INSERT INTO scanner_news(
            fingerprint,ticker,scope,title,publisher,url,published_at,analysis_status,fetched_at,
            verified_tickers_json,content_hash,updated_at)
            VALUES('wrong-legacy-ticker','INTC','watchlist','AMD-only verified update','Publisher',
                   'https://example.test/amd-only',?,'pending_analysis',?,'[\"AMD\"]','v1',?)""",
                     (self.clock.isoformat(), self.clock.isoformat(), self.clock.isoformat()))
        news_id = conn.execute("SELECT id FROM scanner_news WHERE fingerprint='wrong-legacy-ticker'").fetchone()[0]
        conn.execute("""INSERT INTO scanner_news_jobs(news_id,priority,status,next_attempt_at,created_at,updated_at)
                      VALUES(?,80,'pending',?,?,?)""", (news_id, self.clock.isoformat(), self.clock.isoformat(), self.clock.isoformat()))
        conn.commit(); conn.close()
        result = news_pipeline.analyze_news_jobs(analyzer=lambda rows: [{
            "id": rows[0]["id"], "related": True, "title_he": "עדכון AMD",
            "summary_he": "המידע אומת עבור AMD בלבד.", "sentiment": "positive",
            "materiality": "high", "thesis_effect": "unchanged",
            "interpretation_he": "אין שיוך מאומת ל־INTC.", "relevance": .3,
        }], at=self.clock)
        self.assertEqual(result["alerts"], 0)
        self.assertFalse(self.rows("SELECT * FROM scanner_news_watchlist_alerts"))
        self.assertFalse(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='watchlist_news'"))

    def test_legacy_priority_backfill_requires_a_live_relationship(self):
        conn = database.get_db_connection()
        for index, scope in enumerate(("open_position", "active_signal"), 1):
            conn.execute("""INSERT INTO scanner_news(
                fingerprint,ticker,scope,title,publisher,url,published_at,analysis_status,fetched_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                         (f"orphan-{index}", "INTC", scope, "Orphan legacy item", "Publisher",
                          f"https://example.test/orphan-{index}", self.clock.isoformat(), "translated",
                          self.clock.isoformat(), self.clock.isoformat()))
        conn.commit(); conn.close()
        called = False

        def analyzer(_rows):
            nonlocal called
            called = True
            return []

        result = news_pipeline.analyze_news_jobs(analyzer=analyzer, at=self.clock)
        self.assertFalse(called)
        self.assertEqual(result["analyzed"], 0)
        self.assertFalse(self.rows("SELECT * FROM scanner_news_jobs"))
        self.assertEqual({row["analysis_status"] for row in self.rows("SELECT analysis_status FROM scanner_news")},
                         {"translated"})

    def test_watchlist_does_not_duplicate_open_position_alert(self):
        scanner_engine.set_news_watchlist("AAPL", "Apple")
        self.open_trade()
        news_pipeline.ingest_items([self.item("yahoo_priority", "https://example.test/aapl-watched", "AAPL")], self.clock)
        result = news_pipeline.analyze_news_jobs(analyzer=lambda rows: [{"id": rows[0]["id"], "related": True,
            "summary_he": "עדכון.", "sentiment": "negative", "materiality": "medium",
            "thesis_effect": "weakens", "interpretation_he": "ייתכן סיכון.", "relevance": .9}], at=self.clock)
        self.assertEqual(result["alerts"], 1)
        self.assertEqual(len(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='position_news'")), 1)
        self.assertFalse(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='watchlist_news'"))

    def test_watchlist_remove_stops_collection_and_alerting(self):
        scanner_engine.set_news_watchlist("NVDA", "NVIDIA")
        scanner_engine.set_news_watchlist("NVDA", enabled=False)
        selected, _, _ = news_pipeline._priority_tickers(20, {})
        self.assertNotIn(("NVDA", "NVIDIA"), selected)
        dashboard = scanner_engine.dashboard_payload()
        self.assertFalse(dashboard["news_watchlist"])

    def test_closed_position_does_not_receive_new_dedicated_news_alert(self):
        self.open_trade()
        trade = self.rows("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.process_bar("AAPL", {"at": (self.clock + timedelta(minutes=5)).isoformat(),
                                              "open": trade["current_stop"] - 1,
                                              "high": trade["current_stop"] - .5,
                                              "low": trade["current_stop"] - 2,
                                              "close": trade["current_stop"] - 1})
        self.assertEqual(self.rows("SELECT status FROM scanner_news_schedule WHERE ticker='AAPL'")[0]["status"], "closed")
        item = {**self.item("yahoo_priority", "https://example.test/later", "AAPL"),
                "published_at": (self.clock + timedelta(minutes=10)).isoformat()}
        news_pipeline.ingest_items([item], self.clock + timedelta(minutes=10))
        self.assertFalse(self.rows("SELECT * FROM scanner_trade_news"))
        result = news_pipeline.analyze_news_jobs(
            analyzer=lambda rows: [{"id": rows[0]["id"], "related": True, "title_he": "עדכון",
                                    "summary_he": "פורסם עדכון מהותי.", "sentiment": "negative",
                                    "materiality": "high", "thesis_effect": "weakens",
                                    "interpretation_he": "השפעה אפשרית שלילית.", "relevance": .9}],
            at=self.clock + timedelta(minutes=10))
        # Closing the trade stops dedicated position alerts. The same verified,
        # high-quality item may still qualify for the independent stock-news topic.
        self.assertEqual(result["alerts"], 1)
        self.assertFalse(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='position_news'"))
        self.assertEqual(len(self.rows("SELECT * FROM scanner_telegram_outbox WHERE event_type='stock_news'")), 1)

    def test_six_hour_review_reuses_cache_and_partial_position_remains_scheduled(self):
        self.open_trade()
        trade = self.rows("SELECT * FROM scanner_trades WHERE is_shadow=0")[0]
        scanner_engine.set_active_strategy("staged")  # current trade snapshot remains single
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_news_schedule SET next_due_at=? WHERE ticker='AAPL'", (self.clock.isoformat(),))
        conn.commit(); conn.close()
        fake = {"items": [], "coverage": "open ticker checked", "checkpoint": {"candidate_offset": 0}}
        with patch.object(news_pipeline, "_fetch_yahoo_priority", return_value=fake):
            result = news_pipeline.run_position_summary_cycle(self.clock)
        self.assertEqual(result["checked"], 1)
        schedule = self.rows("SELECT * FROM scanner_news_schedule WHERE ticker='AAPL'")[0]
        self.assertEqual(schedule["status"], "no_new")
        self.assertGreater(news_pipeline._parse_time(schedule["next_due_at"]), self.clock + timedelta(hours=5, minutes=59))
        self.assertEqual(self.rows("SELECT strategy FROM scanner_trades WHERE id=?", (trade["id"],))[0]["strategy"], "single")

    def test_six_hour_review_preserves_last_success_during_provider_backoff(self):
        self.open_trade()
        conn = database.get_db_connection()
        conn.execute("UPDATE scanner_news_schedule SET next_due_at=?,last_success_at=? WHERE ticker='AAPL'",
                     (self.clock.isoformat(), (self.clock - timedelta(hours=6)).isoformat()))
        conn.execute("UPDATE scanner_news_providers SET status='rate_limited',next_check_at=? WHERE provider='yahoo_priority'",
                     ((self.clock + timedelta(hours=1)).isoformat(),))
        conn.commit(); conn.close()
        with patch.object(news_pipeline, "_fetch_yahoo_priority") as fetch:
            result = news_pipeline.run_position_summary_cycle(self.clock)
        fetch.assert_not_called()
        self.assertTrue(result["errors"])
        schedule = self.rows("SELECT * FROM scanner_news_schedule WHERE ticker='AAPL'")[0]
        self.assertEqual(schedule["status"], "error")
        self.assertEqual(news_pipeline._parse_time(schedule["last_success_at"]), self.clock - timedelta(hours=6))

    def test_provider_failure_is_not_no_news_and_collection_never_calls_price_monitor(self):
        def failed(state, at):
            raise RuntimeError("provider unavailable")

        with patch.object(scanner_engine, "monitor_prices") as prices:
            result = news_pipeline.run_feed_cycle({"federal_reserve": failed}, self.clock, force=True)
        prices.assert_not_called()
        self.assertTrue(result["errors"])
        provider = self.rows("SELECT * FROM scanner_news_providers WHERE provider='federal_reserve'")[0]
        self.assertEqual(provider["status"], "error")
        self.assertNotEqual(provider["status"], "no_new")

    def test_rss_parser_records_original_publication_and_headline_only_scope(self):
        xml = b"""<rss><channel><item><title>Official release</title><link>https://official.test/item?utm_source=x</link>
        <pubDate>Mon, 14 Sep 2026 12:00:00 GMT</pubDate><description>Official summary</description></item></channel></rss>"""
        rows = news_pipeline._rss_items(xml, "official", "Official Publisher", "market")
        self.assertEqual(rows[0]["url"], "https://official.test/item")
        self.assertEqual(rows[0]["publisher"], "Official Publisher")
        self.assertTrue(rows[0]["headline_only"])
        self.assertEqual(news_pipeline._parse_time(rows[0]["published_at"]), self.clock)

    def test_atom_uses_original_published_time_and_skips_missing_timestamp(self):
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>Old official release</title><link href="https://official.test/old"/>
        <published>2026-09-04T07:51:08.21-04:00</published><updated>2026-09-17T12:00:00Z</updated>
        <content>Official release excerpt.</content></entry>
        <entry><title>Undated item</title><link href="https://official.test/unknown"/></entry></feed>"""
        rows = news_pipeline._rss_items(atom, "bls", "BLS", "market")
        self.assertEqual(len(rows), 1)
        self.assertEqual(news_pipeline._parse_time(rows[0]["published_at"]),
                         datetime(2026, 9, 4, 11, 51, 8, 210000, tzinfo=UTC))
        self.assertEqual(news_pipeline.ingest_items(rows, self.clock)["inserted"], 0)

    def test_corrected_official_date_marks_previously_misdated_archive_stale(self):
        wrong = {**self.item("bls", "https://official.test/old"),
                 "published_at": self.clock.isoformat()}
        news_pipeline.ingest_items([wrong], self.clock)
        corrected = {**wrong, "published_at": (self.clock - timedelta(days=10)).isoformat()}
        changed = news_pipeline._reconcile_source_publication_times("bls", [corrected], self.clock)
        self.assertEqual(changed, 1)
        row = self.rows("SELECT * FROM scanner_news")[0]
        self.assertEqual(row["analysis_status"], "stale_skipped")
        self.assertEqual(self.rows("SELECT status FROM scanner_news_jobs")[0]["status"], "stale_skipped")

    def test_malformed_ai_batch_retries_without_publishing_or_losing_news(self):
        news_pipeline.ingest_items([self.item()], self.clock)

        def malformed(_rows):
            raise json.JSONDecodeError("truncated response", "{", 1)

        failed = news_pipeline.analyze_news_jobs(analyzer=malformed, at=self.clock)
        self.assertEqual(failed["analyzed"], 0)
        self.assertEqual(failed["alerts"], 0)
        self.assertEqual(self.rows("SELECT status FROM scanner_news_jobs")[0]["status"], "retry")
        self.assertEqual(self.rows("SELECT analysis_status FROM scanner_news")[0]["analysis_status"], "analysis_error")

        recovered = news_pipeline.analyze_news_jobs(
            analyzer=lambda rows: [{"id": rows[0]["id"], "related": True, "title_he": "עדכון",
                                    "summary_he": "תקציר זהיר.", "sentiment": "neutral",
                                    "materiality": "low", "thesis_effect": "unchanged",
                                    "interpretation_he": "השפעה לא ברורה.", "relevance": .5}],
            at=self.clock + timedelta(minutes=2))
        self.assertEqual(recovered["analyzed"], 1)
        self.assertEqual(self.rows("SELECT status FROM scanner_news_jobs")[0]["status"], "done")

    def test_legacy_headline_translation_uses_small_ollama_batches(self):
        conn = database.get_db_connection()
        for index in range(7):
            conn.execute("""INSERT INTO scanner_news(fingerprint,scope,title,publisher,url,published_at,
                            analysis_status,fetched_at) VALUES(?,?,?,?,?,?,?,?)""",
                         (f"legacy-{index}", "market", f"Headline {index}", "Market feed",
                          f"https://example.test/{index}", self.clock.isoformat(),
                          "pending_translation", self.clock.isoformat()))
        conn.commit(); conn.close()
        batch_sizes = []

        def translate(_system, rows, _predict):
            batch_sizes.append(len(rows))
            return {"items": [{"id": row["id"], "summary_he": "כותרת בעברית"} for row in rows]}

        with patch.object(scanner_engine, "_ollama_json", side_effect=translate):
            self.assertEqual(scanner_engine.translate_pending_news(), 5)
            self.assertEqual(scanner_engine.translate_pending_news(), 2)
        self.assertEqual(batch_sizes, [5, 2])
        self.assertEqual(len(self.rows("SELECT id FROM scanner_news WHERE analysis_status='translated'")), 7)


if __name__ == "__main__":
    unittest.main()
