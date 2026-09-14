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
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        calls = []
        def manifest(route):
            calls.append(1)
            # Initial discover + initial status check are offline; next poll recovers.
            route.fulfill(json={'backend_url': OLD if len(calls) <= 2 else current})
        page.route('**/runtime-config.json?*', manifest)
        page.route(OLD + '/**', lambda route: route.abort('connectionfailed'))
        page.goto('https://aviramdahan.github.io/AI-Trader/market', wait_until='domcontentloaded')
        expect(page.locator('.backend-status-banner')).to_be_visible(timeout=15000)
        expect(page.get_by_text('ai-trader-admin', exact=True)).to_be_visible(timeout=70000)
        expect(page.locator('.backend-status-banner')).to_have_count(0)
        expect(page.get_by_test_id('paper-activity')).to_be_visible()
        assert len(calls) >= 3
        print('PASS mobile browser recovered from an offline endpoint using the new manifest without manual refresh')
        browser.close()


if __name__ == '__main__':
    main()
