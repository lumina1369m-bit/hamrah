"""Translator safety panel is guidance only, with fresh, validated support settings."""
import asyncio
from pathlib import Path
import secrets
from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api
from hz_api import LOGIN_JS

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_support'
EMPTY = 'شمارهٔ پشتیبانی هنوز در پنل مدیریت تنظیم نشده است.'
INVALID = 'شمارهٔ پشتیبانی ثبت‌شده معتبر نیست؛ امکان تماس از این بخش وجود ندارد.'
ERROR = 'شمارهٔ پشتیبانی دریافت نشد. دوباره تلاش کنید.'
READY = 'شمارهٔ پشتیبانی از تنظیمات مدیر دریافت شد.'


async def scenario(browser, setup, admin, width):
    ctx = await browser.new_context(viewport={'width': width, 'height': 1000}, service_workers='block')
    page = await ctx.new_page()
    page.set_default_timeout(20000)
    errors, mutations = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        async def settings(number):
            await api(setup.request, 'PUT', '/admin/settings', admin, {'support_phone': number})
        await settings('')
        await page.goto(BASE + '/translator/index.html')
        await page.evaluate(LOGIN_JS, '9' + str(secrets.randbelow(900000000) + 100000000))
        page.on('request', lambda r: mutations.append(r.url) if '/api/' in r.url and r.method in ['POST', 'PUT', 'PATCH', 'DELETE'] else None)
        await page.goto(BASE + '/translator/app.html')
        await page.evaluate('''()=>{
            window.supportToasts=[];window.supportGeo=[];window.supportWindows=[];
            window.showToast=(s)=>supportToasts.push(s);HZ.toast=(s)=>supportToasts.push(s);
            Object.defineProperty(navigator,'geolocation',{configurable:true,value:{
                getCurrentPosition:()=>supportGeo.push('position'),watchPosition:()=>supportGeo.push('watch')}});
            window.open=(...args)=>supportWindows.push(args);
        }''')
        panel = page.locator('#inline-sos-panel')
        call = page.locator('#translator-support-call')
        retry = page.locator('#translator-support-retry')
        status = page.locator('#translator-support-status')

        async def no_call():
            await expect(call).to_be_hidden()
            assert await call.get_attribute('href') is None
            await expect(page.locator('#translator-support-phone')).to_have_text('')

        async def check_status(text):
            await expect(status).to_have_text(text)
            await expect(retry).to_be_enabled()

        await page.locator('#sos-btn').click()
        await expect(panel).to_be_visible()
        await expect(page.locator('#sos-btn')).to_have_attribute('aria-expanded', 'true')
        await expect(page.locator('#translator-support-safety-note')).to_contain_text('در خطر فوری، با خدمات اضطراری محل تماس بگیرید.')
        await expect(panel).to_contain_text('اتصال تماس یا پاسخ‌گویی تضمین نمی‌شود.')
        await check_status(EMPTY)
        await no_call()
        await expect(page.locator('#translator-support-escort')).to_be_disabled()
        await page.locator('#translator-support-escort').dispatch_event('click')
        assert await page.evaluate('()=>[typeof handleEmergencySupportEscort,typeof handleEmergencyCallOperator,typeof handleEmergencyPolice]') == ['undefined'] * 3
        for claim in ('موقعیت زنده شما به مرکز دیسپچ مخابره شد', 'زمان تقریبی رسیدن گشت تشریفات', '۰۲۱-۹۱۰۱۰۰۰۰', 'پشتیبانی ۲۴/۷'):
            assert claim not in await panel.inner_text()

        await settings('+۹۸ (۲۱) ۱۲۳۴-۵۶۷۸')
        await retry.click()
        await check_status(READY)
        await expect(call).to_have_attribute('href', 'tel:+982112345678')
        await expect(page.locator('#translator-support-phone')).to_have_text('+982112345678')
        await call.evaluate("e=>e.addEventListener('click',event=>{event.preventDefault();window.selectedSupportNumber=e.getAttribute('href')})")
        await call.click()
        assert await page.evaluate('()=>selectedSupportNumber') == 'tel:+982112345678'

        await settings('')
        await retry.click()
        await check_status(EMPTY)
        await no_call()
        for number in ('tel:02112345678', '021123#45', '*1234567', '123', '1234567890123456',
                       '<img src=x onerror=alert(1)>', '+98\n2112345678', '02112345678;ext=1'):
            await settings(number)
            await retry.click()
            await check_status(INVALID)
            await no_call()

        await settings('٠٢١-٨٨٨٨-٧٧٧٧')
        await page.locator('#translator-support-close').click()
        await expect(panel).to_be_hidden()
        await no_call()
        await expect(page.locator('#sos-btn')).to_be_focused()
        await page.locator('#sos-btn').click()
        await check_status(READY)
        await expect(call).to_have_attribute('href', 'tel:02188887777')

        for mode in ('network', 'http', 'html', 'empty', 'typed', 'wrong-status'):
            async def fault(route, request, *, mode=mode):
                if mode == 'network': await route.abort()
                elif mode == 'http': await route.fulfill(status=503, json={'error': 'unavailable'})
                elif mode == 'html': await route.fulfill(body='<html>offline</html>')
                else: await route.fulfill(status=201 if mode == 'wrong-status' else 200,
                    json={} if mode == 'empty' else {'support_phone': 2112345678} if mode == 'typed' else {'support_phone': '02112345678'})
            await page.route('**/api/config', fault)
            await retry.click()
            await check_status(ERROR)
            await no_call()
            await page.unroute_all(behavior='wait')
            await retry.click()
            await check_status(READY)
            print(f'PASS [{width}] support {mode}')

        # Closing and reopening invalidates a late transport that ignores AbortSignal.
        await page.evaluate('''()=>{
            window.originalSupportFetch=fetch;window.supportTrap=true;window.supportReads=0;
            window.fetch=(url,opts)=>String(url)==='/api/config' && supportTrap
                ? (supportReads++,new Promise(resolve=>{window.releaseSupportFetch=()=>resolve(
                    new Response(JSON.stringify({support_phone:'0210000000'}),{status:200}))}))
                : originalSupportFetch(url,opts);
        }''')
        await retry.click()
        await page.wait_for_function('()=>supportReads===1')
        await no_call()
        await expect(retry).to_be_disabled()
        await retry.evaluate('(e)=>{e.click();e.click()}')
        assert await page.evaluate('()=>supportReads') == 1
        await page.keyboard.press('Escape')
        await expect(panel).to_be_hidden()
        await no_call()
        await expect(page.locator('#sos-btn')).to_be_focused()
        await page.evaluate('()=>{supportTrap=false}')
        await settings('+1 (212) 555-0123')
        await page.locator('#sos-btn').click()
        await check_status(READY)
        await expect(call).to_have_attribute('href', 'tel:+12125550123')
        await page.evaluate('()=>{releaseSupportFetch()}')
        await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        await expect(call).to_have_attribute('href', 'tel:+12125550123')
        await page.evaluate('()=>{window.fetch=originalSupportFetch}')

        # The ten-second deadline also covers a stalled JSON response body.
        await page.clock.install()
        await page.evaluate('''()=>{
            window.originalSupportFetch=fetch;window.supportBodyStalled=false;
            window.fetch=(url,opts)=>String(url)==='/api/config'
                ? Promise.resolve({status:200,json:()=>new Promise(resolve=>{
                    window.supportBodyStalled=true;window.releaseSupportBody=resolve})})
                : originalSupportFetch(url,opts);
        }''')
        await retry.click()
        await page.wait_for_function('()=>supportBodyStalled===true')
        await no_call()
        await page.clock.run_for(10001)
        await check_status(ERROR)
        await no_call()
        await page.evaluate('()=>{window.fetch=originalSupportFetch;releaseSupportBody({support_phone:"0210000000"})}')
        await page.clock.resume()
        await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        await check_status(ERROR)
        await no_call()
        await retry.click()
        await check_status(READY)
        await expect(call).to_have_attribute('href', 'tel:+12125550123')

        await page.locator('#header-financial-shortcut').click()
        await expect(panel).to_be_hidden()
        await no_call()
        await settings('02177776666')
        await page.locator('#view-earnings .translator-alt-back').click()
        await page.locator('#sos-btn').click()
        await check_status(READY)
        await expect(call).to_have_attribute('href', 'tel:02177776666')
        assert not mutations, mutations
        assert await page.evaluate('()=>supportToasts') == []
        assert await page.evaluate('()=>supportGeo') == []
        assert await page.evaluate('()=>supportWindows') == []
        assert not errors, errors
        print(f'PASS [{width}] guidance only; real settings, validated links, no alert/location/call claims, faults, cancellation, late response and body timeout')
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(ARTIFACTS / f'failure-{width}.png'), full_page=True)
        raise
    finally:
        await page.unroute_all(behavior='wait')
        await ctx.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        setup = await browser.new_context()
        original = (await api(setup.request, 'GET', '/config'))['support_phone']
        admin = (await api(setup.request, 'POST', '/admin/login', data={'password': 'test-admin-pass'}))['token']
        try:
            for width in (390, 1280):
                await scenario(browser, setup, admin, width)
        finally:
            await api(setup.request, 'PUT', '/admin/settings', admin, {'support_phone': original})
            await setup.close()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
