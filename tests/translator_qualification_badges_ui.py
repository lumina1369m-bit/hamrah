"""Fixed translator qualification badges and their invented detail cards must stay absent."""
import asyncio
import os
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from hz_api import LOGIN_JS

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_qualification_badges'
FORBIDDEN = ('CAP-100', 'C1', 'پژو ۲۰۷', 'پوشش بیمه مأموریت فعال', 'بیمه‌نامه بدنه کامل',
             'MED-IPD-IR-402', 'LNG-AR-EN-C1-801', 'CAP-100-IR-9921')


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    try:
        await page.goto(BASE + '/translator/index.html')
        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        token = await page.evaluate(LOGIN_JS, phone)
        assert token, 'translator session was not established'
        await page.goto(BASE + '/translator/app.html')
        shortcut = page.locator('#qualification-shortcut')
        await expect(shortcut).to_be_visible()
        await expect(shortcut.locator('button')).to_have_attribute('aria-controls', 'view-credentials')
        text = await shortcut.inner_text()
        for claim in FORBIDDEN:
            assert claim not in text, f'fixed qualification claim remains: {claim}'
        assert await page.locator('#inline-badge-detail-card').count() == 0
        assert await page.evaluate('typeof showBadgeDetail') == 'undefined'
        assert await page.evaluate('typeof closeBadgeDetail') == 'undefined'

        await shortcut.locator('button').click()
        credentials = page.locator('#view-credentials')
        await expect(credentials).to_be_visible()
        await expect(credentials.locator('h2')).to_have_text('وضعیت مدارک و صلاحیت')
        await expect(page.locator('#cap-box')).to_contain_text('احراز هویت و صلاحیت امنیتی')
        live_text = await page.locator('#cap-box').inner_text()
        for claim in ('CAP-100', 'گواهی زبان C1', 'پژو ۲۰۷ تشریفات', 'بیمه مأموریت فعال'):
            assert claim not in live_text, f'unsupported badge detail leaked into live status: {claim}'
        assert not errors, errors
        print(f'PASS [{width}]: invented identity/language/medical/car/insurance badges removed; live server-backed status remains reachable')
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(ARTIFACTS / f'failure-{width}.png'), full_page=True)
            (ARTIFACTS / f'failure-{width}.html').write_text(await page.content())
        except Exception:
            pass
        raise
    finally:
        await context.close()


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=['--no-sandbox'])
        try:
            await scenario(browser, 390)
            await scenario(browser, 1280)
        finally:
            await browser.close()
    print('RESULT: PASS (2/2 viewports)')


asyncio.run(main())
