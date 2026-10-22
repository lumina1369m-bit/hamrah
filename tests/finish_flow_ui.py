"""Real-browser regression: translator requests, traveler rejects/approves or finishes early.

Requires a disposable HZ_DEV=1 server. Fails with a nonzero exit code on any
unexpected API response, missing control, JavaScript error, or changed total.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets

from playwright.async_api import async_playwright, expect
from hz_api import LOGIN_JS

BASE = os.environ.get('BASE', 'http://127.0.0.1:8081').rstrip('/')
ARTIFACTS = Path(__file__).parent / 'assets' / 'last_finish_flow'


async def api(request, method, path, token=None, data=None, status=200):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    response = await request.fetch(BASE + '/api' + path, method=method,
                                   headers=headers, data=data)
    body = await response.json()
    assert response.status == status, (method, path, response.status, body)
    return body


async def booking(request, token, bid):
    body = await api(request, 'GET', '/traveler/bookings', token)
    return next(b for b in body['bookings'] if b['id'] == bid)


async def scenario(browser, own_finish):
    label = 'traveler-early-finish' if own_finish else 'reject-then-approve'
    category = 'business' if own_finish else 'general'
    traveler_ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                             service_workers='block')
    translator_ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                               service_workers='block')
    pages = []
    errors = []
    try:
        await api(traveler_ctx.request, 'POST', '/dev/offline-all')
        translator = await translator_ctx.new_page()
        traveler = await traveler_ctx.new_page()
        pages = [('traveler', traveler), ('translator', translator)]
        for _, page in pages:
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.set_default_timeout(20000)
        # Server-authenticated translator; test-only approval, never a production bypass.
        await translator.goto(BASE + '/translator/index.html')
        ttok = await translator.evaluate(LOGIN_JS, '9' + str(secrets.randbelow(900000000) + 100000000))
        assert ttok, 'Translator login failed'
        await api(translator_ctx.request, 'PATCH', '/translator/online', ttok, {'online': True})

        phone = '9' + str(secrets.randbelow(900000000) + 100000000)
        await api(traveler_ctx.request, 'POST', '/auth/request-code',
                  data={'phone': phone, 'role': 'traveler'})
        login = await api(traveler_ctx.request, 'POST', '/auth/verify',
                          data={'phone': phone, 'role': 'traveler', 'code': '123456'})
        ptok = login['token']
        user = {'name': 'علی', 'last': 'رضایی', 'gender': 'مرد', 'phone': phone, 'lang': 'fa'}
        await traveler_ctx.add_init_script(
            'localStorage.setItem("hamzaban.token.v1", ' + json.dumps(ptok) + ');'
            'localStorage.setItem("hamzaban.user.v1", ' + json.dumps(json.dumps(user)) + ');'
            'localStorage.setItem("hamzaban_lang", "fa");')
        # The booking/finish test must not depend on the availability or rate limits
        # of public map servers. Only geocoding is stubbed; all app APIs stay real.
        await traveler_ctx.route('https://nominatim.openstreetmap.org/**',
                                  lambda route: route.fulfill(json={'display_name': 'تهران، محل آزمون مرورگر'}))
        await traveler_ctx.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
        await traveler.goto(BASE + '/traveler/app.html')
        await expect(traveler.locator('#selected-location-title')).to_have_text('تهران، محل آزمون مرورگر')
        await traveler.locator('#confirm-location-btn').click()
        await expect(traveler.locator('#bottom-sheet')).to_be_visible()
        await traveler.locator(f'.cat-chip[data-cat={category}]').click()
        await traveler.locator('#btn-toggle-car').click()  # Default is car; test translator is pedestrian.
        # Actual booking button and actual server synchronization, not a local FSM shortcut.
        async with traveler.expect_response(lambda r: r.url.endswith('/api/traveler/bookings')
                                             and r.request.method == 'POST') as result:
            await traveler.locator('#btn-main-submit').click()
        response = await result.value
        assert response.status == 201, await response.text()
        created = await response.json()
        assert created['field'] == category, created
        sent = response.request.post_data_json
        assert sent['category'] == category and sent['car'] is False, sent
        bid, total = created['id'], created['total']
        assert total > 0
        offers = await api(translator_ctx.request, 'GET', '/translator/offers', ttok)
        assert len(offers['offers']) == 1, offers
        offer = offers['offers'][0]
        await api(translator_ctx.request, 'POST', f"/translator/offers/{offer['id']}/accept", ttok)
        await expect(traveler.locator('#stage-3')).to_be_visible()
        await traveler.locator('#btn-arrived').click()
        await expect(traveler.locator('#stage-4')).to_be_visible()
        await api(translator_ctx.request, 'POST', f'/translator/missions/{bid}/verify-code', ttok,
                  {'code': created['service_code']})
        await expect(traveler.locator('#stage-5')).to_be_visible()
        await expect(traveler.locator('#extension-card')).to_be_visible()
        await expect(traveler.locator('#finish-request-banner')).to_be_hidden()
        assert (await booking(traveler_ctx.request, ptok, bid))['total'] == total

        async def request_finish():
            await translator.goto(BASE + '/translator/app.html')
            # The initial translator tab is the calendar; use the visible mobile
            # navigation before interacting with workspace-only mission controls.
            await translator.locator('#mobile-nav [data-target=workspace]').click()
            button = translator.locator('#missions-list').get_by_role('button', name='درخواست پایان خدمت', exact=True)
            async with translator.expect_response(lambda r: r.url.endswith(f'/missions/{bid}/finish')
                                                   and r.request.method == 'POST') as result:
                await button.click()
            response = await result.value
            assert response.status == 202, await response.text()
            await expect(traveler.locator('#finish-request-banner')).to_be_visible()
            pending = await booking(traveler_ctx.request, ptok, bid)
            assert pending['status'] == 'matched' and pending['finish_requested']
            assert pending['total'] == total
            # No payment may be recorded while only the translator has requested an end.
            await api(traveler_ctx.request, 'POST', f'/traveler/bookings/{bid}/payment', ptok,
                      {'method': 'cash'}, status=409)

        if not own_finish:
            await request_finish()
            async with traveler.expect_response(lambda r: r.url.endswith(f'/{bid}/finish-reject')) as result:
                await traveler.locator('#btn-reject-finish').click()
            assert (await result.value).status == 200
            await expect(traveler.locator('#finish-request-banner')).to_be_hidden()
            await expect(traveler.locator('#stage-5')).to_be_visible()
            continuing = await booking(traveler_ctx.request, ptok, bid)
            assert continuing['status'] == 'matched' and not continuing['finish_requested']
            assert continuing['total'] == total
            await request_finish()
            suffix, control, finished_by = 'finish-approve', '#btn-approve-finish', 'translator'
        else:
            suffix, control, finished_by = 'finish', '#btn-finish-service', 'traveler'

        async with traveler.expect_response(lambda r: r.url.endswith(f'/{bid}/{suffix}')
                                             and r.request.method == 'POST') as result:
            await traveler.locator(control).click()
        response = await result.value
        assert response.status == 200, await response.text()
        await expect(traveler.locator('#stage-6')).to_be_visible()
        final = await booking(traveler_ctx.request, ptok, bid)
        assert final['status'] == 'finished' and final['finished_by'] == finished_by
        assert final['total'] == total, 'Early finish must not discount the agreed total'
        assert not errors, errors
        print(f'PASS: {label}; full agreed total preserved ({total})')
    except Exception:
        print('JavaScript errors:', errors)
        for name, page in pages:
            try:
                print(name, 'URL:', page.url)
                print(name, 'UI:', (await page.locator('body').inner_text())[-600:])
            except Exception:
                pass
        if 'ttok' in locals():
            print('Server missions:', await api(translator_ctx.request, 'GET', '/translator/missions', ttok))
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        for name, page in pages:
            try:
                await page.screenshot(path=str(ARTIFACTS / f'{label}-{name}.png'), full_page=True)
            except Exception:
                pass  # Preserve the original assertion/timeout, not a screenshot error.
        raise
    finally:
        await traveler_ctx.close()
        await translator_ctx.close()


async def main():
    # App synchronization runs every 5s and the FSM every 1s. Playwright's
    # default assertion timeout is only 5s (independent of page timeouts).
    expect.set_options(timeout=20000)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        try:
            await scenario(browser, own_finish=False)
            await scenario(browser, own_finish=True)
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
