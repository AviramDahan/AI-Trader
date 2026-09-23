"""Browser smoke test of the deployed UI. Install playwright and Chromium first."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://aviramdahan.github.io/AI-Trader"


def main():
    backend = (ROOT / ".runtime/backend-url.txt").read_text().strip()
    with sync_playwright() as p:
        installed = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
        candidates = sorted(installed.glob("chromium-*/chrome-win64/chrome.exe"))
        browser = p.chromium.launch(executable_path=str(candidates[-1]) if candidates else None)
        for width, height in [(390, 844), (1440, 1000)]:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            failures = []
            page.on("requestfailed", lambda r: failures.append(r.url.split("?")[0]))
            page.goto(SITE + "/market", wait_until="networkidle")
            expect(page.get_by_text("Stock scanner dashboard", exact=True)).to_be_visible(timeout=30000)
            expect(page.locator(".scanner-hero").get_by_text("PAPER TRADING ONLY", exact=True)).to_be_visible()
            assert page.locator(".backend-status-banner").count() == 0
            activity = page.evaluate("async url => (await fetch(url)).json()", backend + "/api/runtime/activity")
            assert activity["enabled"] and not activity["stale"] and activity["last_scan_at"]
            assert activity["universe_count"] >= 500 and activity["data_count"] > 0
            for name in ("Signals", "Demo trades", "Results", "News", "Scanner status"):
                expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()
            for path in ["/health", "/api/scanner/dashboard", "/api/scanner/quotes", "/api/market-intel/overview"]:
                result = page.evaluate("""async url => {
                    const response = await fetch(url);
                    const data = await response.json();
                    return {status: response.status, data};
                }""", backend + path)
                assert result["status"] == 200, path
                if path.endswith("dashboard"):
                    assert result["data"]["paper_only"] and result["data"]["scanner_name"] == "us-stock-scanner"
                    assert result["data"]["lifecycle_verification"]["accounting_ok"]
                    assert result["data"]["legacy_positions"]["unmanaged_count"] == 0
                    open_primary = [trade for trade in result["data"]["trades"]
                                    if trade["status"] == "open" and not trade["is_shadow"]]
                    assert open_primary
                    assert all(trade["settings"].get("target_plan", {}).get("method") ==
                               "daily_resistance_and_measured_move_v1" for trade in open_primary)
                if path.endswith("quotes"):
                    assert result["data"]["refresh_seconds"] <= 30
                    assert result["data"]["realtime_guaranteed"] is False
                    assert result["data"]["quotes"]
                if path.endswith("overview"):
                    assert result["data"]["available"], "Financial events unavailable"
                    assert result["data"]["headline_count"] > 0
            for label, lang, direction in [("עברית", "he", "rtl"), ("EN", "en", "ltr")]:
                page.get_by_role("button", name=label, exact=True).click()
                expect(page.locator("html")).to_have_attribute("lang", lang)
                expect(page.locator("html")).to_have_attribute("dir", direction)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "horizontal overflow"
            page.get_by_role("button", name="עברית", exact=True).click()
            expect(page.get_by_text("דשבורד סורק המניות", exact=True)).to_be_visible()
            for text in ("סיגנלים", "עסקאות דמו", "תוצאות", "חדשות", "מצב הסורק"):
                expect(page.get_by_role("button", name=text, exact=True)).to_be_visible()
            first_signal = page.locator("details.scanner-signal-card").first
            expect(first_signal).to_be_visible()
            assert first_signal.get_attribute("open") is None
            expect(first_signal.locator(".scanner-signal-summary")).to_contain_text("$")
            first_signal.locator("summary").click()
            expect(first_signal.locator(".scanner-signal-body")).to_be_visible()
            expect(first_signal.get_by_text("מחיר", exact=False).first).to_be_visible()
            assert ": —" not in first_signal.locator(".scanner-signal-summary").inner_text()
            signal_chart = first_signal.locator(".scanner-position-chart")
            signal_chart.locator("summary").click()
            expect(signal_chart.locator("img")).to_be_visible(timeout=30000)
            page.wait_for_function(
                "() => document.querySelector('.scanner-signal-card .scanner-position-chart img')?.naturalWidth > 100",
                timeout=30000,
            )
            signal_chart.locator("img").click()
            signal_dialog = page.get_by_role("dialog").first
            expect(signal_dialog).to_be_visible()
            signal_dialog.get_by_role("button", name="סגור גרף", exact=True).click()
            expect(signal_dialog).not_to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Hebrew signal overflow"
            page.get_by_role("button", name="עסקאות דמו", exact=True).click()
            expect(page.locator(".scanner-account-grid")).to_be_visible()
            first_trade = page.locator(".scanner-trade-card").first
            targets = first_trade.locator(".scanner-targets")
            expect(targets).to_contain_text("TP1:")
            expect(targets).to_contain_text("תשואה מהכניסה")
            expect(targets).to_contain_text("Shadow בלבד — אין מימוש בפועל")
            expect(targets).to_contain_text("יעד פעיל — סגירת כל הכמות שנותרה")
            expect(first_trade.get_by_text("אסטרטגיה פעילה: יעד יחיד", exact=False)).to_be_visible()
            expect(first_trade.get_by_text("מחיר אחרון", exact=False)).to_be_visible()
            assert "מחיר אחרון ידוע — לא עדכני: —" not in first_trade.inner_text()
            assert "מחיר נוכחי אחרון: —" not in first_trade.inner_text()
            chart = first_trade.locator(".scanner-position-chart")
            chart.locator("summary").click()
            image = chart.locator("img")
            expect(image).to_be_visible(timeout=30000)
            page.wait_for_function(
                "() => document.querySelector('.scanner-trade-card .scanner-position-chart img')?.naturalWidth > 100",
                timeout=30000,
            )
            image.click()
            dialog = page.get_by_role("dialog", name=f"גרף יומי של {first_trade.locator('header b').first.inner_text()} עם מחיר כניסה, סטופ ויעדי TP1, TP2 ו־TP3")
            expect(dialog).to_be_visible()
            expect(dialog.locator("img")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Chart modal overflow"
            dialog.get_by_role("button", name="סגור גרף", exact=True).click()
            expect(dialog).not_to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Hebrew trades overflow"
            page.screenshot(path=str(ROOT / ".runtime" / f"qa-trades-{width}.png"), full_page=True)
            for button, heading in (("תוצאות", "השוואת אסטרטגיות יציאה"),
                                    ("חדשות", "חדשות — מהחדש לישן"),
                                    ("מצב הסורק", "מצב רכיבי הסורק"),
                                    ("סיגנלים", "סיגנלים פעילים")):
                page.get_by_role("button", name=button, exact=True).click()
                expect(page.get_by_role("heading", name=heading, exact=False)).to_be_visible()
                if button == "מצב הסורק":
                    expect(page.get_by_role("heading", name="אימות מחזור עסקה חי", exact=True)).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Hebrew lifecycle status overflow"
                if button == "חדשות":
                    assert page.locator(".scanner-filters select").count() >= 5
                    expect(page.get_by_role("heading", name="רשימת מעקב לחדשות Telegram", exact=True)).to_be_visible()
                    expect(page.get_by_text("הרשימה אינה יוצרת סיגנלים או עסקאות", exact=False)).to_be_visible()
                    expect(page.locator(".scanner-watchlist-items").get_by_text("INTC", exact=True)).to_be_visible()
                    expect(page.get_by_text("רענון תצוגה", exact=False)).to_be_visible()
                    expect(page.get_by_text("בדיקת ספק אחרונה", exact=False)).to_be_visible()
                    assert page.locator(".scanner-status-grid .scanner-status").count() >= 5
                    assert page.locator(".scanner-news-card").count() > 0
                    expect(page.locator(".scanner-news-card").first.get_by_text("מידע מהמקור", exact=False)).to_be_visible()
                    expect(page.locator(".scanner-news-card").first.get_by_text("מפרסם מקורי", exact=False)).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Hebrew news overflow"
            assert page.evaluate("document.documentElement.dir === 'rtl'")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Hebrew dashboard overflow"
            assert page.evaluate("""[...document.querySelectorAll('button')].filter(button => {
                const style = getComputedStyle(button); return style.display !== 'none' && style.visibility !== 'hidden'
              }).every(button => { const box = button.getBoundingClientRect(); return box.left >= -1 && box.right <= innerWidth + 1 })"""), "button overflow"
            page.get_by_role("button", name="EN", exact=True).click()
            expect(page.get_by_text("Stock scanner dashboard", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="Active signals", exact=False)).to_be_visible()
            assert page.evaluate("document.documentElement.dir === 'ltr'")
            page.get_by_role("button", name="News", exact=True).click()
            expect(page.get_by_role("heading", name="News — newest first", exact=False)).to_be_visible()
            expect(page.get_by_role("heading", name="Telegram news watchlist", exact=True)).to_be_visible()
            expect(page.get_by_text("Screen refresh", exact=False)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "English news overflow"
            page.get_by_role("button", name="Signals", exact=True).click()
            assert page.locator(".backend-status-banner").count() == 0
            if width == 390:
                toggle = page.locator(".mobile-nav-toggle")
                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "true")
                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "false")
            assert not failures, f"Failed requests: {failures}"
            page.screenshot(path=str(ROOT / ".runtime" / f"qa-scanner-{width}.png"), full_page=True)
            print(f"PASS browser {width}px: public scanner, Hebrew/English, RTL/LTR, menu and no overflow")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
