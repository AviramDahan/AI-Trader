"""Regression cases from a bounded Telegram review, with synthetic inputs."""
from datetime import timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_public_news_translation_only import isolated_pipeline


def test_forecast_with_quarter_metric_and_numbers_stays_out_of_reports(monkeypatch):
    from news_report_routing import delivery_type

    monkeypatch.setenv("TELEGRAM_COMPANY_REPORTS_RESULTS_ONLY_ENABLED", "true")
    forecast = "Founder sees Example 4Q revenue up 70%, $2B above Wall Street estimates"
    actual = "Example reports Q4 revenue of $2 billion; CEO sees Q1 revenue up 10%"
    assert delivery_type("stock_news", forecast) == "stock_news"
    assert delivery_type("stock_news", actual) == "company_report"


@pytest.mark.parametrize("title,allowed", [
    ("AMD rises after CoreWeave results", False),
    ("Nvidia replaces CEO. When Intel replaced its CEO, shares fell", False),
    ("Intel rises after CoreWeave results", True),
    ("Marvell and Intel rise on a chip rally", True),
    ("Intel stock could climb after guidance. Is it time to buy?", False),
])
def test_watchlist_label_needs_direct_headline_evidence(title, allowed):
    from news_pipeline import _notification_subject

    assert _notification_subject({"title": title}, "INTC", "Intel Corporation") is allowed


def test_pending_watchlist_notice_rechecks_original_headline(isolated_pipeline, monkeypatch):
    import news_pipeline
    from news_subscriptions import personal_delivery_message

    case = isolated_pipeline
    monkeypatch.setenv("STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED", "true")
    news_pipeline.ingest_items([{
        **case.item(provider="yahoo_priority", ticker="INTC"),
        "title": "AMD raises its revenue guidance", "tickers": ["INTC"],
    }], case.clock)
    news = case.rows("SELECT id,content_hash FROM scanner_news")[0]
    import database
    with database.get_db_connection() as conn:
        conn.execute("""INSERT INTO scanner_news_watchlist(ticker,company,enabled,created_at,updated_at)
            VALUES('INTC','Intel Corporation',1,?,?)""", (news_pipeline._z(case.clock), news_pipeline._z(case.clock)))
        conn.commit()
    event = {"dedupe_key": f"watchlist-news:{news['id']}:{news['content_hash']}:INTC"}
    assert personal_delivery_message(event) is None


def test_multiple_stocks_do_not_inherit_one_direction(monkeypatch):
    from news_direction_routing import direction_for_result

    monkeypatch.setenv("STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED", "true")
    result = {"related": True, "relevance": .91, "materiality": "high", "sentiment": "positive"}
    event = {"tickers": ["AAA", "BBB"], "company_identity": [{"ticker": "AAA"}, {"ticker": "BBB"}]}
    assert direction_for_result(event, result) is None
    assert direction_for_result({"tickers": ["AAA"], "company_identity": [{"ticker": "AAA"}]}, result) == "positive"


def test_analyst_target_comparison_uses_both_values_without_reordering():
    from news_analyst_presentation import compact_parts

    title = "בית ההשקעות מעדכן את מחיר היעד ל-86 דולר מתוך 100 דולר"
    assert compact_parts(title, title, "SYN") == [
        "📊 בית ההשקעות מעדכן את מחיר היעד ל-86 דולר (לעומת 100 דולר קודם)", "מניות: SYN"]
    assert compact_parts("דיווח על 86 דולר מתוך 100 דולר", "") == [
        "📊 דיווח על 86 דולר מתוך 100 דולר"]


def test_macro_comparison_keeps_new_data_and_rejects_conflicting_periods():
    from news_macro_bulletins import releases, render

    title = "Japan PPI (M/M) Oct: 0.7% (est 0.3%; prev -0.3%)"
    bundle = releases(title, title + "\n- PPI (Y/Y): 7.1% (est 6.5%; prev 6.8%)\n(@wire)")
    relay = releases("JAPANESE PPI MOM ACTUAL 0.70% (FORECAST 0.3%, PREVIOUS -0.3%) $MACRO|FJ", "")
    assert len(bundle) == 2 and bundle[0].same_figure(relay[0])
    assert not bundle[0].same_figure(releases(title.replace("Oct", "Sep"), "")[0])
    assert not bundle[0].same_figure(releases(title.replace("PPI", "CPI"), "")[0])
    assert not bundle[0].same_figure(releases(title.replace("0.3%;", "0.4%;"), "")[0])
    assert releases(title, title + "\nA revision is due tomorrow.") == ()
    assert "מדד מחירי היצרן" in render(bundle) and "אוקטובר" in render(bundle)


def test_macro_bulletin_enqueues_only_new_figures_across_relays(isolated_pipeline, monkeypatch):
    import database
    import news_pipeline

    case = isolated_pipeline
    monkeypatch.setenv("STOCK_SCANNER_PUBLIC_NEWS_STRICT_QUALITY_ENABLED", "true")
    monthly = "GERMAN CPI FINAL MOM ACTUAL -0.2% (FORECAST -0.2%, PREVIOUS -0.2%) $MACRO|FJ"
    yearly = "German CPI (Y/Y) Oct F: 2.8% (est 2.8%; prev 2.8%)"
    extra = "- CPI (M/M): -0.2% (est -0.2%; prev -0.2%)"
    candidates = [
        (monthly, monthly),
        (yearly, yearly + "\n" + extra),
        ("GERMAN CPI FINAL YOY ACTUAL 2.8% (FORECAST 2.8%, PREVIOUS 2.8%) $MACRO|FJ", ""),
    ]
    for index, (title, excerpt) in enumerate(candidates):
        now = case.clock + timedelta(seconds=index * 5)
        news_pipeline.ingest_items([{
            **case.item(provider="telegram_channels", url=f"https://example.test/{index}"),
            "title": title, "published_at": news_pipeline._z(now), "source_excerpt": excerpt,
            "source_kind": "telegram_post",
        }], now)
        with database.get_db_connection() as conn:
            row = dict(conn.execute("SELECT * FROM scanner_news ORDER BY id DESC LIMIT 1").fetchone())
            result = {"title_he": "דיווח מדד", "summary_he": "נתון מאקרו"}
            assert news_pipeline._queue_general_bulletin(
                conn.cursor(), row, result, now, news_pipeline._z(now), translation_only=True) is (index < 2)
            conn.commit()
    notices = case.rows("SELECT message FROM scanner_telegram_outbox ORDER BY id")
    assert len(notices) == 2
    assert "חודשי" in notices[0]["message"] and "שנתי" not in notices[0]["message"]
    assert "שנתי" in notices[1]["message"] and "חודשי" not in notices[1]["message"]
