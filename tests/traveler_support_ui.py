"""No fake calling/sharing/emergency success; support uses fresh admin config.

Real matching and settings APIs; config failures are intercepted deliberately.
Never actually invokes a telephone handler. Covers all three support entry points,
fa/en/ar, blank/invalid/updated phone numbers, safe tel links and cancellation.
"""
import asyncio
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api
from logout_sessions_ui import sign_in, seeded_context
from booking_options_ui import translator

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_support'
COPY = {
    'fa': {
        'warning': 'این دکمه هشدار اضطراری ارسال نمی‌کند. در خطر فوری، با خدمات اضطراری محل تماس بگیرید.',
        'unavailable': 'تماس امن، پیامک با مترجم و ردیابی زنده هنوز فعال نیستند.',
        'empty': 'شمارهٔ پشتیبانی هنوز در پنل مدیریت تنظیم نشده است.',
        'invalid': 'شمارهٔ پشتیبانی ثبت‌شده معتبر نیست؛ امکان تماس از این بخش وجود ندارد.',
        'error': 'شمارهٔ پشتیبانی دریافت نشد. دوباره تلاش کنید.',
        'ready': 'شمارهٔ پشتیبانی از تنظیمات مدیر دریافت شد.',
    },
    'en': {
        'warning': 'This button does not send an emergency alert. In immediate danger, contact local emergency services.',
        'unavailable': 'Secure calls, translator messaging and live tracking are not available yet.',
        'empty': 'No support phone number has been configured by the administrator yet.',
        'invalid': 'The configured support phone number is invalid; calling is unavailable here.',
        'error': 'Could not load the support phone number. Please try again.',
        'ready': 'The support phone number was loaded from administrator settings.',
    },
    'ar': {
        'warning': 'هذا الزر لا يرسل بلاغ طوارئ. عند وجود خطر فوري، اتصل بخدمات الطوارئ المحلية.',
        'unavailable': 'المكالمات الآمنة ومراسلة المترجم والتتبع المباشر غير متاحة حالياً.',
        'empty': 'لم يُضبط رقم هاتف الدعم في لوحة الإدارة بعد.',
        'invalid': 'رقم هاتف الدعم المسجّل غير صالح؛ الاتصال غير متاح هنا.',
        'error': 'تعذّر تحميل رقم هاتف الدعم. يرجى المحاولة مرة أخرى.',
        'ready': 'تم تحميل رقم هاتف الدعم من إعدادات المدير.',
    },
}


