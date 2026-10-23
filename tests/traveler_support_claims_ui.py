"""Traveler landing page describes only the configured, non-guaranteed contact option."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_support_claims'
COPY = {
    'fa': {
        'f4_title': 'راه تماس پشتیبانی',
        'f4_desc': 'اگر شماره‌ای در سامانه ثبت شده باشد، برنامه شماره‌گیر دستگاه را باز می‌کند؛ تماس یا پاسخ‌گویی تضمین نمی‌شود.',
        'trust_title': 'راه تماس تنظیم‌شده',
        'trust_sub': 'در صورت ثبت شماره در سامانه',
        'disclaimer': 'تضمین نمی‌شود',
        'forbidden': ('۲۴/۷', '24/7', 'شبانه‌روزی', 'همراهی لحظه‌ای و آنلاین', 'پشتیبانی فوری', 'تیم نظارت متمرکز'),
    },
    'en': {
        'f4_title': 'Support contact option',
        'f4_desc': 'If a number is configured, the app opens your dialer; a call or response is not guaranteed.',
        'trust_title': 'Configured contact option',
        'trust_sub': 'Shown only when a number is set',
        'disclaimer': 'not guaranteed',
        'forbidden': ('24/7', 'round-the-clock', 'Operations Command', 'on-call assistance', 'Instant Support', 'supervising each session'),
    },
    'ar': {
        'f4_title': 'وسيلة الاتصال بالدعم',
        'f4_desc': 'إذا تم إعداد رقم، يفتح التطبيق لوحة الاتصال؛ ولا يضمن إجراء المكالمة أو الرد.',
        'trust_title': 'خيار اتصال عند الإعداد',
        'trust_sub': 'يظهر فقط عند ضبط رقم',
        'disclaimer': 'لا يضمن',
        'forbidden': ('٢٤/٧', '24/7', 'على مدار الساعة', 'دعم متواصل', 'مرافقة ومساعدة فورية', 'فريق متابعة مركزي'),
    },
}


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    try:
        await page.goto(BASE + '/traveler/')
        for language, copy in COPY.items():
            if language != 'fa':
                await page.locator('#lang-btn').click()
                await page.locator('#opt-' + language).click()
            await expect(page.locator('[data-i18n="f4_title"]')).to_have_text(copy['f4_title'])
            await expect(page.locator('[data-i18n="f4_desc"]')).to_have_text(copy['f4_desc'])
            await expect(page.locator('[data-i18n="trust_support"]')).to_have_text(copy['trust_title'])
            await expect(page.locator('[data-i18n="trust_support_sub"]')).to_have_text(copy['trust_sub'])
            assert copy['disclaimer'] in await page.locator('[data-i18n="f4_desc"]').inner_text()
            body = await page.locator('body').inner_text()
            for claim in copy['forbidden']:
                assert claim not in body, f'unsupported support claim remains in {language}: {claim}'
            assert await page.locator('footer [data-i18n="footer_support"]').count() == 0
        assert not errors, errors
        print(f'PASS [{width}]: Persian, English, Arabic support copy is conditional; no 24/7 or instant-response promise')
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
    print('RESULT: PASS (2/2 viewports; 6 language/viewport combinations)')


asyncio.run(main())
