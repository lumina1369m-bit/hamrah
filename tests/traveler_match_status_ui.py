"""Traveler search and matched-booking states show only what the server confirms."""
import asyncio
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from booking_options_ui import translator
from finish_flow_ui import BASE, api, booking
from logout_sessions_ui import sign_in

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_match_status'
SEARCH_COPY = {
    'fa': {
        'pill': 'در حال جست‌وجو',
        'title': 'در حال جست‌وجوی مترجم برای درخواست شما',
        'limit': 'حداکثر زمان جست‌وجو: ۱۰ دقیقه',
        'description': 'مترجمان در دسترس بر اساس زبان‌ها و نوع خدمت درخواست شما بررسی می‌شوند.',
        'notifications': 'اعلان‌های مسافر در این نسخه در دسترس نیستند',
        'forbidden': ('در شعاع اولیه‌ی تنظیم‌شده (از پنل مدیریت)', 'بهترین مترجم مسلط به عربی (پزشکی)',
                      'امتیاز عملکرد', 'حوالی میدان ولیعصر'),
    },
    'en': {
        'pill': 'Search in progress',
        'title': 'Searching for an interpreter for your request',
        'limit': 'Maximum search time: 10 minutes',
        'description': 'Available interpreters are matched to the languages and service type in your request.',
        'notifications': 'Traveler notifications are not available in this version',
        'forbidden': ('initial radius set in admin', 'best Arabic (medical) interpreter',
                      'performance scores', 'near Valiasr Square'),
    },
    'ar': {
        'pill': 'جارٍ البحث',
        'title': 'جارٍ البحث عن مترجم لطلبك',
        'limit': 'الحد الأقصى لوقت البحث: ١٠ دقائق',
        'description': 'يتم البحث عن مترجمين متاحين بحسب اللغات ونوع الخدمة في طلبك.',
        'notifications': 'إشعارات المسافر غير متاحة في هذا الإصدار',
        'forbidden': ('النطاق الأولي المحدد في لوحة الإدارة', 'أفضل مترجم للعربية (طبي)',
                      'تقييم الأداء', 'قرب ميدان وليعصر'),
    },
}
COPY = {
    'fa': {
        'title': 'وضعیت رزرو',
        'description': 'مترجم درخواست شما را پذیرفت.',
        'forbidden': ('در راه رسیدن به محل شما', 'در حرکت', 'زمان تخمینی رسیدن مترجم', 'مترجم احراز هویت‌شده‌ی همراه'),
        'arrived': 'مترجم به محل رسید',
    },
    'en': {
        'title': 'Booking status',
        'description': 'The interpreter accepted your request.',
        'forbidden': ('On the way to your location', 'On the way', 'Estimated translator arrival time', 'Verified Hamrah interpreter'),
        'arrived': 'Interpreter arrived',
    },
    'ar': {
        'title': 'حالة الحجز',
        'description': 'قبل المترجم طلبك.',
        'forbidden': ('في الطريق إلى موقعك', 'في الطريق', 'وقت الوصول المتوقع للمترجم', 'مترجم همره موثّق الهوية'),
        'arrived': 'وصل المترجم',
    },
}


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = None
    errors = []
    session = None
    created = None
    try:
        await api(context.request, 'POST', '/dev/offline-all')
        translator_token = await translator(context.request, 'male')
        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        session = await sign_in(context.request, phone)
        await context.route(
            'https://nominatim.openstreetmap.org/**',
            lambda route: route.fulfill(json={'display_name': 'تهران، آزمون وضعیت رزرو'}),
        )
        await context.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
        page = await context.new_page()
        page.set_default_timeout(20000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE + '/traveler/index.html')
        profile = {
            'name': 'Ali', 'last': 'Rezaei', 'gender': 'مرد',
            'phone': session['user']['phone'], 'authUserId': session['user']['id'],
        }
        await page.evaluate('''([token, profile, lang]) => {
            localStorage.setItem('hamzaban.token.v1', token);
            localStorage.setItem('hamzaban.user.v1', JSON.stringify(profile));
            localStorage.setItem('hamzaban.bookings.v1', '[]');
            localStorage.setItem('hamzaban_lang', lang);
        }''', [session['token'], profile, 'fa'])
        await page.goto(BASE + '/traveler/app.html')
        await page.wait_for_function('() => window.hzBookingsSynced === true && !!window.HZ_NEAREST_CITY()')
        await expect(page.locator('header .animate-pulse, header .bg-emerald-500')).to_have_count(0)
        await page.locator('nav a[data-nav="map"]').click()
        await expect(page.locator('#selected-location-title')).to_have_text('تهران، آزمون وضعیت رزرو')
        await page.locator('#confirm-location-btn').click()
        await expect(page.locator('#bottom-sheet')).to_be_visible()
        await page.locator('#btn-toggle-car').click()
        async with page.expect_response(lambda response: response.url.endswith('/api/traveler/bookings')
                                        and response.request.method == 'POST') as response_info:
            await page.locator('#btn-main-submit').click()
        response = await response_info.value
        assert response.status == 201, await response.text()
        created = await response.json()
        assert created['kind'] == 'instant' and created['status'] == 'searching', created
        await expect(page.locator('#stage-2')).to_be_visible()
        await page.reload()
        await page.wait_for_function('() => window.hzBookingsSynced === true')
        await expect(page.locator('#stage-2')).to_be_visible()
        current_language = 'fa'
        for language, copy in SEARCH_COPY.items():
            if language != current_language:
                await page.locator('nav a[data-nav="account"]').click()
                await page.locator('#hz-lang-select').select_option(language)
                await page.locator('nav a[data-nav="map"]').click()
                current_language = language
            await expect(page.locator('#stage-2')).to_be_visible()
            await expect(page.locator('#search-status-pill')).to_have_text(copy['pill'])
            await expect(page.locator('#search-status-title')).to_have_text(copy['title'])
            await expect(page.locator('#search-time-limit')).to_have_text(copy['limit'])
            await expect(page.locator('#search-status-description')).to_have_text(copy['description'])
            stage_text = await page.locator('#stage-2').inner_text()
            for claim in copy['forbidden']:
                assert claim not in stage_text, f'unsupported search claim remains in {language}: {claim}'
            search_icons = await page.locator('#stage-2 .material-symbols-outlined').all_text_contents()
            assert 'verified_user' not in search_icons and 'verified' not in search_icons, 'a static identity-verification icon remains during search'
            await expect(page.locator('#search-timer-display')).to_have_count(0)
            await expect(page.locator('#btn-cancel-search')).to_be_visible()
            await page.locator('#btn-notifications').click()
            await expect(page.locator('#toast-pill')).to_be_visible()
            await expect(page.locator('#toast-text')).to_have_text(copy['notifications'])
            await page.locator('#toast-pill button').click()
            print(f'PASS [{width}/{language}]: accurate search status; no fabricated ranking, radius, identity badge, resetting countdown, empty-notification claim, or global online light')
        offers = await api(context.request, 'GET', '/translator/offers', translator_token)
        assert offers['offers'], 'the real booking did not create an interpreter offer'
        await api(context.request, 'POST', f"/translator/offers/{offers['offers'][0]['id']}/accept", translator_token)
        matched = await booking(context.request, session['token'], created['id'])
        assert matched['status'] == 'matched' and matched['matched'], matched
        await expect(page.locator('#stage-3')).to_be_visible()

        for language, copy in COPY.items():
            if language != current_language:
                await page.locator('nav a[data-nav="account"]').click()
                await page.locator('#hz-lang-select').select_option(language)
                await page.locator('nav a[data-nav="map"]').click()
                current_language = language
            await expect(page.locator('#stage-3')).to_be_visible()
            await expect(page.locator('#match-status-title')).to_have_text(copy['title'])
            await expect(page.locator('#match-status-description')).to_have_text(copy['description'])
            stage_text = await page.locator('#stage-3').inner_text()
            for claim in copy['forbidden']:
                assert claim not in stage_text, f'unsupported route/ETA/identity claim remains in {language}: {claim}'
            matched_icons = await page.locator('#stage-3 .material-symbols-outlined').all_text_contents()
            assert 'verified' not in matched_icons, 'a static translator verification badge remains'
            assert await page.locator('#stage-3 .animate-ping, #stage-3 .animate-pulse, #stage-3 .bg-emerald-500').count() == 0, 'a fake live movement/presence indicator remains'
            await expect(page.locator('#btn-arrived')).to_be_visible()
            await expect(page.locator('#btn-arrived > span:last-child')).to_have_text(copy['arrived'])
            print(f'PASS [{width}/{language}]: server-confirmed match; no fabricated verification badge; arrival remains explicit')
        assert not errors, errors
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        if page:
            try:
                await page.screenshot(path=str(ARTIFACTS / f'failure-{width}.png'), full_page=True)
                (ARTIFACTS / f'failure-{width}.html').write_text(await page.content())
            except Exception:
                pass
        raise
    finally:
        if created and session:
            try:
                await api(context.request, 'POST', f"/traveler/bookings/{created['id']}/cancel", session['token'])
            except Exception:
                pass
        await context.close()


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=['--no-sandbox'])
        try:
            await scenario(browser, 390)
            await scenario(browser, 1280)
        finally:
            await browser.close()
    print('RESULT: PASS (2 viewports; 6 language/viewport combinations per booking state)')


asyncio.run(main())
