"""Booking-form regression: selected options must reach storage and matching.

All booking/auth/matching requests use the real disposable HZ_DEV server. Only
public map services are stubbed. Scheduled cases set the browser clock to the
next day's midnight so the existing date picker is deterministic, including on
the last day of a month. The server clock is never changed.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_booking_options'
SCHEDULE_SEARCH_COPY = {
    'fa': 'برای رزرو زمان‌دار، جست‌وجوی مترجم یک ساعت پیش از زمان انتخابی آغاز می‌شود. اگر تا ۱۵ دقیقه مانده مترجمی نپذیرد، وضعیت رزرو در برنامه به‌روزرسانی می‌شود.',
    'en': 'For a scheduled booking, interpreter search starts one hour before the selected time. If no interpreter has accepted by the 15-minute mark, the app updates the booking status.',
    'ar': 'في الحجز المجدول، يبدأ البحث عن مترجم قبل الموعد المحدد بساعة. إذا لم يقبل أي مترجم قبل ۱۵ دقيقة من الموعد، يحدّث التطبيق حالة الحجز.',
}
TIME_SLOT_WINDOW_COPY = {
    'fa': 'ساعت‌های فهرست‌شده: ۸ صبح تا ۹ شب',
    'en': 'Listed time slots: 8:00 AM–9:00 PM',
    'ar': 'الأوقات المدرجة: ٨:٠٠ صباحاً–٩:٠٠ مساءً',
}
TIME_SLOT_STEP_COPY = {
    'fa': 'انتخاب زمان با گام‌های ۳۰ دقیقه‌ای',
    'en': 'Select a time in 30-minute increments',
    'ar': 'اختر الوقت بفواصل ٣٠ دقيقة',
}
TIME_SLOT_FIRST_COPY = {'fa': '۰۸:۰۰ صبح', 'en': '8:00 AM', 'ar': '٨:٠٠ صباحاً'}
TIME_SLOT_LAST_COPY = {'fa': '۲۱:۰۰ شب', 'en': '9:00 PM', 'ar': '٩:٠٠ مساءً'}
INSTANT_MODE_COPY = {
    'fa': 'درخواست مترجم (اکنون)',
    'en': 'Request an interpreter now',
    'ar': 'طلب مترجم الآن',
}
INSTANT_SUBMIT_COPY = {
    'fa': 'ثبت درخواست مترجم',
    'en': 'Submit interpreter request',
    'ar': 'إرسال طلب مترجم',
}


async def login(request, role):
    phone = '9' + str(secrets.randbelow(900000000) + 100000000)
    await api(request, 'POST', '/auth/request-code', data={'phone': phone, 'role': role})
    result = await api(request, 'POST', '/auth/verify',
                       data={'phone': phone, 'role': role, 'code': '123456'})
    return result['token'], phone


async def translator(request, gender):
    token, _ = await login(request, 'translator')
    await api(request, 'POST', '/dev/approve-translator', token)
    await api(request, 'PATCH', '/translator/online', token,
              {'online': True, 'gender': gender, 'accept_any': False})
    return token


async def scenario(browser, kind, preference, lang):
    label = f'{kind}-{preference}-{lang}'
    ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                    timezone_id='UTC', service_workers='block')
    page = await ctx.new_page()
    page.set_default_timeout(20000)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        await api(ctx.request, 'POST', '/dev/offline-all')
        config = await api(ctx.request, 'GET', '/config')
        # Register the wrong candidate first: a silent fallback to 'any' would
        # offer a female-preference booking to the male traveler’s male candidate.
        wanted = 'female' if preference == 'female' else 'male'
        opposite = 'male' if wanted == 'female' else 'female'
        wrong = await translator(ctx.request, opposite)
        right = await translator(ctx.request, wanted)
        ptok, phone = await login(ctx.request, 'traveler')
        user = {'name': 'علی', 'last': 'رضایی', 'gender': 'مرد', 'phone': phone, 'lang': lang}
        await ctx.add_init_script(
            'localStorage.setItem("hamzaban.token.v1", ' + json.dumps(ptok) + ');'
            'localStorage.setItem("hamzaban.user.v1", ' + json.dumps(json.dumps(user)) + ');'
            'localStorage.setItem("hamzaban_lang", ' + json.dumps(lang) + ');')
        await ctx.route('https://nominatim.openstreetmap.org/**',
                        lambda route: route.fulfill(json={'display_name': 'تهران، آزمون گزینه‌های رزرو'}))
        await ctx.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
        if kind == 'scheduled':
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            await page.clock.install(time=tomorrow)
        await page.goto(BASE + '/traveler/app.html')
        await expect(page.locator('#selected-location-title')).to_have_text('تهران، آزمون گزینه‌های رزرو')
        # Wait for live tariffs before comparing the UI estimate to the server total.
        await page.wait_for_function('() => typeof window.HZ_APPLY_CFG === "function" && !!window.HZ_NEAREST_CITY()')
        await expect(page.locator('#match-chance')).to_have_count(0)
        await page.locator('#confirm-location-btn').click()
        await expect(page.locator('#bottom-sheet')).to_be_visible()
        await expect(page.locator('#btn-mode-instant > span:last-child')).to_have_text(INSTANT_MODE_COPY[lang])
        await expect(page.locator('#txt-main-submit')).to_have_text(INSTANT_SUBMIT_COPY[lang])
        await page.locator('.cat-chip[data-cat=business]').click()
        await page.locator('#btn-inc-hours').click()  # 2 -> 3 hours
        await page.locator('#btn-inc-pax').click()  # 1 -> 2 passengers
        has_car = kind == 'scheduled'
        if not has_car:
            await page.locator('#btn-toggle-car').click()  # Default car -> pedestrian
        # Change away and back, including the 'any' case: the last selection wins.
        alternate = 'male' if preference != 'male' else 'female'
        await page.locator(f'.gender-btn[data-gender={alternate}]').click()
        await page.locator(f'.gender-btn[data-gender={preference}]').click()
        await expect(page.locator(f'.gender-btn[data-gender={preference}]')).to_have_attribute('aria-pressed', 'true')
        notes = f'گزینه‌های رزرو {label}'
        await page.locator('#notes-input').fill(notes)
        if kind == 'scheduled':
            await page.locator('#btn-mode-scheduled').click()
            await expect(page.locator('#scheduled-panel')).to_be_visible()
            await expect(page.locator('#scheduled-search-policy')).to_have_text(SCHEDULE_SEARCH_COPY[lang])
            await page.locator('#btn-open-timepicker').click()
            await expect(page.locator('#modal-timepicker')).to_be_visible()
            await expect(page.locator('#time-slot-step-policy')).to_have_text(TIME_SLOT_STEP_COPY[lang])
            await expect(page.locator('#time-selection-window-label')).to_have_text(TIME_SLOT_WINDOW_COPY[lang])
            slots = await page.locator('#time-slots-container button').all_text_contents()
            assert len(slots) == 27, (label, len(slots), slots)
            await expect(page.locator('#time-slots-container button').first).to_have_text(TIME_SLOT_FIRST_COPY[lang])
            await expect(page.locator('#time-slots-container button').last).to_have_text(TIME_SLOT_LAST_COPY[lang])
            await page.locator('#btn-cancel-time').click()
            await page.locator('#btn-mode-instant').click()
            await expect(page.locator('#scheduled-panel')).to_be_hidden()
            await expect(page.locator('#txt-main-submit')).to_have_text(INSTANT_SUBMIT_COPY[lang])
            await page.locator('#btn-mode-scheduled').click()
            await expect(page.locator('#scheduled-panel')).to_be_visible()
            await expect(page.locator('#scheduled-search-policy')).to_have_text(SCHEDULE_SEARCH_COPY[lang])
            await expect(page.locator('#match-chance')).to_have_count(0)
        # Read-only view of the form state; submission itself uses a real click.
        estimate = await page.evaluate('() => window.getBookingPricing(false).total')
        async with page.expect_response(lambda r: r.url.endswith('/api/traveler/bookings')
                                         and r.request.method == 'POST') as result:
            await page.locator('#btn-main-submit').click()
        response = await result.value
        assert response.status == 201, await response.text()
        sent = response.request.post_data_json
        for key, expected in {'kind': kind, 'gender_pref': preference, 'traveler_gender': 'male',
                              'category': 'business', 'hours': 3, 'car': has_car,
                              'party': 2, 'notes': notes, 'origin_lang': 'ar', 'dest_lang': 'fa'}.items():
            assert sent.get(key) == expected, (label, key, sent.get(key), expected)
        created = await response.json()
        stored = await booking(ctx.request, ptok, created['id'])
        assert stored['gender_pref'] == preference and stored['hours'] == 3, stored
        assert stored['field'] == 'business' and stored['notes'] == notes, stored
        assert stored['lat'] == sent['lat'] and stored['lng'] == sent['lng'], stored
        rates = config['tariffs']
        base = (rates['hourly']['business'] + int(has_car) * rates['car_fee_per_hour']) * 3
        tax = int(base * rates['tax_percent'] / 100 + 0.5)
        assert stored['base'] == base and stored['tax'] == tax, stored
        assert stored['total'] == base + tax == estimate, (stored, estimate)
        if kind == 'instant':
            assert stored['status'] == 'searching', stored
            other_offers = await api(ctx.request, 'GET', '/translator/offers', wrong)
            right_offers = await api(ctx.request, 'GET', '/translator/offers', right)
            assert not other_offers['offers'], (label, other_offers)
            assert len(right_offers['offers']) == 1, (label, right_offers)
            assert right_offers['offers'][0]['notes'] == notes, right_offers
            # Verify assignment too, not merely that the proper candidate sees an offer.
            await api(ctx.request, 'POST', f"/translator/offers/{right_offers['offers'][0]['id']}/accept", right)
            assert (await booking(ctx.request, ptok, stored['id']))['matched'] is True
        else:
            assert stored['status'] == 'waiting_schedule' and not stored['matched'], stored
            assert stored['scheduled_at'] == sent['scheduled_at'], (stored, sent)
        cancelled = await api(ctx.request, 'POST', f"/traveler/bookings/{stored['id']}/cancel", ptok)
        assert cancelled['ok'], cancelled
        assert not errors, errors
        print(f'PASS: {label}; selected options, full price and assignment verified')
    except Exception:
        print(label, 'JavaScript errors:', errors)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(ARTIFACTS / f'{label}.png'), full_page=True)
        except Exception:
            pass
        raise
    finally:
        await ctx.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        try:
            for kind in ('instant', 'scheduled'):
                for preference, lang in (('female', 'fa'), ('male', 'en'), ('any', 'ar')):
                    await scenario(browser, kind, preference, lang)
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
