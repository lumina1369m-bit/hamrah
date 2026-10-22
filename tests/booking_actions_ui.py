"""Server-confirmed creation/cancellation/retry/conversion, fa/en/ar.

Requires a separate disposable HZ_DEV=1, HZ_TIME_SCALE=0.01 server (8082 by
 default). Real expiry supplies no_match; no fake matching/status API is used.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
from playwright.async_api import async_playwright, expect

BASE = os.environ.get('BOOKING_ACTION_BASE', 'http://127.0.0.1:8082').rstrip('/')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_booking_actions'
FAILURE = {
    'fa': 'عملیات رزرو تأیید نشد. وضعیت را بررسی کنید و دوباره تلاش کنید.',
    'en': 'The booking action was not confirmed. Check its status and try again.',
    'ar': 'لم يتم تأكيد إجراء الحجز. تحقّق من حالته وحاول مجدداً.',
}
CREATE_FAILURE = {
    'fa': 'ثبت رزرو تأیید نشد. پیش از تلاش دوباره، فهرست رزروها را بررسی کنید.',
    'en': 'Booking creation was not confirmed. Check your bookings before trying again.',
    'ar': 'لم يتم تأكيد إنشاء الحجز. تحقّق من حجوزاتك قبل المحاولة مجدداً.',
}
REQUIRED = {
    'fa': 'برای این کار، ورود و رزرو معتبر سروری لازم است.',
    'en': 'This action requires sign-in and a valid server booking.',
    'ar': 'يتطلب هذا الإجراء تسجيل الدخول وحجزاً صالحاً على الخادم.',
}
CANCELLED = {
    'fa': 'لغو رزرو در سرور تأیید شد.',
    'en': 'Booking cancellation was confirmed by the server.',
    'ar': 'تم تأكيد إلغاء الحجز من الخادم.',
}
RETRIED = {
    'fa': 'جستجوی دوباره در سرور تأیید شد.',
    'en': 'The new search was confirmed by the server.',
    'ar': 'تم تأكيد البحث مجدداً من الخادم.',
}


async def api(request, method, path, token=None, data=None, status=200):
    r = await request.fetch(BASE + '/api' + path, method=method, data=data,
                            headers={'Authorization': 'Bearer ' + token} if token else {})
    body = await r.json()
    assert r.status == status, (method, path, r.status, body)
    return body


async def login(request):
    phone = '9' + str(secrets.randbelow(900000000) + 100000000)
    await api(request, 'POST', '/auth/request-code', data={'phone': phone, 'role': 'traveler'})
    return await api(request, 'POST', '/auth/verify', data={'phone': phone, 'role': 'traveler', 'code': '123456'})


async def scenario(browser, lang):
    setup = await browser.new_context()
    ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block', timezone_id='UTC')
    await ctx.route('https://nominatim.openstreetmap.org/**', lambda r: r.fulfill(json={'display_name': 'تهران، آزمون عملیات رزرو'}))
    await ctx.route('https://*.tile.openstreetmap.org/**', lambda r: r.abort())
    page = await ctx.new_page()
    page.set_default_timeout(20000)
    errors, posts = [], []
    release = asyncio.Event()
    stale_release = asyncio.Event()
    clock_installed = False
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and '/api/traveler/bookings' in r.url else None)
    try:
        await api(setup.request, 'POST', '/dev/offline-all')
        session = await login(setup.request)
        token = session['token']
        await page.goto(BASE + '/traveler/index.html')
        await page.evaluate("""([s, lang]) => {
            localStorage.setItem('hamzaban.token.v1', s.token);
            localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'Ali', last:'Rezaei', gender:'مرد', phone:s.user.phone, authUserId:s.user.id}));
            localStorage.setItem('hamzaban.bookings.v1','[]'); localStorage.setItem('hamzaban_lang',lang);
        }""", [session, lang])
        await page.goto(BASE + '/traveler/app.html')
        await page.wait_for_function('() => window.hzBookingsSynced === true && !!window.HZ_NEAREST_CITY()')
        await expect(page.locator('#selected-location-title')).to_have_text('تهران، آزمون عملیات رزرو')
        await page.locator('#confirm-location-btn').click()
        await page.locator('#btn-toggle-car').click()
        submit = page.locator('#btn-main-submit')

        async def local_booking(id):
            return await page.evaluate("id => JSON.parse(localStorage.getItem('hamzaban.bookings.v1') || '[]').find(b => b.serverId === id)", id)

        async def server_booking(id):
            return next(b for b in (await api(setup.request, 'GET', '/traveler/bookings', token))['bookings'] if b['id'] == id)

        async def create():
            async with page.expect_response(lambda r: r.url == BASE + '/api/traveler/bookings' and r.request.method == 'POST') as pending:
                await submit.click()
            response = await pending.value
            assert response.status == 201, await response.text()
            booking = await response.json()
            await expect(page.locator('#stage-2')).to_be_visible()
            assert (await local_booking(booking['id']))['serverId'] == booking['id']
            return booking['id']

        # Profile-only and unconfirmed responses cannot manufacture reservations.
        await page.evaluate("localStorage.removeItem('hamzaban.token.v1')")
        await submit.click()
        await expect(page.locator('#toast-text')).to_have_text(REQUIRED[lang])
        assert not posts
        await expect(page.locator('#stage-1')).to_be_visible()
        await page.evaluate("t => localStorage.setItem('hamzaban.token.v1', t)", token)

        async def faults(url, button, message, *, cancelling=False):
            cases = ['offline', '503', 'empty', 'false', 'string', 'malformed']
            if cancelling:
                cases += ['fee_missing', 'fee_invalid']
            for mode in cases:
                async def failure(route, request, *, mode=mode):
                    if request.method != 'POST':
                        await route.fallback()
                    elif mode == 'offline':
                        await route.abort('failed')
                    elif mode == 'malformed':
                        await route.fulfill(status=200, content_type='application/json', body='{')
                    else:
                        payload = {'503': {'error':'unavailable'}, 'empty':{}, 'false':{'ok':False}, 'string':{'ok':'true'}, 'fee_missing':{'ok':True}, 'fee_invalid':{'ok':True,'fee_percent':-1}}[mode]
                        await route.fulfill(status=503 if mode == '503' else 200, json=payload)
                await page.route(url, failure)
                await button.dispatch_event('click')
                await expect(button).to_be_enabled()
                await expect(page.locator('#toast-text')).to_have_text(message)
                await page.unroute(url, failure)

        async def timeout(url, button, message):
            nonlocal clock_installed
            if not clock_installed:
                await page.clock.install()
                clock_installed = True
            await page.evaluate("""url => {
                window.actionTestFetch = window.fetch; window.actionTestAborted = false;
                window.fetch = (path, options) => {
                    if (path === url && options.method === 'POST') return new Promise((resolve,reject) =>
                        options.signal.addEventListener('abort', () => {
                            window.actionTestAborted = true; reject(new DOMException('Aborted','AbortError'));
                        }, {once:true}));
                    return window.actionTestFetch(path, options);
                };
            }""", url)
            await button.dispatch_event('click')
            await expect(button).to_be_disabled()
            await page.clock.fast_forward(10001)
            await expect(button).to_be_enabled()
            await expect(page.locator('#toast-text')).to_have_text(message)
            assert await page.evaluate('window.actionTestAborted')
            await page.evaluate('window.fetch = window.actionTestFetch')
            await page.clock.resume()

        await faults('**/api/traveler/bookings', submit, CREATE_FAILURE[lang])
        await timeout('/api/traveler/bookings', submit, CREATE_FAILURE[lang])
        assert not (await api(setup.request, 'GET', '/traveler/bookings', token))['bookings']
        assert await page.evaluate("localStorage.getItem('hamzaban.bookings.v1')") == '[]'
        await expect(page.locator('#stage-1')).to_be_visible()

        # A single pending creation cannot be duplicated by synthetic clicks.
        entered = asyncio.Event()
        async def delayed(route):
            entered.set()
            await release.wait()
            await route.continue_()
        await page.route('**/api/traveler/bookings', delayed)
        before = len(posts)
        await submit.click()
        await entered.wait()
        await expect(submit).to_be_disabled()
        await expect(submit).to_have_attribute('aria-busy','true')
        await submit.dispatch_event('click')
        assert len(posts) == before + 1
        await expect(page.locator('#stage-1')).to_be_visible()
        async with page.expect_response(lambda r: r.url == BASE + '/api/traveler/bookings' and r.request.method == 'POST') as pending:
            release.set()
        bid = (await (await pending.value).json())['id']
        await page.unroute('**/api/traveler/bookings', delayed)
        await expect(page.locator('#stage-2')).to_be_visible()

        cancel = page.locator('#btn-cancel-search')
        await faults(f'**/api/traveler/bookings/{bid}/cancel', cancel, FAILURE[lang], cancelling=True)
        await timeout(f'/api/traveler/bookings/{bid}/cancel', cancel, FAILURE[lang])
        assert (await server_booking(bid))['status'] != 'cancelled'
        assert (await local_booking(bid))['tab'] != 'cancelled'
        await expect(page.locator('#stage-1')).to_be_hidden()

        # Real expiry (six seconds) drives the no-match state and retry endpoint.
        await expect(page.locator('#nomatch-block')).to_be_visible(timeout=25000)
        assert (await server_booking(bid))['status'] == 'no_match'
        retry = page.locator('#btn-retry-search')
        await faults(f'**/api/traveler/bookings/{bid}/retry', retry, FAILURE[lang])
        await expect(page.locator('#nomatch-block')).to_be_visible()
        assert (await server_booking(bid))['status'] == 'no_match'
        release.clear(); entered.clear()
        await page.route(f'**/api/traveler/bookings/{bid}/retry', delayed)
        before = len(posts)
        await retry.click(); await entered.wait()
        await expect(retry).to_be_disabled()
        for id in ['btn-retry-search','btn-cancel-nomatch','btn-to-scheduled','btn-main-submit']:
            await page.locator('#'+id).dispatch_event('click')
        assert len(posts) == before + 1
        await expect(page.locator('#nomatch-block')).to_be_visible()
        release.set()
        await expect(page.locator('#stage-2')).to_be_visible()
        await expect(page.locator('#toast-text')).to_have_text(RETRIED[lang])
        await page.unroute(f'**/api/traveler/bookings/{bid}/retry', delayed)
        assert (await server_booking(bid))['status'] == 'searching'

        # Cancellation is shared across map and rebuilt booking cards.
        stale_entered, stale_completed = asyncio.Event(), asyncio.Event()
        async def stale_poll(route, request):
            if request.method != 'GET' or stale_entered.is_set():
                await route.fallback(); return
            response = await route.fetch()
            snapshot = await response.json()
            stale_entered.set()
            await stale_release.wait()
            try:
                await route.fulfill(json=snapshot)
            finally:
                stale_completed.set()
        await page.route('**/api/traveler/bookings', stale_poll)
        release.clear(); entered.clear()
        await page.route(f'**/api/traveler/bookings/{bid}/cancel', delayed)
        before = len(posts)
        await cancel.click(); await entered.wait()
        await page.clock.fast_forward(5001)
        await page.clock.resume()
        await stale_entered.wait()
        await cancel.dispatch_event('click')
        await page.locator('nav a[data-nav=bookings]').click()
        card = page.locator(f'article[data-booking-id="{bid}"]')
        for button in await card.locator('.b-act button').all():
            await expect(button).to_be_disabled()
            await button.dispatch_event('click')
        assert len(posts) == before + 1
        assert (await local_booking(bid))['tab'] != 'cancelled'
        release.set()
        await expect(page.locator('#toast-text')).to_have_text(CANCELLED[lang])
        await page.unroute(f'**/api/traveler/bookings/{bid}/cancel', delayed)
        stale_release.set()
        await stale_completed.wait()
        await page.unroute('**/api/traveler/bookings', stale_poll)
        assert (await server_booking(bid))['status'] == 'cancelled'
        assert (await local_booking(bid))['cancelFee'] == 0
        await page.locator('nav a[data-nav=map]').click()
        await expect(page.locator('#stage-1')).to_be_visible()

        # The no-match conversion button edits this reservation, not a new form.
        bid2 = await create()
        await expect(page.locator('#nomatch-block')).to_be_visible(timeout=25000)
        await page.locator('#btn-to-scheduled').click()
        await expect(page.locator('#bk-modal')).to_be_visible()
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime('%Y-%m-%d')
        await page.locator('#bk-modal input[type=date]').fill(tomorrow)
        conversion = page.locator('#bk-modal button').last
        await faults(f'**/api/traveler/bookings/{bid2}/convert', conversion, FAILURE[lang])
        await expect(page.locator('#bk-modal')).to_be_visible()
        assert (await server_booking(bid2))['kind'] == 'instant'
        await conversion.click()
        await expect(page.locator('#bk-modal')).to_have_count(0)
        await expect(page.locator('#stage-1')).to_be_visible()
        converted = await server_booking(bid2)
        assert converted['kind'] == 'scheduled' and converted['status'] == 'waiting_schedule'
        assert (await local_booking(bid2))['mode'] == 'scheduled'
        await api(setup.request,'POST',f'/traveler/bookings/{bid2}/cancel',token)
        # An old account's real cancellation response cannot mutate a new login.
        bid3 = await create()
        replacement = await login(setup.request)
        release.clear(); entered.clear()
        await page.route(f'**/api/traveler/bookings/{bid3}/cancel', delayed)
        await page.locator('#btn-cancel-search').click(); await entered.wait()
        await page.evaluate("""s => {
            localStorage.setItem('hamzaban.token.v1',s.token);
            localStorage.setItem('hamzaban.user.v1',JSON.stringify({name:'New',last:'Account',gender:'مرد',phone:s.user.phone,authUserId:s.user.id}));
            localStorage.setItem('hamzaban.bookings.v1','[]');
            document.getElementById('toast-text').textContent = '';
        }""", replacement)
        release.set()
        await expect(page.locator('#btn-cancel-search')).to_be_enabled()
        assert await page.evaluate("localStorage.getItem('hamzaban.token.v1')") == replacement['token']
        assert await page.evaluate("localStorage.getItem('hamzaban.bookings.v1')") == '[]'
        assert (await server_booking(bid3))['status'] == 'cancelled'
        assert await page.locator('#toast-text').inner_text() != CANCELLED[lang]
        # Local-only historical entries are read-only, not fake server bookings.
        await page.evaluate("""() => localStorage.setItem('hamzaban.bookings.v1',JSON.stringify([
            {id:'legacy',title:'legacy-entry-no-server',tab:'pending',statusLabel:'cached',startAt:Date.now()+300000,rate:100}
        ]))""")
        await page.locator('nav a[data-nav=bookings]').click()
        legacy = page.locator('article').filter(has_text='legacy-entry-no-server')
        await expect(legacy).to_be_visible()
        await expect(legacy.locator('button')).to_have_count(0)
        assert not errors, errors
        print(f'PASS [{lang}]: real creation/cancel/retry/conversion, all failure modes, no optimistic navigation/local success, serialized map/card actions, timeout, stale-poll and session isolation, read-only legacy entries and real expiry')
    except Exception:
        print('JavaScript errors:', errors)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(ARTIFACTS / f'{lang}.png'), full_page=True)
        raise
    finally:
        release.set(); stale_release.set()
        await page.unroute_all(behavior='ignoreErrors')
        await ctx.close()
        await setup.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        for lang in ['fa','en','ar']:
            await scenario(browser,lang)
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
