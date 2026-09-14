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
            for path in ["/health", "/api/scanner/dashboard", "/api/market-intel/overview"]:
                result = page.evaluate("""async url => {
                    const response = await fetch(url);
                    const data = await response.json();
                    return {status: response.status, data};
                }""", backend + path)
                assert result["status"] == 200, path
                if path.endswith("dashboard"):
                    assert result["data"]["paper_only"] and result["data"]["scanner_name"] == "us-stock-scanner"
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
            assert page.evaluate("document.documentElement.dir === 'rtl'")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Hebrew dashboard overflow"
            assert page.evaluate("""[...document.querySelectorAll('button')].filter(button => {
                const style = getComputedStyle(button); return style.display !== 'none' && style.visibility !== 'hidden'
              }).every(button => { const box = button.getBoundingClientRect(); return box.left >= -1 && box.right <= innerWidth + 1 })"""), "button overflow"
            page.get_by_role("button", name="EN", exact=True).click()
            expect(page.get_by_text("Stock scanner dashboard", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.dir === 'ltr'")
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
