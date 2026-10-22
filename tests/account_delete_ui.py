"""Deletion must be explicitly server-confirmed, never a local-profile success.

Run only against a disposable HZ_DEV=1 database. Uses real accounts and deletion;
fault responses exercise retryability without deleting their server-side account.
"""
import asyncio
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api
from logout_sessions_ui import sign_in, seeded_context, assert_cleared

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_account_delete'
WORD = {'fa': 'حذف حساب', 'en': 'Delete account', 'ar': 'حذف الحساب'}
FAILURE = {
    'fa': 'حذف حساب تأیید نشد. اتصال را بررسی کنید و دوباره تلاش کنید.',
    'en': 'Account deletion was not confirmed. Check your connection and try again.',
    'ar': 'لم يتم تأكيد حذف الحساب. تحقّق من الاتصال وحاول مجدداً.',
}
REQUIRED = {
    'fa': 'برای حذف حساب، ابتدا وارد حساب شوید.',
    'en': 'Please sign in before deleting your account.',
    'ar': 'يرجى تسجيل الدخول قبل حذف حسابك.',
}
SUCCESS = {
    'fa': 'حذف حساب توسط سرور تأیید شد.',
    'en': 'Account deletion was confirmed by the server.',
    'ar': 'تم تأكيد حذف الحساب من الخادم.',
}
BLOCKED = {
    'fa': 'حذف حساب وقتی رزرو یا کارِ باز دارید ممکن نیست',
    'en': 'Account deletion is not possible while you have open bookings or work',
    'ar': 'لا يمكن حذف الحساب أثناء وجود حجوزات أو مهام مفتوحة',
}


