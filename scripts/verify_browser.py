"""Browser smoke test of the deployed UI. Install playwright and Chromium first."""
import json
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
            expect(page.get_by_text("ai-trader-admin", exact=True)).to_be_visible(timeout=30000)
            assert page.locator(".backend-status-banner").count() == 0
            panel = page.get_by_test_id("paper-activity")
            expect(panel).to_be_visible(timeout=15000)
            panel.locator("summary").click()
            activity = page.evaluate("async url => (await fetch(url)).json()", backend + "/api/runtime/activity")
            assert activity["enabled"] and not activity["stale"] and activity["last_scan_at"]
            assert activity["universe_count"] >= 500 and activity["data_count"] > 0
            expect(panel).to_contain_text("US STOCK SCANNER", timeout=15000)
            for path in ["/health", "/api/claw/agents/count", "/api/trending", "/api/market-intel/overview"]:
                result = page.evaluate("""async url => {
                    const response = await fetch(url);
                    const data = await response.json();
                    return {status: response.status, data};
                }""", backend + path)
                assert result["status"] == 200, path
                if path.endswith("count"):
                    assert result["data"]["count"] > 0
                if path.endswith("trending"):
                    assert result["data"]["trending"]
                if path.endswith("overview"):
                    assert result["data"]["available"], "Financial events unavailable"
                    assert result["data"]["headline_count"] > 0
            for label, lang, direction in [("עברית", "he", "rtl"), ("EN", "en", "ltr")]:
                page.get_by_role("button", name=label, exact=True).click()
                expect(page.locator("html")).to_have_attribute("lang", lang)
                expect(page.locator("html")).to_have_attribute("dir", direction)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "horizontal overflow"
            page.get_by_role("button", name="עברית", exact=True).click()
            page.goto(SITE + "/discussions", wait_until="networkidle")
            for text in ("דיון חופשי בנושאים פיננסיים", "החדשים ביותר", "הפעילים ביותר", "במעקב"):
                expect(page.get_by_text(text, exact=True)).to_be_visible()
            for untranslated in ("Free discussion on financial topics", "Newest", "Most Active", "Following"):
                assert page.get_by_text(untranslated, exact=True).count() == 0
            assert page.evaluate("document.documentElement.dir === 'rtl'")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Hebrew discussions overflow"
            assert page.evaluate("""[...document.querySelectorAll('button')].filter(button => {
                const style = getComputedStyle(button); return style.display !== 'none' && style.visibility !== 'hidden'
              }).every(button => { const box = button.getBoundingClientRect(); return box.left >= -1 && box.right <= innerWidth + 1 })"""), "button overflow"
            page.get_by_role("button", name="EN", exact=True).click()
            expect(page.get_by_text("Free discussion on financial topics", exact=True)).to_be_visible()
            expect(page.get_by_text("Newest", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.dir === 'ltr'")
            assert page.locator(".backend-status-banner").count() == 0
            if width == 390:
                toggle = page.locator(".mobile-nav-toggle")
                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "true")
                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "false")
            assert not failures, f"Failed requests: {failures}"
            page.screenshot(path=str(ROOT / ".runtime" / f"qa-discussions-{width}.png"), full_page=True)
            print(f"PASS browser {width}px: public data, Hebrew/English discussions, RTL/LTR, menu and no overflow")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
