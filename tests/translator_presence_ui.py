"""Server-confirmed translator presence; no cached or optimistic availability."""
import asyncio
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api
from hz_api import LOGIN_JS
from booking_options_ui import translator

ERROR = 'وضعیت آمادگی تأیید نشد؛ برای بررسی دوباره تلاش کنید.'
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_presence'


async def scenario(browser):
    ctx = await browser.new_context(viewport={'width': 390, 'height': 900}, service_workers='block')
    page = await ctx.new_page()
    page.set_default_timeout(20000)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    toggle = page.locator('#shift-toggle-btn')
    pattern = '**/api/translator/online'
    try:
        await api(ctx.request, 'POST', '/dev/offline-all')
        await page.goto(BASE + '/translator/index.html')
        token = await page.evaluate(LOGIN_JS, '9' + str(secrets.randbelow(900000000) + 100000000))
        await page.evaluate('()=>{let s=HZ.load();s.shift=true;HZ.save(s)}')
        patches = []
        page.on('request', lambda r: patches.append(r.post_data_json) if r.method == 'PATCH' and r.url.endswith('/translator/online') else None)
        await page.goto(BASE + '/translator/app.html')
        await page.locator('#mobile-nav [data-target=workspace]').click()
        await expect(toggle).to_have_attribute('aria-pressed', 'false')
        assert not patches
        assert await page.evaluate('()=>HZ.load().shift') is False
        await page.evaluate('''()=>{window.presenceToasts=[]; const toast=HZ.toast;
            HZ.toast=(s)=>{presenceToasts.push(s);toast(s)}}''')

        async def clear():
            await page.evaluate('()=>{presenceToasts=[]}')

        async def failed():
            await page.wait_for_function('(s)=>presenceToasts.includes(s)', arg=ERROR)
            await expect(toggle).to_have_attribute('aria-pressed', 'mixed')
            assert await page.evaluate('()=>HZ.load().shift === null')
            assert not await page.evaluate("()=>presenceToasts.some(s=>s==='آمادگی شما برای دریافت مأموریت ثبت شد.' || s==='وضعیت آفلاین شما ثبت شد.')")

        async def retry(value=False):
            await page.get_by_role('button', name='بررسی دوبارهٔ آمادگی', exact=True).click()
            await expect(toggle).to_have_attribute('aria-pressed', str(value).lower())
            await expect(toggle).to_be_enabled()

        for mode in ('network', 'http', 'html', 'empty', 'typed', 'opposite', 'contradictory'):
            async def fault(route, request, *, mode=mode):
                if request.method != 'PATCH':
                    await route.fallback()
                    return
                if mode == 'network': await route.abort()
                elif mode == 'http': await route.fulfill(status=503, json={'error': 'unavailable'})
                elif mode == 'html': await route.fulfill(body='<html>offline</html>')
                else:
                    await route.fulfill(json={} if mode == 'empty' else {'online': 'true'} if mode == 'typed' else {'online': mode != 'opposite'})
            await page.route(pattern, fault)
            await clear()
            await toggle.click()
            await failed()
            await page.unroute(pattern, fault)
            assert not (await api(ctx.request, 'GET', '/translator/online', token))['online']
            before = len(patches)
            await retry()
            assert len(patches) == before  # Retry is read-only, never a repeated mutation.
            print('PASS presence', mode)

        # Invalid canonical preflight must not send a mutation at all.
        async def bad_preflight(route, request):
            if request.method == 'GET': await route.fulfill(json={'online': False, 'enabled': 'yes'})
            else: await route.abort()
        await page.route(pattern, bad_preflight)
        await clear()
        before = len(patches)
        await toggle.click()
        await failed()
        assert len(patches) == before
        await page.unroute(pattern, bad_preflight)
        await retry()

        # All presence entry points share one lock; no optimistic label or cache.
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(route, request):
            if request.method != 'PATCH':
                await route.fallback()
                return
            entered.set()
            await release.wait()
            await route.fulfill(json={})
        await page.route(pattern, held)
        await clear()
        before = len(patches)
        await toggle.click()
        await asyncio.wait_for(entered.wait(), 10)
        assert await page.locator('[data-presence-control]:not(:disabled)').count() == 0
        await expect(toggle).to_have_attribute('aria-pressed', 'false')
        assert await page.evaluate('()=>HZ.load().shift') is False
        await page.evaluate("()=>document.querySelectorAll('[data-presence-control]').forEach(b=>b.click())")
        assert len(patches) == before + 1
        release.set()
        await failed()
        await page.unroute(pattern, held)
        await retry()

        await page.clock.install()
        await page.evaluate('''()=>{window.originalFetch=fetch;window.fetch=(url,opts)=>
            String(url).endsWith('/translator/online') && opts.method==='PATCH'
            ? (window.presenceStalled=true,new Promise(()=>{})) : originalFetch(url,opts)}''')
        await clear()
        await toggle.click()
        await page.wait_for_function('()=>window.presenceStalled===true')
        await page.clock.run_for(10001)
        await failed()
        await page.evaluate('()=>{window.fetch=originalFetch}')
        await page.clock.resume()
        await retry()

        # Real server mutation but lost receipt => unknown, not a fake rollback.
        async def lost_receipt(route, request):
            if request.method != 'PATCH':
                await route.fallback()
                return
            await route.fetch()
            await route.abort()
        await page.route(pattern, lost_receipt)
        await clear()
        await toggle.click()
        await failed()
        await page.unroute(pattern, lost_receipt)
        assert (await api(ctx.request, 'GET', '/translator/online', token))['online'] is True
        await retry(True)
        await clear()
        await toggle.click()
        await page.wait_for_function("()=>presenceToasts.includes('وضعیت آفلاین شما ثبت شد.')")
        await expect(toggle).to_have_attribute('aria-pressed', 'false')
        await clear()
        await toggle.click()
        await page.wait_for_function("()=>presenceToasts.includes('آمادگی شما برای دریافت مأموریت ثبت شد.')")
        await expect(toggle).to_have_attribute('aria-pressed', 'true')
        assert all(set(body) == {'online'} and type(body['online']) is bool for body in patches)

        # Real admin feature disable is reflected even if the page was online.
        admin = await api(ctx.request, 'POST', '/admin/login', data={'password': 'test-admin-pass'})
        await api(ctx.request, 'PUT', '/admin/features', admin['token'], {'translator_online': False})
        try:
            await page.evaluate("()=>window.dispatchEvent(new Event('focus'))")
            await expect(toggle).to_have_attribute('aria-pressed', 'false')
            await expect(page.locator('#shift-status-desc')).to_contain_text('توسط مدیر غیرفعال')
            await expect(toggle).to_be_disabled()
            assert not (await api(ctx.request, 'GET', '/translator/online', token))['enabled']
        finally:
            await api(ctx.request, 'PUT', '/admin/features', admin['token'], {'translator_online': True})
        await retry()

        # An old account's late receipt cannot change the next account's cache.
        other = await translator(ctx.request, 'male')
        await api(ctx.request, 'PATCH', '/translator/online', other, {'online': False})
        entered, release = asyncio.Event(), asyncio.Event()
        async def late(route, request):
            if request.method != 'PATCH':
                await route.fallback()
                return
            entered.set()
            await release.wait()
            await route.fulfill(json={'online': True})
        await page.route(pattern, late)
        await clear()
        await toggle.click()
        await asyncio.wait_for(entered.wait(), 10)
        await page.evaluate('(t)=>{let s=HZ.load();s.token=t;s.shift="sentinel";HZ.save(s)}', other)
        release.set()
        await expect(toggle).to_be_enabled()
        assert await page.evaluate('()=>HZ.load().shift') == 'sentinel'
        assert await page.evaluate('()=>presenceToasts.length') == 0
        await page.unroute(pattern, late)
        before = len(patches)
        await toggle.click()  # Different owner => read-only synchronization.
        await expect(toggle).to_have_attribute('aria-pressed', 'false')
        assert len(patches) == before
        assert not (await api(ctx.request, 'GET', '/translator/online', other))['online']

        # Invalid reads may not revive cached online=true; explicit retry works.
        async def malformed(route, request):
            if request.method == 'GET': await route.fulfill(json={'online': True, 'enabled': 'yes'})
            else: await route.fallback()
        await page.route(pattern, malformed)
        await page.evaluate("()=>window.dispatchEvent(new Event('focus'))")
        await expect(toggle).to_have_attribute('aria-pressed', 'mixed')
        await page.unroute(pattern, malformed)
        await retry()
        await page.evaluate('()=>{let s=HZ.load();s.token=null;s.shift=true;HZ.save(s)}')
        before = len(patches)
        await toggle.click()
        await expect(toggle).to_have_attribute('aria-pressed', 'mixed')
        assert len(patches) == before
        assert not errors, errors
        print('PASS presence: cache isolation, real online/offline, feature gate, faults, lock, timeout, uncertain outcome and session isolation')
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
