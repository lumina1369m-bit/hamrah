"""Offer accept/decline: real decisions, private canonical proof and safe faults."""
import asyncio
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking, arrive_and_start
from booking_options_ui import login, translator
from hz_api import LOGIN_JS

ERROR = 'نتیجهٔ عملیات تأیید نشد. وضعیت مأموریت را بررسی کنید و سپس دوباره تلاش کنید.'
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_offer_actions'


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
            b = await api(ctx.request, 'POST', '/traveler/bookings', ptok, {
                'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa', 'place': label,
                'traveler_name': 'آزمون پیشنهاد'}, status=201)
            offers = (await api(ctx.request, 'GET', '/translator/offers', token))['offers']
            return b, next(o for o in offers if o['reservation_id'] == b['id'])

        b, o = await create('پیشنهاد اصلی')
        oid, rid = o['id'], b['id']
        pattern = f'**/api/translator/offers/{oid}'

        def card(offer_id=oid):
            return page.locator(f'[data-offer-id="{offer_id}"]')

        def button(action, offer_id=oid):
            return card(offer_id).get_by_role('button', name='پذیرش' if action == 'accept' else 'رد', exact=True)

        async def open_app():
            await page.goto(BASE + '/translator/app.html')
            await expect(button('accept')).to_be_visible()
            await page.evaluate('''()=>{window.offerToasts=[]; const toast=HZ.toast;
                HZ.toast=(s)=>{offerToasts.push(s);toast(s)}}''')

        async def clear():
            await page.evaluate('()=>{offerToasts=[]}')

        async def failed():
            await page.wait_for_function('(s)=>offerToasts.includes(s)', arg=ERROR)
            assert not await page.evaluate("()=>offerToasts.some(s=>s==='ماموریت پذیرفته شد.' || s==='رد پیشنهاد ثبت شد.')")

        await open_app()
        for action in ('accept', 'decline'):
            for mode in ('network', 'http', 'html', 'empty', 'partial', 'contradictory'):
                async def fault(route, request, *, mode=mode, action=action):
                    if mode == 'network': await route.abort()
                    elif mode == 'http': await route.fulfill(status=503, json={'error': 'unavailable'})
                    elif mode == 'html': await route.fulfill(body='<html>offline</html>')
                    else: await route.fulfill(json={} if mode == 'empty' else {'ok': True} if mode == 'partial' else {'ok': True, 'reservation_id': rid})
                post = pattern + '/' + action
                await page.route(post, fault)
                await clear()
                await button(action).click()
                await failed()
                await page.unroute(post, fault)
                await expect(button(action)).to_be_enabled()
                assert (await booking(ctx.request, ptok, rid))['status'] == 'searching'
                assert (await api(ctx.request, 'GET', f'/translator/offers/{oid}', token))['status'] == 'pending'
                print('PASS offer', action, mode)

        # Even a fabricated accepted decision needs the real assigned mission.
        receipt_sent = False
        async def fabricated_receipt(route):
            nonlocal receipt_sent
            receipt_sent = True
            await route.fulfill(json={'ok': True, 'reservation_id': rid})
        async def fabricated_decision(route):
            response = await route.fetch()
            data = await response.json()
            if receipt_sent:
                data.update(status='accepted', assigned=True)
            await route.fulfill(json=data)
        await page.route(pattern, fabricated_decision)
        await page.route(pattern + '/accept', fabricated_receipt)
        await clear()
        await button('accept').click()
        await failed()
        await page.unroute(pattern, fabricated_decision)
        await page.unroute(pattern + '/accept', fabricated_receipt)
        await expect(button('accept')).to_be_enabled()
        assert (await booking(ctx.request, ptok, rid))['status'] == 'searching'

        # Invalid identity, amount or state must not send an accept POST.
        posts = 0
        async def no_post(route):
            nonlocal posts
            posts += 1
            await route.abort()
        await page.route(pattern + '/accept', no_post)
        for patch in ({'id': oid + 999}, {'reservation_id': rid + 999}, {'net': o['net'] + 1},
                      {'status': 'expired'}, {'assigned': 'false'}, {'expires_at': 'invalid'}):
            async def malformed(route, request, *, patch=patch):
                response = await route.fetch()
                data = await response.json()
                data.update(patch)
                await route.fulfill(json=data)
            await page.route(pattern, malformed)
            await clear()
            await button('accept').click()
            await failed()
            await page.unroute(pattern, malformed)
            await expect(button('accept')).to_be_enabled()
        assert posts == 0
        await page.unroute(pattern + '/accept', no_post)

        # Poll-replaced offer cards inherit the opposing-decision lock.
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(route):
            nonlocal posts
            posts += 1
            entered.set()
            await release.wait()
            await route.fulfill(json={})
        await page.route(pattern + '/accept', held)
        await card().evaluate('(e)=>e.dataset.beforePoll="1"')
        # Force a harmless displayed quote/notes refresh so polling re-renders.
        async def changed_list(route):
            response = await route.fetch()
            data = await response.json()
            for row in data['offers']: row['notes'] = 'بازسازی کارت'
            await route.fulfill(json=data)
        await page.route('**/api/translator/offers', changed_list)
        await clear()
        await button('accept').click()
        await asyncio.wait_for(entered.wait(), 10)
        await expect(button('accept')).to_be_disabled()
        await expect(button('decline')).to_be_disabled()
        await expect(page.locator('[data-before-poll]')).to_have_count(0)
        await expect(button('decline')).to_be_disabled()
        await card().evaluate('(e)=>e.querySelectorAll("button").forEach(b=>b.click())')
        assert posts == 1
        release.set()
        await failed()
        # Drain in-flight polling mocks before removing them; unroute alone
        # may race route.fetch()/fulfill() and hand a request twice.
        await page.unroute_all(behavior='wait')
        await expect(button('accept')).to_be_enabled()

        await page.clock.install()
        await page.evaluate('''()=>{window.originalFetch=fetch; window.fetch=(url,opts)=>
            String(url).endsWith('/offers/' + window.currentOffer + '/accept') && opts.method==='POST'
            ? (window.offerStalled=true,new Promise(()=>{})) : originalFetch(url,opts)}''')
        await page.evaluate('(id)=>{window.currentOffer=id}', oid)
        await clear()
        await button('accept').click()
        await page.wait_for_function('()=>window.offerStalled===true')
        await page.clock.run_for(10001)
        await failed()
        await page.evaluate('()=>{window.fetch=originalFetch}')
        await page.clock.resume()
        await expect(button('accept')).to_be_enabled()

        # Late response and old-card click cannot mutate the next account.
        other = await translator(ctx.request, 'male')
        await api(ctx.request, 'PATCH', '/translator/online', other, {'online': False})
        entered, release = asyncio.Event(), asyncio.Event()
        async def late(route):
            entered.set()
            await release.wait()
            await route.fulfill(json={'ok': True, 'reservation_id': rid})
        await page.route(pattern + '/accept', late)
        await clear()
        await button('accept').click()
        await asyncio.wait_for(entered.wait(), 10)
        await page.evaluate('(t)=>{let s=HZ.load();s.token=t;HZ.save(s)}', other)
        release.set()
        await expect(button('accept')).to_be_enabled()
        assert await page.evaluate('()=>offerToasts.length') == 0
        await page.unroute(pattern + '/accept', late)
        posts = 0
        await page.route(pattern + '/accept', no_post)
        await button('accept').click()
        await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(resolve))')
        assert posts == 0
        await page.unroute(pattern + '/accept', no_post)
        await page.evaluate('(t)=>{let s=HZ.load();s.token=t;HZ.save(s)}', token)
        await open_app()

        async def bad_list(route):
            await route.fulfill(json={'offers': [{'id': oid}], 'changes': [], 'extensions': []})
        await page.route('**/api/translator/offers', bad_list)
        await expect(page.locator('#offers-box')).to_contain_text('دریافت درخواست‌ها انجام نشد')
        await expect(card()).to_have_count(0)
        await page.unroute('**/api/translator/offers', bad_list)
        await page.get_by_role('button', name='تلاش دوباره', exact=True).click()
        await expect(button('accept')).to_be_enabled()

        # A delayed old pending-list response may not undo a real decline.
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
            await route.fulfill(json=data, headers={'x-offer-old': '1'})
        await page.route('**/api/translator/offers', old_list)
        await asyncio.wait_for(entered.wait(), 10)
        await clear()
        await button('decline').click()
        await page.wait_for_function("()=>offerToasts.includes('رد پیشنهاد ثبت شد.')")
        await expect(card()).to_have_count(0)
        async with page.expect_response(lambda r: r.headers.get('x-offer-old') == '1'):
            release.set()
        await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        await expect(card()).to_have_count(0)
        await page.unroute('**/api/translator/offers', old_list)
        assert (await api(ctx.request, 'GET', f'/translator/offers/{oid}', token))['status'] == 'declined'
        assert (await booking(ctx.request, ptok, rid))['status'] == 'searching'

        # A real accept with a lost receipt stays unconfirmed, not auto-retried.
        uncertain, pending = await create('پذیرش با پاسخ گم‌شده')
        await expect(button('accept', pending['id'])).to_be_visible()
        async def lost_receipt(route):
            await route.fetch()
            await route.abort()
        post = f"**/api/translator/offers/{pending['id']}/accept"
        await page.route(post, lost_receipt)
        await clear()
        await button('accept', pending['id']).click()
        await failed()
        await page.unroute(post, lost_receipt)
        assert (await booking(ctx.request, ptok, uncertain['id']))['status'] == 'matched'
        await arrive_and_start(ctx.request, uncertain['id'], token, uncertain['service_code'])
        await api(ctx.request, 'POST', f"/traveler/bookings/{uncertain['id']}/finish", ptok)

        real, pending = await create('پذیرش واقعی')
        await expect(button('accept', pending['id'])).to_be_visible()
        await clear()
        await button('accept', pending['id']).click()
        await page.wait_for_function("()=>offerToasts.includes('ماموریت پذیرفته شد.')")
        await expect(page.locator('#missions-list')).to_contain_text('پذیرش واقعی')
        result = await booking(ctx.request, ptok, real['id'])
        assert result['status'] == 'matched' and not result['service_started'] and result['total'] == real['total']
        assert not errors, errors
        print('PASS offer decisions: real accept/decline, privacy-backed state, faults, lock, timeout, stale list and session isolation')
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
