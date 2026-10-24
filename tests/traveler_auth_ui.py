"""Traveler sign-in must be server-confirmed, never email/demo-local success.

Real OTP/session APIs on an isolated HZ_DEV server; only delivery failures and
production config are intercepted. Covers fa/en/ar, single in-flight requests,
server revocation, profile/account binding and the development-only helper.
"""
import asyncio
import json
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from finish_flow_ui import BASE, api

ARTIFACTS = Path(__file__).parent / 'assets' / 'last_traveler_auth'
EMAIL_OFF = {
    'fa': 'ورود با ایمیل فعلاً فعال نیست. لطفاً از شماره همراه استفاده کنید.',
    'en': 'Email sign-in is not available. Please use a mobile number.',
    'ar': 'الدخول بالبريد الإلكتروني غير متاح حالياً. يرجى استخدام رقم الجوال.',
}
SMS_OFF = {
    'fa': 'ارسال پیامک فعلاً فعال نیست. بعداً دوباره تلاش کنید.',
    'en': 'SMS sending is not available right now. Try again later.',
    'ar': 'إرسال الرسائل النصية غير متاح حالياً. حاول لاحقاً.',
}
OTP_HEADER = {
    'fa': 'تأیید شماره همراه',
    'en': 'Mobile number verification',
    'ar': 'التحقق من رقم الجوال',
}
UNSUPPORTED_OTP_HEADERS = (
    'تأیید شماره و احراز هویت',
    'Identity & Code Verification',
    'تأكيد الرقم والتحقق من الهوية',
)


