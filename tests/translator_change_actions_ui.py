"""Translator change consent requires the exact recorded decision AND mission details."""
import asyncio
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api, booking
from booking_options_ui import login, translator
from hz_api import LOGIN_JS

ERROR = 'نتیجهٔ عملیات تأیید نشد. وضعیت مأموریت را بررسی کنید و سپس دوباره تلاش کنید.'
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_change_actions'


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
        b = await api(ctx.request, 'POST', '/traveler/bookings', ptok, {
            'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa', 'place': 'محل اولیه',
            'traveler_name': 'آزمون رضایت تغییر', 'car': False, 'hours': 2}, status=201)
        rid = b['id']
        offer = next(o for o in (await api(ctx.request, 'GET', '/translator/offers', token))['offers'] if o['reservation_id'] == rid)
        await api(ctx.request, 'POST', f"/translator/offers/{offer['id']}/accept", token)
        changes = {'place': 'محل جدید توافقی', 'hours': 20, 'car': True, 'party': 3, 'notes': 'یادداشت همراه تغییر'}
        c = await api(ctx.request, 'POST', f'/traveler/bookings/{rid}/change', ptok, changes, status=202)
        cid = c['id']
        pattern = f'**/api/translator/changes/{cid}'
        before = await api(ctx.request, 'GET', f'/translator/missions/{rid}', token)

        def card(change_id=cid):
            return page.locator(f'[data-change-id="{change_id}"]')

        def button(action, change_id=cid):
            return card(change_id).get_by_role('button', name='پذیرش' if action == 'accept' else 'رد', exact=True)

        def start_button():
            return page.locator('#missions-list').get_by_role('button', name='تأیید کد و آغاز همراهی', exact=True)

        async def fill_code(code):
            for index, digit in enumerate(code):
                await page.locator('#missions-list input').nth(index).fill(digit)

        async def open_app():
            await page.goto(BASE + '/translator/app.html')
            await expect(button('accept')).to_be_visible()
            mission = await api(ctx.request, 'GET', f'/translator/missions/{rid}', token)
            if not mission['arrived_at']:
                arrival = page.locator('#missions-list').get_by_role('button', name='رسیدم به محل ملاقات', exact=True)
                await expect(arrival).to_be_visible()
                await arrival.click()
                await expect(start_button()).to_be_visible()
            await page.evaluate('''()=>{window.changeToasts=[]; const toast=HZ.toast;
                HZ.toast=(s)=>{changeToasts.push(s);toast(s)}}''')

        async def clear():
            await page.evaluate('()=>{changeToasts=[]}')

        async def failed():
            await page.wait_for_function('(s)=>changeToasts.includes(s)', arg=ERROR)
            assert not await page.evaluate("()=>changeToasts.some(s=>s==='تغییر پذیرفته شد.' || s==='رد تغییر ثبت شد.')")

        await open_app()
        await expect(card()).to_contain_text('یادداشت همراه تغییر')
        for action in ('accept', 'reject'):
            for mode in ('network', 'http', 'html', 'empty', 'contradictory'):
                async def fault(route, request, *, mode=mode):
                    if mode == 'network': await route.abort()
                    elif mode == 'http': await route.fulfill(status=503, json={'error': 'unavailable'})
                    elif mode == 'html': await route.fulfill(body='<html>offline</html>')
                    else: await route.fulfill(json={} if mode == 'empty' else {'ok': True})
                post = pattern + '/' + action
                await page.route(post, fault)
                await clear()
                await button(action).click()
                await failed()
                await page.unroute(post, fault)
                await expect(button(action)).to_be_enabled()
                unchanged = await api(ctx.request, 'GET', f'/translator/missions/{rid}', token)
                assert unchanged['details'] == before['details'] and unchanged['total'] == before['total']
                print('PASS change', action, mode)

        # Fabricated accepted history alone cannot substitute for applied mission details.
        receipt_sent = False
        async def fabricated_receipt(route):
            nonlocal receipt_sent
            receipt_sent = True
            await route.fulfill(json={'ok': True})
        async def fabricated_decision(route):
            response = await route.fetch()
            data = await response.json()
            if receipt_sent: data['status'] = 'accepted'
            await route.fulfill(json=data)
        await page.route(pattern, fabricated_decision)
        await page.route(pattern + '/accept', fabricated_receipt)
        await clear()
        await button('accept').click()
        await failed()
        await page.unroute_all(behavior='wait')
        await expect(button('accept')).to_be_enabled()

        posts = 0
        async def no_post(route):
            nonlocal posts
            posts += 1
            await route.abort()
        await page.route(pattern + '/accept', no_post)
        for patch in ({'id': cid + 999}, {'reservation_id': rid + 999}, {'changes': {'place': 'تغییر دیگر'}},
                      {'changes': {'unknown_column': 'x'}}, {'status': 'expired'}, {'expires_at': 'invalid'}):
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

        # Opposing actions and mission start share the reservation lock, including re-render.
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(route):
            nonlocal posts
            posts += 1
            entered.set()
            await release.wait()
            await route.fulfill(json={})
        async def changed_list(route):
            response = await route.fetch()
            data = await response.json()
            for row in data['changes']: row['place'] = 'بازسازی کارت'
            await route.fulfill(json=data)
        await page.route(pattern + '/accept', held)
        await page.route('**/api/translator/offers', changed_list)
        await clear()
        await card().evaluate('(e)=>e.dataset.beforePoll="1"')
        await button('accept').click()
        await asyncio.wait_for(entered.wait(), 10)
        await expect(button('reject')).to_be_disabled()
        await expect(start_button()).to_be_disabled()
        await expect(page.locator('[data-before-poll]')).to_have_count(0)
        await expect(button('reject')).to_be_disabled()
        await card().evaluate('(e)=>e.querySelectorAll("button").forEach(b=>b.click())')
        assert posts == 1
        release.set()
        await failed()
        await page.unroute_all(behavior='wait')
        await expect(button('accept')).to_be_enabled()

        await page.clock.install()
        await page.evaluate('''(id)=>{window.currentChange=id; window.originalFetch=fetch; window.fetch=(url,opts)=>
            String(url).endsWith('/changes/' + currentChange + '/accept') && opts.method==='POST'
            ? (window.changeStalled=true,new Promise(()=>{})) : originalFetch(url,opts)}''', cid)
        await clear()
        await button('accept').click()
        await page.wait_for_function('()=>window.changeStalled===true')
        await page.clock.run_for(10001)
        await failed()
        await page.evaluate('()=>{window.fetch=originalFetch}')
        await page.clock.resume()
        await expect(button('accept')).to_be_enabled()

        other = await translator(ctx.request, 'male')
        await api(ctx.request, 'PATCH', '/translator/online', other, {'online': False})
        entered, release = asyncio.Event(), asyncio.Event()
        async def late(route):
            entered.set()
            await release.wait()
            await route.fulfill(json={'ok': True})
        await page.route(pattern + '/accept', late)
        await clear()
        await button('accept').click()
        await asyncio.wait_for(entered.wait(), 10)
        await page.evaluate('(t)=>{let s=HZ.load();s.token=t;HZ.save(s)}', other)
        release.set()
        await expect(button('accept')).to_be_enabled()
        assert await page.evaluate('()=>changeToasts.length') == 0
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
            await route.fulfill(json={'offers': [], 'changes': [{'id': cid, 'reservation_id': rid,
                'changes': {'hours': '20'}, 'expires_at': c['expires_at']}], 'extensions': []})
        await page.route('**/api/translator/offers', bad_list)
        await expect(page.locator('#offers-box')).to_contain_text('دریافت درخواست‌ها انجام نشد')
        await expect(card()).to_have_count(0)
        await page.unroute_all(behavior='wait')
        await page.get_by_role('button', name='تلاش دوباره', exact=True).click()
        await expect(button('accept')).to_be_enabled()

        # Keep one old pending list in flight across real acceptance.
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
            await route.fulfill(json=data, headers={'x-change-old': '1'})
        await page.route('**/api/translator/offers', old_list)
        await asyncio.wait_for(entered.wait(), 10)
        await clear()
        await button('accept').click()
        await page.wait_for_function("()=>changeToasts.includes('تغییر پذیرفته شد.')")
        await expect(card()).to_have_count(0)
        async with page.expect_response(lambda r: r.headers.get('x-change-old') == '1'):
            release.set()
        await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        await expect(card()).to_have_count(0)
        await page.unroute_all(behavior='wait')
        accepted = await api(ctx.request, 'GET', f'/translator/missions/{rid}', token)
        assert accepted['details']['place'] == changes['place'] and accepted['hours'] == 20
        assert accepted['details']['car'] == 1 and accepted['details']['party'] == 3
        assert accepted['details']['notes'] == changes['notes'] and accepted['total'] == before['total'] and accepted['net'] == before['net']

        second = await api(ctx.request, 'POST', f'/traveler/bookings/{rid}/change', ptok, {'place': 'تغییر مردود'}, status=202)
        await expect(button('reject', second['id'])).to_be_visible()
        await clear()
        await button('reject', second['id']).click()
        await page.wait_for_function("()=>changeToasts.includes('رد تغییر ثبت شد.')")
        assert (await api(ctx.request, 'GET', f'/translator/missions/{rid}', token))['details'] == accepted['details']

        third = await api(ctx.request, 'POST', f'/traveler/bookings/{rid}/change', ptok, {'place': 'رد با پاسخ گم‌شده'}, status=202)
        await expect(button('reject', third['id'])).to_be_visible()
        async def lost_receipt(route):
            await route.fetch()
            await route.abort()
        post = f"**/api/translator/changes/{third['id']}/reject"
        await page.route(post, lost_receipt)
        await clear()
        await button('reject', third['id']).click()
        await failed()
        await page.unroute_all(behavior='wait')
        assert (await api(ctx.request, 'GET', f"/translator/changes/{third['id']}", token))['status'] == 'rejected'
        assert (await api(ctx.request, 'GET', f'/translator/missions/{rid}', token))['details'] == accepted['details']

        # Existing allowed 20-hour change must not strand subsequent service controls.
        await fill_code(b['service_code'])
        await page.locator('#missions-list').get_by_role('button', name='تأیید کد و آغاز همراهی', exact=True).click()
        await page.wait_for_function("()=>changeToasts.includes('خدمت شروع شد.')")
        result = await booking(ctx.request, ptok, rid)
        assert result['hours'] == 20 and result['service_started'] and result['total'] == before['total']
        assert not errors, errors
        print('PASS change consent: exact applied details, preserved price snapshot, real accept/reject, faults, shared locks, timeout and session isolation')
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
