"""Account-bound, server-backed translator notifications on mobile and desktop."""
import asyncio
import os
import re
import secrets
from pathlib import Path
from playwright.async_api import async_playwright, expect
from hz_api import LOGIN_JS

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_translator_notifications'
PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
READY = 'اعلان‌های ثبت‌شدهٔ این حساب از سرور دریافت شدند.'
ERROR = 'دریافت اعلان‌ها انجام نشد. دوباره تلاش کنید.'
CHANGED = 'حساب تغییر کرده است؛ اعلان‌ها را دوباره دریافت کنید.'


async def api(page, method, path, token=None, body=None, admin=False):
    return await page.evaluate("""async ({method, path, token, body, admin}) => {
      const headers = {};
      if (body !== null && body !== undefined) headers['Content-Type'] = 'application/json';
      if (token) headers[admin ? 'X-Admin-Token' : 'Authorization'] = admin ? token : 'Bearer ' + token;
      const response = await fetch(path, {method, headers, body: body === null || body === undefined ? undefined : JSON.stringify(body), cache: 'no-store'});
      let data = null; try { data = await response.json(); } catch (_) {}
      return {status: response.status, data};
    }""", {'method': method, 'path': path, 'token': token, 'body': body, 'admin': admin})


async def translator_token(page, phone):
    token = await page.evaluate(LOGIN_JS, phone)
    assert token, 'translator login did not issue a token'
    return token


async def create_real_rejection(page, translator, phone):
    uploaded = await api(page, 'POST', '/api/translator/documents', translator, {
        'kind': 'criminal_record', 'data': PNG, 'expires_at': '2035-01-01'
    })
    assert uploaded['status'] == 200 and uploaded['data']['status'] == 'uploaded', uploaded
    login = await api(page, 'POST', '/api/admin/login', body={
        'password': os.environ.get('HZ_ADMIN_PASSWORD', 'test-admin-pass')
    })
    assert login['status'] == 200 and login['data'].get('token'), login
    admin = login['data']['token']
    docs = await api(page, 'GET', '/api/admin/documents?status=uploaded', admin, admin=True)
    assert docs['status'] == 200, docs
    doc = next((d for d in docs['data']['documents'] if d['phone'] == phone and d['kind'] == 'criminal_record'), None)
    assert doc, 'uploaded test document missing from admin review queue'
    reason = '<img src=x onerror=window.__notificationXss=1>'
    rejected = await api(page, 'POST', f"/api/admin/documents/{doc['id']}/decision", admin,
                         {'decision': 'reject', 'reason': reason}, admin=True)
    assert rejected['status'] == 200 and rejected['data'].get('ok') is True, rejected
    feed = await api(page, 'GET', '/api/translator/notifications', translator)
    assert feed['status'] == 200 and len(feed['data']['notifications']) == 1, feed
    item = feed['data']['notifications'][0]
    assert item['kind'] == 'doc_rejected' and reason in item['text'], item
    return item, reason


