"""Translator cash controls must reconcile the exact private server payment.
Real lifecycle and owner authorization; faults only intercept specified requests.
"""
import asyncio
from pathlib import Path
import secrets
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking
from booking_options_ui import login, translator
from hz_api import LOGIN_JS

ERROR = 'نتیجهٔ عملیات تأیید نشد. وضعیت مأموریت را بررسی کنید و سپس دوباره تلاش کنید.'
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_cash_actions'


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
                'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa',
                'place': label, 'traveler_name': 'آزمون پرداخت'}, status=201)
            offers = await api(ctx.request, 'GET', '/translator/offers', token)
            offer = next(o for o in offers['offers'] if o['place'] == label)
            await api(ctx.request, 'POST', f"/translator/offers/{offer['id']}/accept", token)
            await api(ctx.request, 'POST', f"/translator/missions/{b['id']}/verify-code", token, {'code': b['service_code']})
            await api(ctx.request, 'POST', f"/traveler/bookings/{b['id']}/finish", ptok)
            await api(ctx.request, 'POST', f"/traveler/bookings/{b['id']}/payment", ptok, {'method': 'cash'})
            return b

        b = await create('نقدی اصلی')
        second = await create('نقدی اختلاف')
        rid = b['id']
        pattern = f'**/api/translator/missions/{rid}'
        confirm_pattern = pattern + '/cash-confirm'
        disputed_pattern = pattern + '/cash-dispute'

        def card(bid=rid):
            return page.locator(f'[data-payment-reservation="{bid}"]')

        def button(action, bid=rid):
            return card(bid).get_by_role('button', name='دریافت وجه را تأیید می‌کنم' if action == 'cash-confirm' else 'اختلاف دارم', exact=True)

        async def open_app():
            await page.goto(BASE + '/translator/app.html')
            await page.locator('#mobile-nav [data-target=workspace]').click()
            await expect(button('cash-confirm')).to_be_visible()
            await page.evaluate('''() => {window.cashToasts=[]; const toast=HZ.toast;
                HZ.toast=(s)=>{cashToasts.push(s);toast(s)};}''')

        async def clear():
            await page.evaluate('() => {cashToasts=[]}')

        async def failed():
            await page.wait_for_function('(s)=>cashToasts.includes(s)', arg=ERROR)
            assert not await page.evaluate("() => cashToasts.some(s=>['پرداخت تسویه شد.','اختلاف پرداخت ثبت شد.','دریافت شما ثبت شد؛ منتظر تأیید مسافر.'].includes(s))")

        async def unchanged():
            data = await booking(ctx.request, ptok, rid)
            assert data['status'] == 'finished' and data['pay_state'] == 'awaiting_cash' and data['total'] == b['total']
            private = await api(ctx.request, 'GET', f'/translator/missions/{rid}', token)
            assert private['confirmed'] is False

        await open_app()
        for action in ('cash-confirm', 'cash-dispute'):
            for mode in ('network', 'http', 'html', 'empty', 'partial', 'contradictory', 'typed', 'wrong_status'):
                async def fault(route, request, *, mode=mode, action=action):
                    receipt = {'ok': True, 'settled': True, 'waiting_traveler': False} if action == 'cash-confirm' else {'ok': True, 'pay_state': 'disputed'}
                    if mode == 'network': await route.abort()
                    elif mode == 'http': await route.fulfill(status=503, json={'error': 'unavailable'})
                    elif mode == 'html': await route.fulfill(body='<html>offline</html>')
                    else:
                        if mode == 'typed': receipt = {'ok': True, 'settled': 'true', 'waiting_traveler': False, 'pay_state': True}
                        await route.fulfill(status=202 if mode == 'wrong_status' else 200,
                                            json={} if mode == 'empty' else {'ok': True} if mode == 'partial' else receipt)
                post = pattern + '/' + action
                await page.route(post, fault)
                await clear()
                await button(action).click()
                await failed()
                await page.unroute(post, fault)
                await expect(button(action)).to_be_enabled()
                await unchanged()
                print('PASS', action, mode)

        # Bad identity/amount/types must stop before a financial mutation.
        posts = 0
        async def forbidden_post(route):
            nonlocal posts
            posts += 1
            await route.abort()
        await page.route(confirm_pattern, forbidden_post)
        for patch in ({'reservation_id': rid + 999}, {'total': b['total'] + 1}, {'confirmed': 'false'},
                      {'traveler_paid': None}, {'pay_state': 'settled'}, {'status': 'matched'}, {'net': -1}):
            async def bad_state(route, request, *, patch=patch):
                response = await route.fetch()
                data = await response.json()
                data.update(patch)
                await route.fulfill(json=data)
            await page.route(pattern, bad_state)
            await clear()
            await button('cash-confirm').click()
            await failed()
            await expect(button('cash-confirm')).to_be_enabled()
            await page.unroute(pattern, bad_state)
        assert posts == 0
        await page.unroute(confirm_pattern, forbidden_post)

        # Poll-driven replacements must keep both opposing actions disabled.
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(route):
            nonlocal posts
            posts += 1
            entered.set()
            await release.wait()
            await route.fulfill(json={})
        await page.route(confirm_pattern, held)
        await clear()
        await card().evaluate('(e)=>e.dataset.beforePoll="1"')
        await button('cash-confirm').click()
        await asyncio.wait_for(entered.wait(), 10)
        await expect(button('cash-confirm')).to_be_disabled()
        await expect(button('cash-dispute')).to_be_disabled()
        await expect(page.locator('[data-before-poll]')).to_have_count(0)
        await expect(button('cash-dispute')).to_be_disabled()
        await card().evaluate('(e)=>e.querySelectorAll("button").forEach(b=>b.click())')
        assert posts == 1
        release.set()
        await failed()
        await page.unroute(confirm_pattern, held)
        await expect(button('cash-confirm')).to_be_enabled()

        # Whole-operation timeout, even if a transport ignores AbortSignal.
        await page.clock.install()
        await page.evaluate('''() => {window.originalFetch=fetch; window.fetch=(url,opts)=>
            String(url).endsWith('/cash-confirm') && opts.method==='POST'
            ? (window.cashStalled=true,new Promise(()=>{})) : originalFetch(url,opts)}''')
        await clear()
        await button('cash-confirm').click()
        await page.wait_for_function('() => window.cashStalled === true')
        await page.clock.run_for(10001)
        await failed()
        await page.evaluate('() => {window.fetch=originalFetch}')
        await page.clock.resume()
        await expect(button('cash-confirm')).to_be_enabled()
        await unchanged()

        # A previous account's late response and old card cannot act as the next user.
        other = await translator(ctx.request, 'male')
        entered, release = asyncio.Event(), asyncio.Event()
        async def late(route):
            entered.set()
            await release.wait()
            await route.fulfill(json={'ok': True, 'settled': True, 'waiting_traveler': False})
        await page.route(confirm_pattern, late)
        await clear()
        await button('cash-confirm').click()
        await asyncio.wait_for(entered.wait(), 10)
        await page.evaluate('(token)=>{let s=HZ.load();s.token=token;HZ.save(s)}', other)
        release.set()
        await page.wait_for_function('() => !document.querySelector("[aria-busy=true]")')
        assert await page.evaluate('() => cashToasts.length') == 0
        await page.unroute(confirm_pattern, late)
        posts = 0
        await page.route(confirm_pattern, forbidden_post)
        await button('cash-confirm').click()
        await page.evaluate('() => new Promise(resolve=>requestAnimationFrame(resolve))')
        assert posts == 0 and await page.evaluate('() => cashToasts.length') == 0
        await page.unroute(confirm_pattern, forbidden_post)
        await page.evaluate('(token)=>{let s=HZ.load();s.token=token;HZ.save(s)}', token)
        await open_app()

        # Malformed payment-list snapshots clear old actionable cards and expose retry.
        async def bad_list(route):
            await route.fulfill(json={'payments': [{'reservation_id': rid, 'confirmed': 'false'}]})
        await page.route('**/api/translator/payments', bad_list)
        await expect(page.locator('#payments-box')).to_contain_text('وضعیت پرداخت‌ها دریافت نشد')
        await expect(card()).to_have_count(0)
        await page.unroute('**/api/translator/payments', bad_list)
        await page.get_by_role('button', name='دریافت دوبارهٔ پرداخت‌ها', exact=True).click()
        await expect(button('cash-confirm')).to_be_enabled()

        # Hold an old list response across a real confirm. It must not resurrect
        # the already-settled payment card once the action refresh has applied.
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
            await route.fulfill(json=data, headers={'x-cash-stale': '1'})
        await page.route('**/api/translator/payments', old_list)
        await asyncio.wait_for(entered.wait(), 10)
        await clear()
        await button('cash-confirm').click()
        await page.wait_for_function("() => cashToasts.includes('پرداخت تسویه شد.')")
        await expect(card()).to_have_count(0)
        async with page.expect_response(lambda r: r.headers.get('x-cash-stale') == '1'):
            release.set()
        await page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        await expect(card()).to_have_count(0)
        await page.unroute('**/api/translator/payments', old_list)
        settled = await booking(ctx.request, ptok, rid)
        assert settled['status'] == 'done' and settled['pay_state'] == 'settled' and settled['total'] == b['total']

        await clear()
        await button('cash-dispute', second['id']).click()
        await page.wait_for_function("() => cashToasts.includes('اختلاف پرداخت ثبت شد.')")
        await expect(card(second['id'])).to_contain_text('اختلاف پرداخت ثبت شده')
        await expect(card(second['id']).get_by_role('button')).to_have_count(0)
        disputed = await booking(ctx.request, ptok, second['id'])
        assert disputed['status'] == 'finished' and disputed['pay_state'] == 'disputed' and disputed['total'] == second['total']
        assert not errors, errors
        print('PASS translator cash: real confirm/dispute, unchanged amounts, faults, locks, timeout, stale list, account isolation')
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
