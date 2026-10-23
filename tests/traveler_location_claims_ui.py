"""Traveler sign-in must describe meeting-point selection, not live tracking or ETA."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_location_claims'
COPY = {
    'fa': {
        'title': 'انتخاب محل ملاقات',
        'description': 'محل ملاقات را روی نقشه انتخاب و تأیید کنید.',
        'forbidden': ('اعزام فوری در محل دلخواه', 'مشاهده زنده موقعیت روی نقشه و تخمین زمان رسیدن', 'ردیابی زندهٔ مترجم'),
    },
    'en': {
        'title': 'Meeting point on the map',
        'description': 'Choose and confirm your meeting point on the map.',
        'forbidden': ('Instant On-Site Dispatch', 'Real-time GPS tracking', 'precise arrival estimations'),
    },
    'ar': {
        'title': 'اختيار نقطة اللقاء',
        'description': 'اختر نقطة اللقاء على الخريطة وأكّدها.',
        'forbidden': ('إيفاد فوري للموقع المطلوب', 'متابعة حية للموقع على الخريطة وتقدير دقيق لوقت الوصول', 'تقدير دقيق لوقت الوصول'),
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
            await expect(page.locator('[data-i18n="f1_title"]')).to_have_text(copy['title'])
            await expect(page.locator('[data-i18n="f1_desc"]')).to_have_text(copy['description'])
            body = await page.locator('body').inner_text()
            for claim in copy['forbidden']:
                assert claim not in body, f'unsupported location/ETA claim remains in {language}: {claim}'
        assert not errors, errors
        print(f'PASS [{width}]: Persian, English, Arabic describe map selection without live-tracking or ETA promises')
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
