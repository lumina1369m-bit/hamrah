"""The translator earnings view must not invent balances or payout history."""
import asyncio
import os
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from hz_api import LOGIN_JS

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_earnings_truth'
FORBIDDEN = (
    '۴,۹۲۰,۰۰۰', '٤,٩٢٠,٠٠٠', '4,920,000', 'IR820170000000123456789012',
    'IR8201...', 'PAYA-7701', 'شاپرک', 'تسویه پایا خودکار', 'موجودی قابل تسویه',
    'نمودار درآمد ۷ روز گذشته', 'مجموع هفته:', '۱۱,۳۵۰,۰۰۰',
    'آخرین واریزی‌های مأموریت', 'هیئت تجاری امارات', 'کلینیک نور',
    'ترانسفر CIP فرودگاه', '۲,۴۰۰,۰۰۰', '۱,۸۵۰,۰۰۰', '۱,۶۰۰,۰۰۰',
)


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors, payment_posts = [], []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.on('request', lambda request: payment_posts.append(request.url)
            if request.method == 'POST' and request.url.rstrip('/').endswith('/payment') else None)
    try:
        await page.goto(BASE + '/translator/index.html')
        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        token = await page.evaluate(LOGIN_JS, phone)
        assert token, 'translator session was not established'
        await page.goto(BASE + '/translator/app.html')
        nav = '#mobile-nav' if width < 768 else '#desktop-nav'
        await page.locator(nav + ' [data-target="earnings"]').click()
        view = page.locator('#view-earnings')
        note = page.locator('#earnings-data-note')
        await expect(view).to_be_visible()
        await expect(note).to_be_visible()
        await expect(note.locator('#earnings-data-title')).to_have_text('گزارش مالی در دسترس نیست')
        await expect(note).to_contain_text('از سرور دریافت نمی‌شوند')
        await expect(note).to_contain_text('عدد، نمودار یا نتیجهٔ تسویهٔ نمونه نمایش داده نمی‌شود')
        await expect(note).to_contain_text('پرداخت‌های منتظر تأیید در میزکار')
        text = await view.inner_text()
        for value in FORBIDDEN:
            assert value not in text, f'fabricated earnings or settlement data remains: {value}'
        buttons = await view.locator('button').all_text_contents()
        assert len(buttons) == 1 and 'بازگشت به میز کار' in buttons[0], buttons
        assert not payment_posts, f'opening the report must not initiate payment: {payment_posts}'
        await page.locator(nav + ' [data-target="workspace"]').click()
        await expect(page.locator('#view-workspace')).to_be_visible()
        await expect(page.locator('#payments-box')).to_be_attached()
        assert not errors, errors
        print(f'PASS [{width}]: no invented wallet, account, income, or payout data/actions; server-backed payment area remains')
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
