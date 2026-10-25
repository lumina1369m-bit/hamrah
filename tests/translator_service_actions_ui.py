"""Translator service controls: real authorization/state, adversarial receipts,
shared locks across duplicate cards, bounded requests and account isolation.
All booking/matching/consent APIs are real; only explicit fault cases are mocked.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking
from booking_options_ui import login, translator
from hz_api import LOGIN_JS

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_service_actions'
ERROR = 'نتیجهٔ عملیات تأیید نشد. وضعیت مأموریت را بررسی کنید و سپس دوباره تلاش کنید.'


async def scenario(browser):
    ctx = await browser.new_context(viewport={'width': 390, 'height': 900}, service_workers='block')
    page = await ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.set_default_timeout(20000)
    try:
        await api(ctx.request, 'POST', '/dev/offline-all')
        await page.goto(BASE + '/translator/index.html')
        import secrets
        token = await page.evaluate(LOGIN_JS, '9' + str(secrets.randbelow(900000000) + 100000000))
        await api(ctx.request, 'PATCH', '/translator/online', token, {'online': True})
        ptok, _ = await login(ctx.request, 'traveler')
        b = await api(ctx.request, 'POST', '/traveler/bookings', ptok, {
            'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa',
            'place': 'آزمون کنترل واقعی مترجم', 'traveler_name': 'مسافر آزمون'}, status=201)
        rid, total = b['id'], b['total']
        offers = await api(ctx.request, 'GET', '/translator/offers', token)
        await api(ctx.request, 'POST', f"/translator/offers/{offers['offers'][0]['id']}/accept", token)

        async def open_app():
            await page.goto(BASE + '/translator/app.html')
            await expect(page.locator('#missions-list')).to_contain_text('آزمون کنترل واقعی مترجم')
            await page.evaluate('''() => { window.actionToasts=[];
                const toast=HZ.toast; HZ.toast=(s)=>{actionToasts.push(s);toast(s)}; }''')

        def mission_button(name):
            return page.locator('#missions-list').get_by_role('button', name=name, exact=True)

        def extension_review():
            return page.locator('#missions-list .translator-extension-card').get_by_role('button', name='بررسی درخواست تمدید', exact=True)

        def extension_button(name):
            label = 'پذیرش تمدید' if name in ('پذیرش', 'accept') else 'رد تمدید'
            return page.locator('#mission-extension-modal').get_by_role('button', name=label, exact=True)

        def finish():
            return page.locator('#mission-finish-confirm')

        async def prepare_finish():
            await mission_button('درخواست پایان مأموریت').click()
            await expect(finish()).to_be_visible()

        async def prepare_extension():
            await extension_review().click()
            await expect(page.locator('#mission-extension-modal')).to_be_visible()

        async def clear():
            await page.evaluate('() => {window.actionToasts=[]}')

        async def failed():
            await page.wait_for_function('(s) => window.actionToasts.includes(s)', arg=ERROR)
            assert not await page.evaluate("() => actionToasts.some(s=>s==='خدمت شروع شد.' || s==='تمدید رد شد.' || s.startsWith('تمدید پذیرفته شد') || s.startsWith('درخواست پایان برای مسافر'))")

        async def faults(button, path, receipt, status, prepare=None):
            for mode in ('network', 'http', 'html', 'empty', 'partial', 'contradictory'):
                async def handler(route, request, *, mode=mode):
                    if mode == 'network':
                        await route.abort()
                    elif mode == 'http':
                        await route.fulfill(status=503, json={'error': 'unavailable'})
                    elif mode == 'html':
                        await route.fulfill(status=status, content_type='text/html', body='<html>offline</html>')
                    else:
                        await route.fulfill(status=status, json={} if mode == 'empty' else {'ok': True} if mode == 'partial' else receipt)
                await page.route('**/api/translator/' + path, handler)
                await clear()
                if prepare:
                    await prepare()
                await button().click()
                await failed()
                await page.unroute('**/api/translator/' + path, handler)
                await expect(button()).to_be_enabled()
                unchanged = await booking(ctx.request, ptok, rid)
                assert unchanged['status'] == 'matched' and unchanged['total'] == total
                print('PASS', path, mode)

        await open_app()
        arrive = lambda: mission_button('رسیدم به محل ملاقات')
        await faults(arrive, f'missions/{rid}/arrive',
                     {'ok': True, 'already_arrived': False, 'arrived_at': '2026-10-24T12:00:00.000Z'}, 200)
        await clear()
        await arrive().click()
        await page.wait_for_function("() => actionToasts.includes('رسیدن شما به‌صورت دستی در سرور ثبت شد.')")
        assert (await api(ctx.request, 'GET', f'/translator/missions/{rid}', token))['arrived_at']

        start = lambda: mission_button('تأیید کد و آغاز همراهی')
        async def fill_code():
            for index, digit in enumerate(b['service_code']):
                await page.locator('#missions-list input').nth(index).fill(digit)
        # Security-code input is re-created after each canonical refresh.
        for mode in ('network', 'http', 'html', 'empty', 'partial', 'contradictory'):
            async def handler(route, request, *, mode=mode):
                if mode == 'network': await route.abort()
                elif mode == 'http': await route.fulfill(status=503, json={'error': 'unavailable'})
                elif mode == 'html': await route.fulfill(status=200, body='not JSON')
                else: await route.fulfill(status=200, json={} if mode == 'empty' else {'ok': True} if mode == 'partial' else {'ok': True, 'started': True})
            pattern = f'**/api/translator/missions/{rid}/verify-code'
            await page.route(pattern, handler)
            await clear()
            await fill_code()
            await start().click()
            await failed()
            await page.unroute(pattern, handler)
            await expect(start()).to_be_enabled()
            assert not (await booking(ctx.request, ptok, rid))['service_started']
            print('PASS start', mode)

        # Malformed canonical preflight must not even send the security code.
        count = 0
        async def no_post(route):
            nonlocal count
            count += 1
            await route.abort()
        async def malformed(route):
            await route.fulfill(json={'reservation_id': rid, 'status': 'matched', 'started': True})
        pattern = f'**/api/translator/missions/{rid}'
        post_pattern = f'**/api/translator/missions/{rid}/verify-code'
        await page.route(pattern, malformed)
        await page.route(post_pattern, no_post)
        await clear()
        await fill_code()
        await start().click()
        await failed()
        assert count == 0
        await page.unroute(pattern, malformed)
        await page.unroute(post_pattern, no_post)
        await expect(start()).to_be_enabled()

        # A believable receipt still needs a complete canonical start snapshot.
        # Do not let a started boolean without a usable timestamp suffice.
        read_count = 0
        async def bad_started_snapshot(route):
            nonlocal read_count
            read_count += 1
            response = await route.fetch()
            data = await response.json()
            if read_count > 1:
                data['started'] = True
                data['service_started_at'] = 'invalid timestamp'
            await route.fulfill(json=data)
        async def fake_started(route):
            await route.fulfill(json={'ok': True, 'started': True})
        await page.route(pattern, bad_started_snapshot)
        await page.route(post_pattern, fake_started)
        await clear()
        await fill_code()
        await start().click()
        await failed()
        assert read_count == 2
        await page.unroute(pattern, bad_started_snapshot)
        await page.unroute(post_pattern, fake_started)
        await expect(start()).to_be_enabled()

        # A stalled POST is shared by calendar/workspace cards. No second POST,
        # and re-rendering the day bar must not enable a duplicate action.
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(route):
            nonlocal count
            count += 1
            entered.set()
            await release.wait()
            await route.fulfill(json={})
        await page.route(post_pattern, held)
        await clear()
        await fill_code()
        await start().click()
        await asyncio.wait_for(entered.wait(), 10)
        await expect(start()).to_be_disabled()
        await expect(mission_button('لغو مأموریت')).to_be_disabled()
        await page.evaluate("() => document.querySelector('#day-bar button').click()")
        assert await page.locator(f'[data-service-mission="{rid}"]:not(:disabled)').count() == 0
        await page.evaluate("() => document.querySelectorAll('[data-service-mission]').forEach(b=>b.click())")
        assert count == 1
        release.set()
        await failed()
        await page.unroute(post_pattern, held)
        await expect(start()).to_be_enabled()

        # Timeout applies even when a transport ignores AbortSignal entirely.
        await page.clock.install()
        await page.evaluate('''() => { window.originalFetch=fetch;
            window.fetch=(url,opts)=>String(url).endsWith('/verify-code') && opts.method==='POST'
              ? (window.postStalled=true, new Promise(()=>{})) : originalFetch(url,opts); }''')
        await clear()
        await fill_code()
        await start().click()
        await expect(start()).to_be_disabled()
        await page.wait_for_function('() => window.postStalled === true')
        await page.clock.run_for(10001)
        await failed()
        await page.evaluate('() => { window.fetch=originalFetch }')
        await page.clock.resume()
        await expect(start()).to_be_enabled()

        # Actual start via the UI; timer origin must remain server-owned.
        await clear()
        await fill_code()
        await start().click()
        await page.wait_for_function("() => actionToasts.includes('خدمت شروع شد.')")
        before = await booking(ctx.request, ptok, rid)
        assert before['service_started'] and before['total'] == total
        await expect(mission_button('درخواست پایان مأموریت')).to_be_visible()
        await faults(finish, f'missions/{rid}/finish', {'ok': True, 'pending_finish': True}, 202, prepare=prepare_finish)
        assert not (await booking(ctx.request, ptok, rid))['finish_requested']

        # Late response from the previous account cannot toast or refresh the
        # next account. Restore the real owner afterwards and reload its UI.
        other = await translator(ctx.request, 'male')
        entered, release = asyncio.Event(), asyncio.Event()
        async def late(route):
            entered.set()
            await release.wait()
            await route.fulfill(status=202, json={'ok': True, 'pending_finish': True})
        finish_pattern = f'**/api/translator/missions/{rid}/finish'
        await page.route(finish_pattern, late)
        await clear()
        await prepare_finish()
        await finish().click()
        await asyncio.wait_for(entered.wait(), 10)
        await page.evaluate('(token) => {let s=HZ.load();s.token=token;HZ.save(s)}', other)
        release.set()
        await page.wait_for_function('() => !document.querySelector("[aria-busy=true]")')
        assert await page.evaluate('() => actionToasts.length') == 0
        await page.unroute(finish_pattern, late)
        await page.evaluate('(token) => {let s=HZ.load();s.token=token;HZ.save(s)}', token)
        await open_app()

        # Finish remains a request, not a completed or payable service.
        await prepare_finish()
        await finish().click()
        await page.wait_for_function("() => actionToasts.some(s=>s.startsWith('درخواست پایان برای مسافر'))")
        pending = await booking(ctx.request, ptok, rid)
        assert pending['status'] == 'matched' and pending['finish_requested'] and pending['total'] == total
        assert not (await api(ctx.request, 'GET', '/translator/payments', token))['payments']
        await api(ctx.request, 'POST', f'/traveler/bookings/{rid}/finish-reject', ptok)
        await open_app()

        # Both accept and reject must reconcile the exact extension, quote,
        # duration and unchanged service-start origin, not just HTTP 200.
        for decision, label in [('reject', 'رد'), ('accept', 'پذیرش')]:
            e = await api(ctx.request, 'POST', f'/traveler/bookings/{rid}/extend', ptok, {'extra_hours': 1}, status=202)
            button = lambda: extension_button(label)
            await expect(extension_review()).to_be_visible()
            await faults(button, f"extensions/{e['id']}/{decision}", {'ok': True}, 200, prepare=prepare_extension)
            pending = await booking(ctx.request, ptok, rid)
            assert pending['hours'] == before['hours'] and pending['pending_extension']['id'] == e['id']
            if decision == 'reject':
                # The opposing decision and finish control must share the lock,
                # even when polling replaces the extension card with a new quote.
                entered, release = asyncio.Event(), asyncio.Event()
                async def held_decision(route):
                    entered.set()
                    await release.wait()
                    await route.fulfill(json={})
                async def changed_offer(route):
                    response = await route.fetch()
                    data = await response.json()
                    for item in data.get('extensions', []):
                        item['extra_hours'] = 2
                    await route.fulfill(json=data)
                decision_pattern = f"**/api/translator/extensions/{e['id']}/reject"
                await page.route(decision_pattern, held_decision)
                await page.route('**/api/translator/offers', changed_offer)
                await clear()
                await prepare_extension()
                await button().click()
                await asyncio.wait_for(entered.wait(), 10)
                await expect(finish()).to_be_disabled()
                await expect(extension_button('پذیرش')).to_be_disabled()
                await expect(page.locator('#missions-list')).to_contain_text('تمدید درخواستی: ۲ ساعت')
                await expect(extension_button('پذیرش')).to_be_disabled()
                await expect(button()).to_be_disabled()
                release.set()
                await failed()
                # Do not remove a polling route while route.fetch/fulfill is active.
                await page.unroute_all(behavior='wait')
                await expect(button()).to_be_enabled()
            stale_entered, stale_release = asyncio.Event(), asyncio.Event()
            held_once = False
            async def stale_offer(route):
                nonlocal held_once
                if held_once:
                    await route.fallback()
                    return
                held_once = True
                response = await route.fetch()
                data = await response.json()
                stale_entered.set()
                await stale_release.wait()
                await route.fulfill(json=data, headers={'x-offer-stale': '1'})
            await page.route('**/api/translator/offers', stale_offer)
            await asyncio.wait_for(stale_entered.wait(), 10)
            await clear()
            await prepare_extension()
            await button().click()
            await page.wait_for_function('(decision) => actionToasts.some(s=>decision==="reject" ? s==="تمدید رد شد." : s.startsWith("تمدید پذیرفته شد"))', arg=decision)
            await expect(extension_review()).to_have_count(0)
            async with page.expect_response(lambda r: r.headers.get('x-offer-stale') == '1'):
                stale_release.set()
            await page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            await expect(extension_review()).to_have_count(0)
            await page.unroute('**/api/translator/offers', stale_offer)
            after = await booking(ctx.request, ptok, rid)
            assert after['hours'] == before['hours'] + (1 if decision == 'accept' else 0)
            assert after['total'] == total + (e['extra_total'] if decision == 'accept' else 0)
            assert after['service_started_at'] == before['service_started_at']
            if decision == 'accept': total = after['total']
            print('PASS real extension', decision)

        # Traveler may end early without translator approval, with full price.
        await api(ctx.request, 'POST', f'/traveler/bookings/{rid}/finish', ptok)
        ended = await booking(ctx.request, ptok, rid)
        assert ended['status'] == 'finished' and ended['total'] == total
        assert not errors, errors
        print('PASS translator service actions: real lifecycle, faults, shared locks, timeout, account isolation')
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