async def scenario(browser, lang):
    setup = await browser.new_context()
    ctx, page = None, None
    release = asyncio.Event()
    errors, deletes = [], []
    phone = '9' + ''.join(str(secrets.randbelow(10)) for _ in range(9))
    try:
        session = await sign_in(setup.request, phone)
        peer = await sign_in(setup.request, phone)
        outsider = await sign_in(setup.request, '9' + ''.join(str(secrets.randbelow(10)) for _ in range(9)))
        ctx, page = await seeded_context(browser, session, lang, errors)
        page.on('request', lambda r: deletes.append(r) if r.method == 'DELETE' else None)
        await page.locator('#ac-delete').click()
        confirm, field = page.locator('#ac-delete-confirm'), page.locator('#ac-delete-input')
        await expect(field).to_have_accessible_name({'fa': 'برای تأیید عبارت «حذف حساب» را بنویسید', 'en': 'To confirm, type "Delete account"', 'ar': 'للتأكيد، اكتب عبارة «حذف الحساب»'}[lang])
        # No fixed 30-day job/retention policy is implemented by this endpoint.
        assert '۳۰' not in await page.locator('#ac-delete-box').inner_text()
        await field.fill('wrong phrase')
        await expect(confirm).to_be_disabled()
        await confirm.dispatch_event('click')
        assert not deletes
        await field.fill(WORD[lang])
        await expect(confirm).to_be_enabled()

        # A local profile without an authenticated session is not an account deletion.
        await page.evaluate("localStorage.removeItem('hamzaban.token.v1')")
        await confirm.click()
        await expect(page.locator('#toast-text')).to_have_text(REQUIRED[lang])
        assert not deletes and page.url.endswith('/app.html')
        assert await page.evaluate("!!localStorage.getItem('hamzaban.user.v1')")
        await page.evaluate("t => localStorage.setItem('hamzaban.token.v1', t)", session['token'])

        for mode in ['offline', '503', 'empty', 'false', 'string', 'malformed']:
            async def fail(route, _request, *, mode=mode):
                if mode == 'offline':
                    await route.abort('failed')
                elif mode == 'malformed':
                    await route.fulfill(status=200, content_type='application/json', body='{')
                else:
                    payload = {'503': {'error': 'unavailable'}, 'empty': {}, 'false': {'ok': False}, 'string': {'ok': 'true'}}[mode]
                    await route.fulfill(status=503 if mode == '503' else 200, json=payload)
            await page.route('**/api/auth/account', fail)
            await confirm.click()
            await expect(confirm).to_be_enabled()
            await expect(page.locator('#toast-text')).to_have_text(FAILURE[lang])
            assert await page.evaluate("localStorage.getItem('hamzaban.token.v1')") == session['token']
            await api(setup.request, 'GET', '/auth/me', session['token'])
            await api(setup.request, 'GET', '/auth/me', peer['token'])
            await page.unroute('**/api/auth/account', fail)

        # Exercise the real ten-second AbortController deadline without an
        # intercepted route left hanging after cancellation.
        await page.clock.install()
        await page.evaluate("""() => {
            window.deleteTestFetch = window.fetch;
            window.deleteTestAborted = false;
            window.fetch = (url, options) => {
                if (url === '/api/auth/account' && options.method === 'DELETE') {
                    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => {
                        window.deleteTestAborted = true;
                        reject(new DOMException('Aborted', 'AbortError'));
                    }, {once: true}));
                }
                return window.deleteTestFetch(url, options);
            };
        }""")
        await confirm.click()
        await expect(confirm).to_be_disabled()
        await page.clock.fast_forward(10001)
        await expect(confirm).to_be_enabled()
        await expect(page.locator('#toast-text')).to_have_text(FAILURE[lang])
        assert await page.evaluate('window.deleteTestAborted')
        await page.evaluate('window.fetch = window.deleteTestFetch')
        await page.clock.resume()
        await api(setup.request, 'GET', '/auth/me', session['token'])

        # Simulate stale local bookings, not the server: its real 409 must win.
        async def stale_bookings(route):
            await route.fulfill(json={'bookings': []})
        await page.route('**/api/traveler/bookings', stale_bookings)
        booking = await api(setup.request, 'POST', '/traveler/bookings', session['token'],
                            {'kind': 'instant', 'origin_lang': 'ar', 'dest_lang': 'fa', 'place': 'Deletion regression', 'traveler_name': 'Ali'}, status=201)
        await page.evaluate("localStorage.setItem('hamzaban.bookings.v1', '[]')")
        await confirm.click()
        await expect(page.locator('#toast-text')).to_have_text(BLOCKED[lang])
        await api(setup.request, 'GET', '/auth/me', session['token'])
        await api(setup.request, 'POST', f"/traveler/bookings/{booking['id']}/cancel", session['token'])
        await page.unroute('**/api/traveler/bookings', stale_bookings)
        # Reload after the canceled booking so normal polling remains unmodified.
        await page.reload()
        await page.wait_for_function('() => window.hzBookingsSynced === true')
        await page.locator('nav a[data-nav=account]').click()
        await page.locator('#ac-delete').click()
        await field.fill(WORD[lang])

        # Pending deletion guards all clicks, including synthetic logout/delete.
        entered = asyncio.Event()
        async def delayed(route):
            entered.set()
            await release.wait()
            await route.continue_()
        await page.route('**/api/auth/account', delayed)
        before = len(deletes)
        await confirm.click()
        await entered.wait()
        await expect(confirm).to_be_disabled()
        await expect(field).to_be_disabled()
        await expect(confirm).to_have_attribute('aria-busy', 'true')
        for id in ['ac-delete-confirm', 'ac-logout', 'ac-logout-all']:
            await page.locator('#' + id).dispatch_event('click')
        assert len(deletes) == before + 1
        await api(setup.request, 'GET', '/auth/me', session['token'])
        release.set()
        await assert_cleared(page, lang)
        await expect(page.locator('#ident-notice')).to_have_text(SUCCESS[lang])
        for token in [session['token'], peer['token']]:
            await api(setup.request, 'GET', '/auth/me', token, status=401)
        await api(setup.request, 'GET', '/auth/me', outsider['token'])
        fresh = await sign_in(setup.request, phone)
        assert fresh['user']['id'] != session['user']['id']
        # A late *real* deletion response belongs to its original session only.
        await ctx.close()
        ctx, page = await seeded_context(browser, fresh, lang, errors)
        await page.locator('#ac-delete').click()
        await page.locator('#ac-delete-input').fill(WORD[lang])
        release.clear()
        entered.clear()
        await page.route('**/api/auth/account', delayed)
        await page.locator('#ac-delete-confirm').click()
        await entered.wait()
        await page.evaluate("""s => {
            localStorage.setItem('hamzaban.token.v1', s.token);
            const p = JSON.parse(localStorage.getItem('hamzaban.user.v1'));
            p.authUserId = s.user.id; p.phone = s.user.phone;
            localStorage.setItem('hamzaban.user.v1', JSON.stringify(p));
        }""", outsider)
        release.set()
        await expect(page.locator('#ac-delete-confirm')).to_be_enabled()
        assert page.url.endswith('/app.html')
        assert await page.evaluate("localStorage.getItem('hamzaban.token.v1')") == outsider['token']
        assert await page.evaluate("sessionStorage.getItem('hamzaban.auth.notice.v1')") is None
        await api(setup.request, 'GET', '/auth/me', fresh['token'], status=401)
        await api(setup.request, 'GET', '/auth/me', outsider['token'])
        assert not errors, errors
        print(f'PASS [{lang}]: phrase/auth guards, offline/unconfirmed/timeout failures, real active-booking rejection, one pending delete, peer revocation, confirmed deletion notice and late-response session isolation')
    except Exception:
        print('JavaScript errors:', errors)
        if page:
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(ARTIFACTS / f'{lang}.png'), full_page=True)
        raise
    finally:
        release.set()
        if ctx:
            await page.unroute_all(behavior='ignoreErrors')
            await ctx.unroute_all(behavior='wait')
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