async def scenario(browser, width):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, service_workers='block')
    page = await context.new_page()
    page.set_default_timeout(15000)
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    phone = '9' + str(secrets.randbelow(900000000) + 100000000)
    notification_requests = []
    page.on('request', lambda req: notification_requests.append(req.method)
            if '/api/translator/notifications' in req.url else None)
    try:
        await page.goto(BASE + '/translator/index.html')
        first_token = await translator_token(page, phone)
        item, reason = await create_real_rejection(page, first_token, phone)
        # Login helper seeds only this browser's session; the notification is independently created by the real admin workflow.
        await page.goto(BASE + '/translator/app.html')
        await page.locator('#notifications-btn').wait_for(state='visible')
        notification_requests.clear()
        button = page.locator('#notifications-btn')
        panel = page.locator('#inline-notifications-panel')
        status = page.locator('#notifications-status')
        listing = page.locator('#notifications-list')
        retry = page.locator('#notifications-retry')
        read_disabled = page.locator('#notifications-mark-read')

        await button.click()
        await expect(panel).to_be_visible()
        await expect(button).to_have_attribute('aria-expanded', 'true')
        await expect(status).to_have_text(READY)
        card = listing.locator('[data-notification-id]')
        await expect(card).to_have_count(1)
        await expect(card).to_contain_text('گواهی عدم سوءپیشینه')
        await expect(card).to_contain_text(reason)
        assert await card.locator('img').count() == 0, 'untrusted notification text became HTML'
        assert await page.evaluate('window.__notificationXss || false') is False
        assert await page.locator('#notifications-btn .bg-error').count() == 0, 'a fake unread badge is still shown'
        assert 'واریز موفق پایا' not in await panel.inner_text()
        assert '۱,۸۵۰,۰۰۰' not in await panel.inner_text()
        assert await read_disabled.is_disabled(), 'read state must not claim to work without server support'
        # The unsupported read action is inert, and notifications are fetched read-only.
        await read_disabled.evaluate('(button) => button.click()')
        assert notification_requests == ['GET'], notification_requests
        assert item['id'] == int(await card.get_attribute('data-notification-id'))

        await retry.click()
        await expect(status).to_have_text(READY)
        assert notification_requests == ['GET', 'GET'], notification_requests
        await page.locator('#notifications-close').click()
        await expect(panel).to_be_hidden()
        await expect(button).to_have_attribute('aria-expanded', 'false')
        await expect(button).to_be_focused()

        # HTTP/auth failures clear the previous notification and leave retry available.
        async def unauthorized(route):
            await route.fulfill(status=401, content_type='application/json', body='{"error":"unauthorized"}')
        await page.route('**/api/translator/notifications', unauthorized)
        await button.click()
        await expect(status).to_have_text(ERROR)
        await expect(listing.locator('[data-notification-id]')).to_have_count(0)
        await expect(retry).to_be_enabled()
        await page.unroute_all(behavior='wait')
        await retry.click()
        await expect(status).to_have_text(READY)
        await expect(card).to_have_count(1)

        async def offline(route):
            await route.abort()
        await page.route('**/api/translator/notifications', offline)
        await retry.click()
        await expect(status).to_have_text(ERROR)
        await expect(listing.locator('[data-notification-id]')).to_have_count(0)
        await page.unroute_all(behavior='wait')
        await retry.click()
        await expect(status).to_have_text(READY)
        await expect(card).to_have_count(1)

        async def malformed(route):
            await route.fulfill(status=200, content_type='application/json', body='{"notifications":[{}]}')
        await page.route('**/api/translator/notifications', malformed)
        await retry.click()
        await expect(status).to_have_text(ERROR)
        await expect(listing.locator('[data-notification-id]')).to_have_count(0)
        await page.unroute_all(behavior='wait')
        await retry.click()
        await expect(status).to_have_text(READY)
        await expect(card).to_have_count(1)

        # A second account has no access to the first account's private notification.
        second_phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        second_token = await translator_token(page, second_phone)
        await page.evaluate("""(token) => {
          const state = HZ.load(); state.token = token; HZ.save(state);
          window.dispatchEvent(new Event('storage'));
        }""", second_token)
        await expect(status).to_have_text(CHANGED)
        await expect(listing.locator('[data-notification-id]')).to_have_count(0)
        await retry.click()
        await expect(status).to_have_text('اعلانی برای این حساب ثبت نشده است.')
        await expect(listing.locator('[data-notification-id]')).to_have_count(0)

        # No token means no request and no cached account's content.
        before = len(notification_requests)
        await page.evaluate("""() => {
          const state = HZ.load(); state.token = null; HZ.save(state);
          window.dispatchEvent(new Event('storage'));
        }""")
        await expect(status).to_have_text(CHANGED)
        await retry.click()
        await expect(status).to_have_text('برای دریافت اعلان‌ها دوباره وارد شوید.')
        assert len(notification_requests) == before, notification_requests
        await expect(listing.locator('[data-notification-id]')).to_have_count(0)

        # Deliberately ignore AbortSignal, then close: the delayed response must never repaint the panel.
        await page.evaluate("""(token) => {
          const state = HZ.load(); state.token = token; HZ.save(state);
          window.dispatchEvent(new Event('storage'));
          window.originalNotificationsFetch = window.fetch;
          window.holdNotification = true;
          window.fetch = (url, options) => String(url) === '/api/translator/notifications' && window.holdNotification
            ? new Promise(resolve => { window.releaseNotification = () => resolve(new Response(JSON.stringify({notifications:[{
                id: 999999, kind:'doc_rejected', doc_kind:'criminal_record', doc_name:'x', created_at:new Date().toISOString(), text:'پاسخ قدیمی حساب قبلی'
              }]}), {status:200, headers:{'Content-Type':'application/json'}})); })
            : window.originalNotificationsFetch(url, options);
        }""", first_token)
        await retry.click()
        await page.wait_for_function('typeof window.releaseNotification === "function"')
        await page.keyboard.press('Escape')
        await expect(panel).to_be_hidden()
        await page.evaluate('window.releaseNotification()')
        await page.wait_for_timeout(150)
        assert await listing.locator('[data-notification-id]').count() == 0
        await expect(button).to_be_focused()
        assert not errors, errors
        print(f'PASS [{width}]: real per-account notice, safe rendering, no fake read/badge, retry/errors, account isolation, Escape and stale-response protection')
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(ARTIFACTS / f'failure-{width}.png'), full_page=True)
            (ARTIFACTS / f'failure-{width}.html').write_text(await page.content())
        except Exception:
            pass
        raise
    finally:
        await context.close()


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=['--no-sandbox'])
        try:
            await scenario(browser, 390)
            await scenario(browser, 1280)
        finally:
            await browser.close()
    print('RESULT: PASS (2/2 viewports)')


asyncio.run(main())
