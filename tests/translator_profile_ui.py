"""Translator profile panel must not present hard-coded ratings or credentials as personal facts."""
import asyncio
import os
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from hz_api import LOGIN_JS

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_profile'
FORBIDDEN = ('۴.۹۵', '4.95', '۱۲۸ نظر', '۱۲۸ مأموریت', '۶۴ ساعت', 'CAP-100-IR41',
             '۰۰۸****۳۲۱', 'پژو ۲۰۷', 'بیمه‌نامه کامل بدنه', 'خودرو تایید شده سامانه')


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
        profile_button = page.locator('#header-profile-btn')
        await profile_button.click()
        panel = page.locator('#inline-profile-panel')
        await expect(panel).to_be_visible()
        await expect(panel.locator('#profile-title')).to_have_text('نمایهٔ مترجم')
        await expect(panel.locator('[data-tr-name]')).to_have_text('علی رضایی')
        note = panel.locator('#profile-data-note')
        await expect(note).to_contain_text('همین مرورگر')
        await expect(note).to_contain_text('هویت تأییدشده را ثابت نمی‌کند')
        await expect(note).to_contain_text('از حساب شما دریافت نشده‌اند')
        content = await panel.inner_text()
        for claim in FORBIDDEN:
            assert claim not in content, f'unsupported profile claim remains: {claim}'
        await panel.locator('button:has-text("بستن پنل")').click()
        await expect(panel).to_be_hidden()
        assert not errors, errors
        print(f'PASS [{width}]: display name is labeled local; fabricated rating, activity, identity ID and vehicle approval are absent')
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