async def scenario(browser, setup, admin, lang):
    ctx, page, errors = None, None, []
    release = asyncio.Event()
    try:
        async def settings(number):
            await api(setup.request, 'PUT', '/admin/settings', admin, {'support_phone': number})
        await settings('')
        await api(setup.request, 'POST', '/dev/offline-all')
        session = await sign_in(setup.request, '9' + str(secrets.randbelow(900000000) + 100000000))
        ttok = await translator(setup.request, 'male')
        ctx, page = await seeded_context(browser, session, lang, errors)
        await page.locator('nav a[data-nav=map]').click()
        await page.wait_for_function('() => !!window.HZ_NEAREST_CITY()')
        await expect(page.locator('#selected-location-title')).to_have_text('تهران، آزمون خروج')
        await page.locator('#confirm-location-btn').click()
        await expect(page.locator('#bottom-sheet')).to_be_visible()
        await page.locator('#btn-toggle-car').click()
        async with page.expect_response(lambda r: r.url.endswith('/api/traveler/bookings') and r.request.method == 'POST') as response:
            await page.locator('#btn-main-submit').click()
        result = await response.value
        assert result.status == 201, await result.text()
        created = await result.json()
        offers = await api(setup.request, 'GET', '/translator/offers', ttok)
        await api(setup.request, 'POST', f"/translator/offers/{offers['offers'][0]['id']}/accept", ttok)
        await expect(page.locator('#stage-3')).to_be_visible()
        mutations = []
        page.on('request', lambda r: mutations.append(r.url) if '/api/' in r.url and r.method in ['POST', 'PUT', 'PATCH', 'DELETE'] else None)
        await expect(page.locator('#trip-contact-unavailable')).to_have_text(COPY[lang]['unavailable'])
        for id in ['btn-call-masked', 'btn-chat-inapp', 'btn-share-ride']:
            await expect(page.locator('#' + id)).to_be_disabled()
            await expect(page.locator('#' + id)).to_have_attribute('aria-describedby', 'trip-contact-unavailable')
        await page.evaluate("""() => {
            window.safetyToasts = []; window.clipboardWrites = [];
            const old = window.showAppToast;
            window.showAppToast = (message, icon) => { safetyToasts.push(message); old(message, icon); };
            Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText:async value=>clipboardWrites.push(value)}});
            ['btn-call-masked','btn-chat-inapp','btn-share-ride'].forEach(id => document.getElementById(id)
                .dispatchEvent(new MouseEvent('click', {bubbles:true})));
        }""")
        assert await page.evaluate('() => safetyToasts') == []
        assert await page.evaluate('() => clipboardWrites') == []

        dialog = page.locator('#support-dialog')
        async def open_from(id):
            await page.locator('#' + id).click()
            await expect(dialog).to_be_visible()
            await expect(page.locator('#support-safety-note')).to_have_text(COPY[lang]['warning'])
        async def status(key):
            await expect(page.locator('#support-status')).to_have_text(COPY[lang][key])
            await expect(page.locator('#support-retry')).to_be_enabled()
        async def no_call():
            await expect(page.locator('#support-call')).to_be_hidden()
            assert await page.locator('#support-call').get_attribute('href') is None
        await open_from('btn-quick-support')
        await status('empty')
        await no_call()
        await page.keyboard.press('Escape')
        await expect(dialog).to_be_hidden()
        await expect(page.locator('#btn-quick-support')).to_be_focused()
        await settings('+98 (21) 1234-5678')
        await open_from('btn-safety-support')
        await status('ready')
        await expect(page.locator('#support-call')).to_have_attribute('href', 'tel:+982112345678')
        await expect(page.locator('#support-call')).to_be_visible()
        # Updating settings while already open must replace, not cache, the number.
        await settings('۰۲۱ ۱۲۳۴۵۶۷۸')
        await page.locator('#support-retry').click()
        await status('ready')
        await expect(page.locator('#support-call')).to_have_attribute('href', 'tel:02112345678')
        for invalid in ['javascript:alert(1)', '+98;ext=1', '*123#', '<img src=x onerror=alert(1)>']:
            await settings(invalid)
            await page.locator('#support-retry').click()
            await status('invalid')
            await no_call()
        await page.locator('#support-close').click()
        await expect(dialog).to_be_hidden()
        await settings('+442079460123')
        await open_from('btn-sos')
        await status('ready')
        await expect(page.locator('#support-call')).to_have_attribute('href', 'tel:+442079460123')
        # Native modal keyboard containment and closing are usable without a mouse.
        for _ in range(4):
            await page.keyboard.press('Tab')
        assert await page.evaluate("() => !!document.activeElement.closest('#support-dialog')")
        await page.keyboard.press('Escape')
        await expect(dialog).to_be_hidden()
        await expect(page.locator('#btn-sos')).to_be_focused()

        async def offline(route):
            await route.abort('internetdisconnected')
        await page.route('**/api/config', offline)
        await open_from('btn-quick-support')
        await status('error')
        await no_call()
        await page.unroute('**/api/config', offline)
        await page.locator('#support-retry').click()
        await status('ready')
        async def malformed(route):
            await route.fulfill(json={'support_phone': False})
        await page.route('**/api/config', malformed)
        await page.locator('#support-retry').click()
        await status('error')
        await no_call()
        await page.unroute('**/api/config', malformed)
        await page.locator('#support-close').click()
        # Closing an in-flight request must not block a fresh opening or restore
        # a stale number when the older response finally completes.
        arrived, completed = asyncio.Event(), asyncio.Event()
        async def delayed(route):
            arrived.set()
            await release.wait()
            try:
                await route.fulfill(json={'support_phone': '99999999'})
            finally:
                completed.set()
        await page.route('**/api/config', delayed)
        await open_from('btn-sos')
        await asyncio.wait_for(arrived.wait(), 20)
        await page.locator('#support-close').click()
        # The canceled request may reject fulfillment; let Playwright retire its
        # handler rather than swallowing its error and leaking its handled future.
        await page.unroute_all(behavior='ignoreErrors')
        await settings('+33123456789')
        await open_from('btn-quick-support')
        await status('ready')
        release.set()
        await asyncio.wait_for(completed.wait(), 20)
        await expect(page.locator('#support-call')).to_have_attribute('href', 'tel:+33123456789')
        assert not mutations, mutations
        assert await page.evaluate('() => safetyToasts') == []
        assert not errors, errors
        print(f'PASS [{lang}]: no fake call/SMS/sharing/SOS; all support entry points, validated fresh numbers, safe failure/retry and modal cancellation work')
        await api(setup.request, 'POST', f"/traveler/bookings/{created['id']}/cancel", session['token'])
    except Exception:
        print('JavaScript errors:', errors)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        if page:
            await page.screenshot(path=str(ARTIFACTS / f'support-{lang}.png'), full_page=True)
        raise
    finally:
        release.set()
        if ctx:
            await page.unroute_all(behavior='wait')
            await ctx.unroute_all(behavior='wait')
            await ctx.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        setup = await browser.new_context()
        original = (await api(setup.request, 'GET', '/config'))['support_phone']
        admin = (await api(setup.request, 'POST', '/admin/login', data={'password': 'test-admin-pass'}))['token']
        try:
            for lang in ['fa', 'en', 'ar']:
                await scenario(browser, setup, admin, lang)
        finally:
            await api(setup.request, 'PUT', '/admin/settings', admin, {'support_phone': original})
            await setup.close()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
