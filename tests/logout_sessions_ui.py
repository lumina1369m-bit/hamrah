"""Real server revocation: single-device versus all-device traveler logout.

Three independent browser contexts share one account; another account stays
unaffected. Failed/unconfirmed requests preserve retryability, duplicate clicks
are guarded, and revoked peer devices return to sign-in on their next API sync.
"""
import asyncio
import json
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_logout_sessions'
FAILURE = {
    'fa': 'خروج ثبت نشد. اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.',
    'en': 'Sign-out was not confirmed. Check your connection and try again.',
    'ar': 'لم يتم تأكيد الخروج. تحقّق من اتصال الإنترنت وحاول مجدداً.',
}
EXPIRED = {
    'fa': 'نشست شما پایان یافته است. لطفاً دوباره وارد شوید.',
    'en': 'Your session has ended. Please sign in again.',
    'ar': 'انتهت جلستك. يرجى تسجيل الدخول مجدداً.',
}


async def sign_in(request, phone):
    await api(request, 'POST', '/auth/request-code', data={'phone': phone, 'role': 'traveler'})
    return await api(request, 'POST', '/auth/verify', data={'phone': phone, 'role': 'traveler', 'code': '123456'})


async def seeded_context(browser, session, lang, errors):
    ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
    await ctx.route('https://nominatim.openstreetmap.org/**', lambda r: r.fulfill(json={'display_name': 'تهران، آزمون خروج'}))
    await ctx.route('https://*.tile.openstreetmap.org/**', lambda r: r.abort())
    page = await ctx.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.set_default_timeout(20000)
    await page.goto(BASE + '/traveler/index.html')
    profile = {'name': 'Ali', 'last': 'Rezaei', 'gender': 'مرد',
               'phone': session['user']['phone'], 'authUserId': session['user']['id']}
    # Do not inject credentials with add_init_script: logout must really clear them.
    await page.evaluate("""([token, profile, lang]) => {
        localStorage.setItem('hamzaban.token.v1', token);
        localStorage.setItem('hamzaban.user.v1', JSON.stringify(profile));
        localStorage.setItem('hamzaban.bookings.v1', '[]');
        localStorage.setItem('hamzaban_lang', lang);
    }""", [session['token'], profile, lang])
    await page.goto(BASE + '/traveler/app.html')
    await page.wait_for_function('() => window.hzBookingsSynced === true')
    await page.locator('nav a[data-nav=account]').click()
    return ctx, page


async def assert_cleared(page, lang):
    await expect(page).to_have_url(BASE + '/traveler/index.html')
    await expect(page.locator('#step-identifier')).to_be_visible()
    stored = await page.evaluate("""() => [
        localStorage.getItem('hamzaban.token.v1'), localStorage.getItem('hamzaban.user.v1'),
        localStorage.getItem('hamzaban.bookings.v1'), localStorage.getItem('hamzaban_lang')
    ]""")
    assert stored == [None, None, None, lang], stored


async def scenario(browser, lang):
    setup = await browser.new_context()
    contexts, pages, errors = [], [], []
    release = asyncio.Event()
    try:
        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        sessions = [await sign_in(setup.request, phone) for _ in range(3)]
        outsider = await sign_in(setup.request, '9' + str(secrets.randbelow(900000000) + 100000000))
        for session in sessions:
            ctx, page = await seeded_context(browser, session, lang, errors)
            contexts.append(ctx)
            pages.append(page)
        a, b, c = pages
        # An offline single-device attempt must not claim success or erase the token.
        async def offline(route):
            await route.abort('internetdisconnected')
        await a.route('**/api/auth/logout', offline)
        await a.locator('#ac-logout').click()
        await expect(a.locator('#ac-logout')).to_be_enabled()
        await expect(a.locator('#toast-text')).to_have_text(FAILURE[lang])
        assert await a.evaluate("() => localStorage.getItem('hamzaban.token.v1')") == sessions[0]['token']
        await api(setup.request, 'GET', '/auth/me', sessions[0]['token'])
        await a.unroute('**/api/auth/logout', offline)

        # Hold the real request, then try both buttons again via synthetic events.
        arrived, requests = asyncio.Event(), []
        async def delayed(route):
            requests.append(route.request.url)
            arrived.set()
            await release.wait()
            await route.continue_()
        await a.route('**/api/auth/logout', delayed)
        await a.locator('#ac-logout').click()
        await asyncio.wait_for(arrived.wait(), 20)
        for selector in ['#ac-logout', '#ac-logout-all']:
            await expect(a.locator(selector)).to_be_disabled()
        await expect(a.locator('#ac-logout')).to_have_attribute('aria-busy', 'true')
        await a.evaluate("""() => ['ac-logout','ac-logout-all'].forEach(id =>
            document.getElementById(id).dispatchEvent(new MouseEvent('click', {bubbles:true})))""")
        assert len(requests) == 1
        await api(setup.request, 'GET', '/auth/me', sessions[0]['token'])
        release.set()
        await assert_cleared(a, lang)
        await api(setup.request, 'GET', '/auth/me', sessions[0]['token'], status=401)
        for session in sessions[1:]:
            await api(setup.request, 'GET', '/auth/me', session['token'])
        assert len(requests) == 1
        print(f'PASS [{lang}]: single-device logout revokes only that session, clears private cache and guards duplicate clicks')

        # Both server failure and a superficially successful but unconfirmed JSON
        # response must retain credentials and keep all other sessions valid.
        for status, payload in [(503, {'error': 'unavailable'}), (200, {})]:
            async def failure(route, _request, *, status=status, payload=payload):
                await route.fulfill(status=status, json=payload)
            await b.route('**/api/auth/logout-all', failure)
            await b.locator('#ac-logout-all').click()
            await expect(b.locator('#ac-logout-all')).to_be_enabled()
            await expect(b.locator('#toast-text')).to_have_text(FAILURE[lang])
            assert b.url.endswith('/app.html')
            assert await b.evaluate("() => localStorage.getItem('hamzaban.token.v1')") == sessions[1]['token']
            await api(setup.request, 'GET', '/auth/me', sessions[1]['token'])
            await api(setup.request, 'GET', '/auth/me', sessions[2]['token'])
            await b.unroute('**/api/auth/logout-all', failure)
        await b.locator('#ac-logout-all').click()
        await assert_cleared(b, lang)
        for session in sessions:
            await api(setup.request, 'GET', '/auth/me', session['token'], status=401)
        # An already-open peer returns to login when its normal five-second poll
        # receives 401, rather than keeping a stale signed-in profile on screen.
        await assert_cleared(c, lang)
        await expect(c.locator('#ident-err')).to_have_text(EXPIRED[lang])
        await api(setup.request, 'GET', '/auth/me', outsider['token'])
        assert not errors, errors
        print(f'PASS [{lang}]: failed all-device logout stays retryable; confirmed logout revokes peers but not other accounts')
    except Exception:
        print('JavaScript errors:', errors)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        for i, page in enumerate(pages):
            try:
                await page.screenshot(path=str(ARTIFACTS / f'{lang}-device-{i}.png'), full_page=True)
            except Exception:
                pass
        raise
    finally:
        release.set()
        for ctx in contexts:
            await ctx.close()
        await setup.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        for lang in ['fa', 'en', 'ar']:
            await scenario(browser, lang)
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
