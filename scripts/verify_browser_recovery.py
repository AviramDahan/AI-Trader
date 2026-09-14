"""Exercise deployed endpoint rediscovery in a real browser without disrupting services."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OLD = 'https://04f3e5fb7105b8db-5-29-209-136.serveousercontent.com'


def main():
    current = (ROOT / '.runtime/backend-url.txt').read_text().strip()
    if current == OLD:
        raise RuntimeError('Recovery test needs the historical and current endpoint to differ')
    with sync_playwright() as p:
        candidates = sorted((Path(os.environ['LOCALAPPDATA']) / 'ms-playwright').glob('chromium-*/chrome-win64/chrome.exe'))
        browser = p.chromium.launch(executable_path=str(candidates[-1]) if candidates else None)
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        context.add_init_script("localStorage.setItem('ai_trader_language', 'he')")
        page = context.new_page()
        calls = []
        def manifest(route):
            calls.append(1)
            # Initial discover + two health cycles stay stale, then the manifest rotates.
            route.fulfill(json={'backend_url': OLD if len(calls) <= 3 else current})
        page.route('**/runtime-config.json?*', manifest)
        page.route(OLD + '/**', lambda route: route.abort('connectionfailed'))
        page.goto('https://aviramdahan.github.io/AI-Trader/market', wait_until='domcontentloaded')
        expect(page.locator('.backend-status-banner')).to_be_visible(timeout=25000)
        expect(page.get_by_role('alert').get_by_role('button', name='בדיקה מחדש', exact=True)).to_be_visible()
        expect(page.get_by_text('דשבורד סורק המניות', exact=True)).to_be_visible(timeout=45000)
        expect(page.locator('.backend-status-banner')).to_have_count(0, timeout=45000)
        expect(page.get_by_text('מסחר מדומה בלבד', exact=True).last).to_be_visible()
        assert len(calls) >= 4

        # A temporary health failure on the current URL must recover without a page reload.
        health_offline = {'value': False}
        def health(route):
            if health_offline['value']:
                route.abort('connectionfailed')
            else:
                route.continue_()
        page.route(current + '/health', health)
        health_offline['value'] = True
        expect(page.locator('.backend-status-banner')).to_be_visible(timeout=25000)
        health_offline['value'] = False
        page.get_by_role('alert').get_by_role('button', name='בדיקה מחדש', exact=True).click()
        expect(page.locator('.backend-status-banner')).to_have_count(0, timeout=10000)
        assert page.evaluate("Number(localStorage.getItem('ai_trader_backend_last_success')) > 0")
        print('PASS mobile browser handled offline, Retry, recovery and tunnel URL rotation without manual reload')
        context.close()
        browser.close()


if __name__ == '__main__':
    main()
