"""Pre-start cancellation needs an explicit receipt and private committed history."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import secrets
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking, arrive_and_start
from booking_options_ui import login, translator
from hz_api import LOGIN_JS

ERROR = 'نتیجهٔ عملیات تأیید نشد. وضعیت مأموریت را بررسی کنید و سپس دوباره تلاش کنید.'
SUCCESS = 'لغو مأموریت شما ثبت شد؛ پیدا شدن مترجم جایگزین هنوز قطعی نیست.'
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_cancel_actions'


async def scenario(browser):
    ctx = await browser.new_context(viewport={'width': 390, 'height': 900}, service_workers='block')
    page = await ctx.new_page()
    page.set_default_timeout(20000)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        await api(ctx.request, 'POST', '/dev/offline-all')
        await page.goto(BASE + '/translator/index.html')
        token = await page.evaluate(LOGIN_JS, '9' + str(secrets.randbelow(900000000) + 100000000))
        await api(ctx.request, 'PATCH', '/translator/online', token, {'online': True})
        ptok, _ = await login(ctx.request, 'traveler')

        async def create(label):
            data = {'kind': 'instant', 'origin_lang': 'ar',
                    'dest_lang': 'fa', 'place': label, 'traveler_name': 'آزمون لغو واقعی مترجم'}
            b = await api(ctx.request, 'POST', '/traveler/bookings', ptok, data, status=201)
            o = next(o for o in (await api(ctx.request, 'GET', '/translator/offers', token))['offers'] if o['reservation_id'] == b['id'])
            await api(ctx.request, 'POST', f"/translator/offers/{o['id']}/accept", token)
            return b

        b = await create('لغو اصلی')
        rid = b['id']
        pattern = f'**/api/translator/missions/{rid}/cancel'
        canonical = f'**/api/translator/missions/{rid}/cancellation'
        receipt = {'ok': True, 'reservation_id': rid, 'cancelled_at': datetime.now(timezone.utc).isoformat(), 'reassigned': True}

        def cancel():
            return page.locator('#missions-list').get_by_role('button', name='لغو مأموریت', exact=True)

        async def open_app():
            await page.goto(BASE + '/translator/app.html')
            await expect(cancel()).to_be_visible()
            mission = await api(ctx.request, 'GET', f'/translator/missions/{rid}', token)
            if not mission['arrived_at']:
                arrival = page.locator('#missions-list').get_by_role('button', name='رسیدم به محل ملاقات', exact=True)
                await expect(arrival).to_be_visible()
                await arrival.click()
                await expect(page.locator('#missions-list').get_by_role('button', name='تأیید کد و آغاز همراهی', exact=True)).to_be_visible()
            await page.evaluate('''()=>{window.cancelToasts=[];const toast=HZ.toast;
                HZ.toast=(s)=>{cancelToasts.push(s);toast(s)}}''')

        async def clear():
            await page.evaluate('()=>{cancelToasts=[]}')

        async def failed():
            await page.wait_for_function('(s)=>cancelToasts.includes(s)', arg=ERROR)
            assert not await page.evaluate('(s)=>cancelToasts.includes(s)', SUCCESS)

        await open_app()
        for mode in ('network', 'http', 'html', 'empty', 'partial', 'contradictory'):
            async def fault(route, request, *, mode=mode):
                if mode == 'network': await route.abort()
                elif mode == 'http': await route.fulfill(status=503, json={'error': 'unavailable'})
                elif mode == 'html': await route.fulfill(body='<html>offline</html>')
                else: await route.fulfill(json={} if mode == 'empty' else {'ok': True} if mode == 'partial' else receipt)
            await page.route(pattern, fault)
            await clear()
            await cancel().click()
            await failed()
            await page.unroute_all(behavior='wait')
            await expect(cancel()).to_be_enabled()
            unchanged = await booking(ctx.request, ptok, rid)
            assert unchanged['status'] == 'matched' and unchanged['total'] == b['total']
            print('PASS cancellation', mode)

        posts = 0
        async def no_post(route):
            nonlocal posts
            posts += 1
            await route.abort()
        await page.route(pattern, no_post)
        for patch in ({'reservation_id': rid + 999}, {'cancelled': 'false'}, {'assigned': False},
                      {'cancelled_at': 'invalid'}, {'cancelled': True, 'cancelled_at': receipt['cancelled_at']}):
            async def bad_view(route, request, *, patch=patch):
                response = await route.fetch()
                data = await response.json()
                data.update(patch)
                await route.fulfill(json=data)
            await page.route(canonical, bad_view)
            await clear()
            await cancel().click()
            await failed()
            await page.unroute_all(behavior='wait')
            await page.route(pattern, no_post)
            await expect(cancel()).to_be_enabled()
        assert posts == 0
        await page.unroute_all(behavior='wait')

        # Opposing start and duplicate calendar controls share the reservation lock.
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(route):
            nonlocal posts
            posts += 1
            entered.set()
            await release.wait()
            await route.fulfill(json={})
        await page.route(pattern, held)
        await clear()
        await cancel().click()
        await asyncio.wait_for(entered.wait(), 10)
        await expect(cancel()).to_be_disabled()
        await expect(page.locator('#missions-list').get_by_role('button', name='تأیید کد و آغاز همراهی', exact=True)).to_be_disabled()
        await page.evaluate("()=>document.querySelector('#day-bar button').click()")
        assert await page.locator(f'[data-service-mission="{rid}"]:not(:disabled)').count() == 0
        await page.evaluate('()=>document.querySelectorAll("[data-service-mission]").forEach(b=>b.click())')
        assert posts == 1
        release.set()
        await failed()
        await page.unroute_all(behavior='wait')
        await expect(cancel()).to_be_enabled()

        await page.clock.install()
        await page.evaluate('''(rid)=>{window.cancelRid=rid;window.originalFetch=fetch;window.fetch=(url,opts)=>
            String(url).endsWith('/missions/' + cancelRid + '/cancel') && opts.method==='POST'
            ? (window.cancelStalled=true,new Promise(()=>{})) : originalFetch(url,opts)}''', rid)
        await clear()
        await cancel().click()
        await page.wait_for_function('()=>window.cancelStalled===true')
        await page.clock.run_for(10001)
        await failed()
        await page.evaluate('()=>{window.fetch=originalFetch}')
        await page.clock.resume()
        await expect(cancel()).to_be_enabled()

        other = await translator(ctx.request, 'male')
        await api(ctx.request, 'PATCH', '/translator/online', other, {'online': False})
        entered, release = asyncio.Event(), asyncio.Event()
        async def late(route):
            entered.set()
            await release.wait()
            await route.fulfill(json=receipt)
        await page.route(pattern, late)
        await clear()
        await cancel().click()
        await asyncio.wait_for(entered.wait(), 10)
        await page.evaluate('(t)=>{let s=HZ.load();s.token=t;HZ.save(s)}', other)
        release.set()
        await expect(cancel()).to_be_enabled()
        assert await page.evaluate('()=>cancelToasts.length') == 0
        await page.unroute_all(behavior='wait')
        posts = 0
        await page.route(pattern, no_post)
        await cancel().click()
        await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(resolve))')
        assert posts == 0
        await page.unroute_all(behavior='wait')
        await page.evaluate('(t)=>{let s=HZ.load();s.token=t;HZ.save(s)}', token)
        await open_app()

        # A retained old UI handler is safe; its stale in-flight list cannot restore the released mission.
        entered, release = asyncio.Event(), asyncio.Event()
        once = False
        async def old_list(route):
            nonlocal once
            if once:
                await route.fallback()
                return
            once = True
            response = await route.fetch()
            data = await response.json()
            entered.set()
            await release.wait()
            await route.fulfill(json=data, headers={'x-cancel-old': '1'})
        async def empty_receipt(route):
            await route.fulfill(json={})
        await page.route('**/api/translator/missions', old_list)
        await page.route(pattern, empty_receipt)
        await cancel().evaluate('(b)=>{window.retainedCancel=b}')
        await clear()
        await cancel().click()
        await failed()
        await asyncio.wait_for(entered.wait(), 10)
        await page.unroute(pattern, empty_receipt)
        await clear()
        await page.evaluate('()=>retainedCancel.click()')
        await page.wait_for_function('(s)=>cancelToasts.includes(s)', arg=SUCCESS)
        await expect(cancel()).to_have_count(0)
        async with page.expect_response(lambda r: r.headers.get('x-cancel-old') == '1'):
            release.set()
        await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        await expect(cancel()).to_have_count(0)
        await page.unroute_all(behavior='wait')
        released = await api(ctx.request, 'GET', f'/translator/missions/{rid}/cancellation', token)
        assert released['cancelled'] and not released['assigned'] and released['cancelled_at']
        after = await booking(ctx.request, ptok, rid)
        assert not after['matched'] and after['total'] == b['total'] and not after['service_started']

        await api(ctx.request, 'PATCH', '/translator/online', other, {'online': True})
        replacement = next(o for o in (await api(ctx.request, 'GET', '/translator/offers', other))['offers'] if o['reservation_id'] == rid)
        await api(ctx.request, 'POST', f"/translator/offers/{replacement['id']}/accept", other)
        assert (await api(ctx.request, 'GET', f'/translator/missions/{rid}/cancellation', token)) == released
        await api(ctx.request, 'GET', f'/translator/missions/{rid}', token, status=404)
        replacement_history = await api(ctx.request, 'GET', f'/translator/missions/{rid}/cancellation', other)
        assert replacement_history['cancelled'] is False and replacement_history['assigned'] is True
        await api(ctx.request, 'PATCH', '/translator/online', other, {'online': False})

        b2 = await create('پاسخ لغو گم‌شده')
        await open_app()
        async def lost_receipt(route):
            await route.fetch()
            await route.abort()
        await page.route(f"**/api/translator/missions/{b2['id']}/cancel", lost_receipt)
        await clear()
        await cancel().click()
        await failed()
        await page.unroute_all(behavior='wait')
        assert (await api(ctx.request, 'GET', f"/translator/missions/{b2['id']}/cancellation", token))['cancelled']
        assert not (await booking(ctx.request, ptok, b2['id']))['matched']

        b3 = await create('شروع در دستگاه دیگر')
        await open_app()
        await arrive_and_start(ctx.request, b3['id'], token, b3['service_code'])
        posts = 0
        await page.route(f"**/api/translator/missions/{b3['id']}/cancel", no_post)
        await clear()
        await cancel().click()
        await failed()
        assert posts == 0
        await expect(cancel()).to_have_count(0)
        assert (await booking(ctx.request, ptok, b3['id']))['service_started']
        await page.unroute_all(behavior='wait')
        await api(ctx.request, 'POST', f"/traveler/bookings/{b3['id']}/finish", ptok)

        assert not errors, errors
        print('PASS cancellation: committed release, no replacement promise, unchanged price, faults, shared locks, timeout, session isolation, stale list, lost response and blocked cancellation after start')
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(ARTIFACTS / 'failure.png'), full_page=True)
        raise
    finally:
        await ctx.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        try:
            await scenario(browser)
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
