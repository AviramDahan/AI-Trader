"""Browser-only fixture: no production inserts, orders, or Telegram calls."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as p:
        candidates = sorted((Path(os.environ["LOCALAPPDATA"])/"ms-playwright").glob("chromium-*/chrome-win64/chrome.exe"))
        browser = p.chromium.launch(executable_path=str(candidates[-1]) if candidates else None)
        for width in (390,1440):
            context = browser.new_context(viewport={"width": width,"height": 900})
            def fixture(route):
                response = route.fetch()
                data = response.json()
                data["signals"] = [{"id": -1,"ticker": "UI-TEST", "company": "ISOLATED BROWSER FIXTURE",
                    "action": "BUY", "status": "PENDING_ENTRY", "planned_entry": 100,
                    "current_price": 101.25, "price_as_of": "2026-09-22T13:30:00Z", "price_stale": True,
                    "original_stop": 97,"current_stop": 97,"tp1":103.7,"tp2":107.7,"tp3":111.7,
                    "tp1_pct": 1/3,"tp2_pct":1/3,"tp3_pct":1/3,"rr1":1.23,"rr2":2.57,"rr3":3.9,
                    "weighted_rr":2.57,"confidence":.85,"reason_he":"בדיקת דפדפן מבודדת בלבד",
                    "technical_json":{"target_plan":{"zones":[{"low":104,"high":104.5,"touches":2,
                        "pivots":[{"date":"2026-09-01"},{"date":"2026-09-08"}]}]}}}]
                route.fulfill(response=response,body=json.dumps(data))
            context.route("**/api/scanner/dashboard*", fixture)
            page = context.new_page()
            page.goto("https://aviramdahan.github.io/AI-Trader/market",wait_until="networkidle")
            for label, text in (("עברית","כיצד חושבו היעדים?"),("EN","How were targets calculated?")):
                page.get_by_role("button",name=label,exact=True).click()
                card = page.locator("#signal--1")
                expect(card).to_be_visible()
                expect(card.get_by_text("$101.25",exact=False)).to_be_visible()
                summary = card.locator("summary").filter(has_text=text)
                summary.click()
                expect(card.get_by_text("2026-09-01",exact=False)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "overflow"
                summary.click()
            print(f"PASS {width}px isolated signal card: quote, stale label, structure evidence, Hebrew/English")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
