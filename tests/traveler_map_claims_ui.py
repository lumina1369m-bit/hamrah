"""Traveler map copy must not invent online counts or require automatic GPS access."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_map_claims'
COPY = {
    'fa': {
        'availability': 'پذیرش درخواست به در دسترس بودن مترجم بستگی دارد.',
        'selection_badge': 'قابل تغییر روی نقشه',
        'guidance': 'نقطهٔ ملاقات را روی نقشه انتخاب کنید یا نشانی را جست‌وجو کنید. موقعیت دستگاه فقط پس از اجازهٔ شما خوانده می‌شود.',
        'forbidden': ('۴ مترجم آنلاین در محدوده', 'مترجم آنلاین در محدوده: ۴',
                      'تعیین خودکار GPS', 'نزدیک‌ترین مترجم', 'موقعیت شما لازم است'),
    },
    'en': {
        'availability': 'Request acceptance depends on interpreter availability.',
        'selection_badge': 'Editable on the map',
        'guidance': 'Choose the meeting point on the map or search for an address. Your device location is read only with your permission.',
        'forbidden': ('4 online interpreters in range', 'Online interpreters in range: 4',
                      'Automatic GPS location', 'nearest translator', 'we need your location'),
    },
    'ar': {
        'availability': 'يعتمد قبول الطلب على توفر المترجم.',
        'selection_badge': 'قابلة للتغيير على الخريطة',
        'guidance': 'اختر نقطة اللقاء على الخريطة أو ابحث عن عنوان. لا يُقرأ موقع جهازك إلا بعد إذنك.',
        'forbidden': ('٤ مترجمين متصلين في النطاق', 'مترجمون متصلون في النطاق: ٤',
                      'تعیین خودکار GPS', 'تحديد الموقع تلقائياً (GPS)', 'أقرب مترجم', 'نحتاج إلى موقعك'),
    },
}


async def scenario(browser, width):
    context = await browser.new_context(
        viewport={'width': width, 'height': 900}, service_workers='block'
    )
    await context.route(
        'https://nominatim.openstreetmap.org/**',
        lambda route: route.fulfill(json={'display_name': 'Test meeting point'}),
    )
    await context.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        await page.goto(BASE + '/traveler/app.html')
        await expect(page.locator('#real-map')).to_be_attached()
        await expect(page.locator('#center-location-pin')).to_be_attached()
        await expect(page.locator('#location-picker-bar')).to_be_visible()
        await page.wait_for_function('() => window.HZ_I18N && document.querySelector("#map-availability-note .availability-copy")')

        current_language = 'fa'
        for language, copy in COPY.items():
            if language != current_language:
                await page.evaluate('(language) => window.HZ_I18N.set(language)', language)
                current_language = language
            await expect(page.locator('#map-availability-note .availability-copy')).to_have_text(copy['availability'])
            await expect(page.locator('#location-availability-note .availability-copy')).to_have_text(copy['availability'])
            await expect(page.locator('#location-selection-badge')).to_have_text(copy['selection_badge'])
            await expect(page.locator('#location-guidance')).to_have_text(copy['guidance'])

            map_copy = (await page.locator('#map-availability-note').inner_text()) + '\n' + \
                       (await page.locator('#location-picker-bar').inner_text())
            for claim in copy['forbidden']:
                assert claim not in map_copy, f'unsupported map/location claim remains in {language}: {claim}'
            assert await page.locator(
                '#map-availability-note .bg-emerald-500, '
                '#location-availability-note .bg-emerald-500, '
                '#map-availability-note .animate-pulse, '
                '#location-availability-note .animate-pulse'
            ).count() == 0, 'a live-availability indicator remains beside the disclaimer'
            print(f'PASS [{width}/{language}]: no fixed interpreter count or automatic-GPS claim')
        assert not errors, errors
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
    print('RESULT: PASS (2 viewports; 6 language/viewport combinations)')


asyncio.run(main())
