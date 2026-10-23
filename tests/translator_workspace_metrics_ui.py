"""The translator workspace must not invent daily earnings, work time or satisfaction metrics."""
import asyncio
import os
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from hz_api import LOGIN_JS

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_workspace_metrics'
FORBIDDEN = ('۱,۸۵۰,۰۰۰', '1,850,000', '۴:۰۰', '4:00', '۴.۹۵', '4.95',
             '۱۲۸ مأموریت', '128 missions', 'درآمد امروز')


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
        nav = '#mobile-nav' if width < 768 else '#desktop-nav'
        await page.locator(nav + ' [data-target="workspace"]').click()
        workspace = page.locator('#view-workspace')
        await expect(workspace).to_be_visible()
        note = page.locator('#workspace-metrics-note')
        await expect(note).to_be_visible()
        await expect(note.locator('#workspace-metrics-title')).to_have_text('خلاصهٔ عملکرد')
        await expect(note).to_contain_text('از سرور دریافت نمی‌شوند')
        await expect(note).to_contain_text('عدد نمونه نمایش داده نمی‌شود')
        text = await workspace.inner_text()
        for value in FORBIDDEN:
            assert value not in text, f'fabricated workspace metric remains: {value}'
        assert not errors, errors
        print(f'PASS [{width}]: fixed income, hours, satisfaction and mission-count samples absent; transparent notice shown')
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