async def scenario(browser, lang):
    ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
    page = await ctx.new_page()
    page.set_default_timeout(20000)
    errors, posts = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: posts.append(r.url) if '/api/auth/' in r.url and r.method == 'POST' else None)
    request_release, verify_release = asyncio.Event(), asyncio.Event()
    try:
        # A historical demo/email profile is not an authenticated session.
        await ctx.add_init_script('localStorage.setItem("hamzaban_lang", ' + json.dumps(lang) + ');')
        await page.goto(BASE + '/traveler/index.html')
        await page.evaluate("() => localStorage.setItem('hamzaban.user.v1', JSON.stringify({name:'Old',last:'Demo',method:'email',contact:'guest@example.com'}))")
        await page.reload()
        await expect(page.locator('#step-identifier')).to_be_visible()
        assert page.url.endswith('/index.html')
        await page.locator('#tab-email').click()
        await expect(page.locator('#email-input')).to_be_disabled()
        await expect(page.locator('#ident-err')).to_have_text(EMAIL_OFF[lang])
        await expect(page.locator('#btn-request-otp')).to_be_disabled()
        # Even direct calls to legacy global functions cannot manufacture a login.
        await page.evaluate("""() => {
          handleRequestOTP(); handleResendCode();
          document.querySelectorAll('.otp-box').forEach((b,i)=>b.value='123456'[i]);
          handleVerifyOTP(); proceedAfterOtp();
          finishLogin({name:'Forged',last:'User'});
        }""")
        await expect(page.locator('#step-identity')).to_be_hidden()
        assert not posts and await page.evaluate("() => localStorage.getItem('hamzaban.token.v1')") is None
        print(f'PASS [{lang}]: cached email profile and demo code cannot sign in or send auth requests')

        await page.locator('#tab-phone').click()
        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        await page.locator('#phone-input').fill(phone)
        await page.locator('#check-age').check()
        await page.locator('#check-terms').check()
        async def unavailable(route):
            await route.fulfill(status=503, json={'error': 'sms_unavailable'})
        await page.route('**/api/auth/request-code', unavailable)
        await page.locator('#btn-request-otp').click()
        await expect(page.locator('#ident-err')).to_have_text(SMS_OFF[lang])
        await expect(page.locator('#step-otp')).to_be_hidden()
        await expect(page.locator('#btn-request-otp')).to_be_enabled()
        await page.unroute('**/api/auth/request-code', unavailable)

        requests, verifications = [], []
        request_arrived, verify_arrived = asyncio.Event(), asyncio.Event()
        async def delayed_request(route):
            requests.append(route.request.post_data_json)
            request_arrived.set()
            await request_release.wait()
            await route.continue_()
        async def delayed_verify(route):
            verifications.append(route.request.post_data_json)
            verify_arrived.set()
            await verify_release.wait()
            await route.continue_()
        await page.route('**/api/auth/request-code', delayed_request)
        await page.locator('#btn-request-otp').click()
        await asyncio.wait_for(request_arrived.wait(), 20)
        await expect(page.locator('#btn-request-otp')).to_be_disabled()
        await page.evaluate('() => handleRequestOTP()')
        assert len(requests) == 1
        request_release.set()
        await expect(page.locator('#step-otp')).to_be_visible()
        await expect(page.locator('#step-otp [data-i18n="otp_header"]')).to_have_text(OTP_HEADER[lang])
        otp_step_text = await page.locator('#step-otp').inner_text()
        for unsupported_header in UNSUPPORTED_OTP_HEADERS:
            assert unsupported_header not in otp_step_text, f'OTP screen overstates identity verification in {lang}: {unsupported_header}'
        async with page.expect_response(lambda r: r.url.endswith('/api/auth/verify')) as rejected:
            for i, digit in enumerate('000000'):
                await page.locator('.otp-box').nth(i).fill(digit)
        assert (await rejected.value).status == 401
        await expect(page.locator('#otp-err')).to_be_visible()
        await expect(page.locator('#step-identity')).to_be_hidden()
        assert await page.evaluate("() => localStorage.getItem('hamzaban.token.v1')") is None
        await page.route('**/api/auth/verify', delayed_verify)
        # Last digit auto-submits; a duplicate click while the API is pending must not.
        for i, digit in enumerate('123456'):
            await page.locator('.otp-box').nth(i).fill(digit)
        await asyncio.wait_for(verify_arrived.wait(), 20)
        await expect(page.locator('#btn-verify')).to_be_disabled()
        await page.evaluate('() => handleVerifyOTP()')
        assert len(verifications) == 1
        verify_release.set()
        await expect(page.locator('#step-identity')).to_be_visible()
        await expect(page.locator('#step-identifier')).to_be_hidden()
        await page.locator('#id-name').fill('Ali')
        await page.locator('#id-last').fill('Rezaei')
        await page.locator('.id-gender').nth(1).click()
        await page.locator('#id-save').click()
        await expect(page).to_have_url(BASE + '/traveler/app.html')
        token = await page.evaluate("() => localStorage.getItem('hamzaban.token.v1')")
        user = await api(ctx.request, 'GET', '/auth/me', token)
        profile = await page.evaluate("() => JSON.parse(localStorage.getItem('hamzaban.user.v1'))")
        assert user['phone'] == phone and profile['authUserId'] == user['id'] and profile['phone'] == phone
        assert len(requests) == 1 and len(verifications) == 1
        await page.goto(BASE + '/traveler/index.html')
        await expect(page).to_have_url(BASE + '/traveler/app.html')
        # A token for another account cannot reuse the first account's cached identity.
        other = '9' + str(secrets.randbelow(900000000) + 100000000)
        await api(ctx.request, 'POST', '/auth/request-code', data={'phone': other, 'role': 'traveler'})
        second = await api(ctx.request, 'POST', '/auth/verify', data={'phone': other, 'role': 'traveler', 'code': '123456'})
        await page.evaluate('(t) => localStorage.setItem("hamzaban.token.v1",t)', second['token'])
        await page.goto(BASE + '/traveler/index.html')
        await expect(page.locator('#step-identity')).to_be_visible()
        await expect(page.locator('#id-name')).to_be_empty()
        # Revoke that session server-side: even a cached profile is not sufficient.
        await api(ctx.request, 'POST', '/auth/logout', second['token'])
        async with page.expect_response(lambda r: r.url.endswith('/api/auth/me')) as response:
            await page.reload()
        assert (await response.value).status == 401
        await page.wait_for_function("() => !localStorage.getItem('hamzaban.token.v1')")
        await expect(page.locator('#step-identifier')).to_be_visible()
        await expect(page.locator('#step-identity')).to_be_hidden()
        # Confirmed logout must clear the token as well as the cached identity;
        # otherwise the new session restore would immediately reopen identity entry.
        await page.evaluate('(t) => localStorage.setItem("hamzaban.token.v1",t)', token)
        await page.goto(BASE + '/traveler/index.html')
        await expect(page).to_have_url(BASE + '/traveler/app.html')
        await page.locator('nav a[data-nav=account]').click()
        await page.locator('#ac-logout').click()
        await expect(page).to_have_url(BASE + '/traveler/index.html')
        await expect(page.locator('#step-identifier')).to_be_visible()
        assert await page.evaluate("() => localStorage.getItem('hamzaban.token.v1')") is None
        await api(ctx.request, 'GET', '/auth/me', token, status=401)
        assert not errors, errors
        print(f'PASS [{lang}]: phone-only OTP wording; delivery retry, single request/verify, account-bound profile and revocation')
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        print('JavaScript errors:', errors)
        await page.screenshot(path=str(ARTIFACTS / f'auth-{lang}.png'), full_page=True)
        raise
    finally:
        request_release.set()
        verify_release.set()
        await ctx.close()


async def production_helper(browser):
    ctx = await browser.new_context(service_workers='block')
    page = await ctx.new_page()
    try:
        async def production(route):
            await route.fulfill(json={'dev': False})
        await page.route('**/api/config', production)
        await page.goto(BASE + '/traveler/index.html')
        await page.locator('#phone-input').fill('9' + str(secrets.randbelow(900000000) + 100000000))
        await page.locator('#check-age').check()
        await page.locator('#check-terms').check()
        await page.locator('#btn-request-otp').click()
        await expect(page.locator('#step-otp')).to_be_visible()
        await expect(page.locator('#btn-test-code')).to_be_hidden()
        await page.evaluate('() => fillTestCode()')
        assert await page.locator('.otp-box').evaluate_all('(bs) => bs.every(b => !b.value)')
        print('PASS: production config does not offer or execute development-code autofill')
    finally:
        await ctx.close()


async def main():
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        for lang in ['fa', 'en', 'ar']:
            await scenario(browser, lang)
        await production_helper(browser)
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
